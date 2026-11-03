"""一次性技术验证：MediaKit video-understand-router / semantic-segment。不进产品代码。
用法：uv run python spike.py upload | run <clip> <variant> | seg <clip>"""
import json, sys, time, urllib.parse, uuid
from pathlib import Path
sys.path.insert(0, "/Users/lance/Development/ai/ai-precut")
from pipeline import cloud

OUT = Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
CLIPS = Path(__file__).parent / "clips"
IDS = OUT / "file_ids.json"

PROMPT = """你是纪录片剪辑助理。请逐段描述这段视频的画面，覆盖整段视频，不要遗漏没有人说话的时间段。
只输出一个 JSON 对象，不要输出其它文字，格式：
{"events":[{"start":秒数,"end":秒数,"shot":"景别：特写/近景/中景/全景","people":"画面里的人数、谁在做什么、是否面向镜头","action":"发生了什么","objects":["画面中重要的物品"],"text_on_screen":"画面上能读到的文字，没有则为空字符串","usable":"画面能否用于成片：可用/一般/不可用，并说明原因"}]}
要求：start/end 为相对本视频开头的秒数（数字，可带一位小数），按时间顺序、首尾相接覆盖 0 到视频结尾；画面内容变化时就开始新的一段，每段一般 3–20 秒。"""

VARIANTS = {
    "eco": {"level": "Economy"},
    "bal": {"level": "Balanced"},
    "eco_audio": {"level": "Economy", "manual_option": {"fps": 1.0, "need_audio": True}},
    "man_fps1": {"manual_option": {"fps": 1.0, "need_audio": False}},
    "man_fps2": {"manual_option": {"fps": 2.0, "need_audio": False}},
}

class C(cloud.CloudClient):
    tool = "video-understand-router"
    def _upload_target(self):
        data = self._request("POST", cloud.UPLOAD_PATH, {"tool_name": self.tool}, self.timeout_submit)
        res = data.get("result") if isinstance(data.get("result"), dict) else data
        return res["file_id"], res["upload_url"], str(res.get("method") or "PUT").upper(), \
            cloud._parse_upload_headers(res.get("upload_headers"))

def submit(c, tool, payload):
    t0 = time.time()
    data = c._request("POST", f"/api/v1/tools/{tool}", payload, 60)
    tid = data.get("task_id") or (data.get("result") or {}).get("task_id")
    print("task", tid, flush=True)
    res = c.wait_task(str(tid), total_timeout=1800, interval=10)
    res["_elapsed_s"] = round(time.time() - t0, 1)
    return res

def main():
    c = C()
    cmd = sys.argv[1]
    ids = json.loads(IDS.read_text()) if IDS.exists() else {}
    if cmd == "upload":
        for p in sorted(CLIPS.glob("*.mp4")):
            if p.stem not in ids:
                ids[p.stem] = c._upload(p, None); IDS.write_text(json.dumps(ids, indent=1))
        print(ids)
    elif cmd == "run":
        clip, var = sys.argv[2], sys.argv[3]
        payload = {"video_urls": [ids[clip]], "prompt": PROMPT, **VARIANTS[var]}
        res = submit(c, "video-understand-router", payload)
        (OUT / f"{clip}_{var}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        print(json.dumps({k: res.get(k) for k in ("status", "token_usage", "_elapsed_s", "duration")}, ensure_ascii=False))
    elif cmd == "seg":
        clip = sys.argv[2]
        res = submit(c, "semantic-segment", {"video_url": ids[clip]})
        (OUT / f"{clip}_seg.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        print(json.dumps(res, ensure_ascii=False)[:800])

main()

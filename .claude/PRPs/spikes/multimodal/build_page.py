import json, glob, os, re, sys
S = sys.argv[1]; ROOT = "/Users/lance/Development/ai/ai-precut"
OUT = f"{S}/out"
CLIPS = {"A": (0, 180, "办公室 → 电梯 → 室外（大段无人声）"),
         "B": (2300, 280, "签培训协议、盖章、微信付款"),
         "C": (1200, 180, "围桌长时间对话")}
VAR_LABEL = {"eco": "省钱档 Economy", "bal": "均衡档 Balanced", "eco_audio": "省钱档 + 音频",
             "man_fps1": "手动 1 fps", "man_fps2": "手动 2 fps"}
segs = json.load(open(f"{ROOT}/projects/2026-09-01_080055/work/segments.json"))
segs = segs["segments"] if isinstance(segs, dict) else segs
data = {}
for c, (a, dur, desc) in CLIPS.items():
    asr = []
    for s in segs:
        for l in s["lines"]:
            if l["end"] > a and l["start"] < a + dur:
                asr.append({"start": round(max(0, l["start"] - a), 1), "end": round(min(dur, l["end"] - a), 1),
                            "speaker": "spk" + str(l.get("speaker", s["speaker"])), "text": l["text"]})
    variants = []
    for v in VAR_LABEL:
        f = f"{OUT}/{c}_{v}.json"
        if not os.path.exists(f): continue
        r = json.load(open(f))
        ev = json.loads(re.sub(r"^```(json)?|```$", "", r["contents"][0].strip()))["events"]
        variants.append({"key": v, "label": VAR_LABEL[v], "tokens": r["token_usage"], "elapsed": r["_elapsed_s"], "events": ev})
    seg = json.load(open(f"{OUT}/{c}_seg_result.json"))["segments"]
    item = {"desc": desc, "offset": a, "duration": dur, "asr": asr, "variants": variants,
            "semantic": [{"start": x["start_ms"] / 1000, "end": x["end_ms"] / 1000} for x in seg]}
    f = f"{OUT}/{c}_audio_asr.json"
    if os.path.exists(f):
        r = json.load(open(f))
        item["model_asr"] = {"tokens": r["token_usage"], "elapsed": r["_elapsed_s"],
                             "lines": json.loads(r["contents"][0])["lines"]}
    data[c] = item
tpl = open(f"{S}/page_template.html", encoding="utf-8").read()
open(f"{S}/index.html", "w", encoding="utf-8").write(tpl.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False)))
print("ok", {c: len(d["variants"]) for c, d in data.items()})

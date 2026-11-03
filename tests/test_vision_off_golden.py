"""画面理解第 4 阶段的底线：关闭画面理解时，逐句标注与三档判定的产物、发给模型的提示词逐字节不变。

哈希是在接入画面之前录下的。这里变红 = 关闭时的结果被改了（哪怕只多一个键）。
"""
import hashlib
import json
import re

import pytest

from pipeline import classify
from pipeline import understand_text as ut

TEXT_SHA256 = "43654c9c328b6b4743247cb1bde429df2f904802efaefce53894fe542da3b0e7"
SCORED_SHA256 = "18c84c5100870bb2f24c54f6f323f6611ea5014f6cf041296ded6d50a8a9778a"
PROMPTS_SHA256 = "44fbe43b3fca689ffb676540309da0825b18e57633c8605f70af29f22888867a"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(ut, "_sleep", lambda _s: None)


class GoldenClient:
    """确定性的假模型：标注只取决于 id，记下每次收到的提示词。"""
    model = "golden"

    def __init__(self):
        self.prompts = []

    def chat_json(self, system, user, **kw):
        self.prompts.append([system, user])
        ids = re.findall(r"^(S\d{3}) ", user, flags=re.M)
        if "归并成" in user:
            return {"topics": [{"name": "开场寒暄", "segment_ids": ids[:3]},
                               {"name": "讲解合同条款", "segment_ids": ids[3:]}]}
        kinds = ("金额价格", "闲聊寒暄", "事实陈述", "条款期限")
        return {"segments": [{"id": i, "info_type": kinds[int(i[1:]) % 4], "key_info": int(i[1:]) % 4 == 0,
                              "entities": ["九千八"] if int(i[1:]) % 4 == 0 else [], "reason": "依据"}
                             for i in ids]}


def _segments():
    durs = (2.0, 8.0, 5.0, 12.0, 7.0, 3.5, 9.0, 15.0)
    out, t = [], 0.0
    for i, d in enumerate(durs, 1):
        out.append({"id": f"S{i:03d}", "start": t, "end": t + d, "duration": d, "speaker": str(i % 2),
                    "text": f"第{i}句：学费九千八，三个月结业" if i % 3 else f"第{i}句闲聊"})
        t += d + 1.0
    return out


def _sha(path):
    # Windows 文本模式写出 \r\n：按 \n 算，同一份金标准在各平台都成立
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_vision_off_text_and_score_are_byte_identical(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "segments.json").write_text(json.dumps({"segments": _segments()}, ensure_ascii=False), encoding="utf-8")
    # 开过画面理解又关掉：残留文件不能影响结果
    (work / "visual_timeline.json").write_text(json.dumps({"events": [
        {"start": 0, "end": 80, "people": "两人", "action": "签合同", "text_on_screen": "培训协议书",
         "objects": ["合同"], "issues": ["背对镜头"]}]}, ensure_ascii=False), encoding="utf-8")
    (work / "vision_aligned.json").write_text("{}", encoding="utf-8")
    (work / "visual_quality.json").write_text(json.dumps({"segments": {"S005": {"flags": ["dark"]}}}),
                                              encoding="utf-8")
    client = GoldenClient()
    ut.run(work / "segments.json", work / "segments_text.json", client=client, model="golden",
           style="剪辑偏好：观众是家长")
    classify.run(work / "segments_text.json", None, work / "segments_scored.json", total_target=40.0,
                 visual_path=work / "visual_quality.json")
    prompts = hashlib.sha256(json.dumps(client.prompts, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert [_sha(work / "segments_text.json"), _sha(work / "segments_scored.json"), prompts] \
        == [TEXT_SHA256, SCORED_SHA256, PROMPTS_SHA256]

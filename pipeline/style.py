# -*- coding: utf-8 -*-
"""剪辑偏好（calibration）：程序运行时问剪辑员，而不是在代码里写死。

三个问题，对应三种会改变剪法的输入：
    1. 她更想保留信息还是情绪？        → tone
    2. 片子给谁看？                    → audience
    3. 有哪 2–3 句必须保留的原话？     → must_lines

回答会：
  * 拼成一段"剪辑偏好"指令，注入 b 路标注与摘要的提示词；
  * 调整选段的打分权重（信息优先 / 情绪优先）；
并把回答存进 project.json，随时可改、可重置。
"""
from __future__ import annotations

TONES = {"info": "信息优先", "emotion": "情绪优先", "balanced": "均衡"}

QUESTIONS = [
    ("tone", "她更想保留「信息」还是「情绪」？（info / emotion / balanced）"),
    ("audience", "这条片子主要给谁看？（例如：准备报名的家长）"),
    ("must_lines", "有哪 2–3 句必须保留的原话？（直接贴，没有就回车）"),
]


AUDIENCE_MAX = 60      # 字数上限（normalize 会截断；接口层先拒绝，不静默截断）
MUST_LINES_MAX_CHARS = 200


def normalize(calib: dict | None) -> dict:
    calib = calib or {}
    tone = str(calib.get("tone") or "balanced").strip()
    if tone not in TONES:
        tone = "balanced"
    return {
        "tone": tone,
        "audience": str(calib.get("audience") or "").strip()[:AUDIENCE_MAX],
        "must_lines": str(calib.get("must_lines") or "").strip()[:MUST_LINES_MAX_CHARS],
    }


def is_empty(calib: dict | None) -> bool:
    c = normalize(calib)
    return c["tone"] == "balanced" and not c["audience"] and not c["must_lines"]


def directive(calib: dict | None) -> str:
    """给 LLM 的偏好指令；没填就返回空串，提示词保持原样。"""
    c = normalize(calib)
    parts = []
    if c["audience"]:
        parts.append(f"观众是{c['audience']}")
    if c["tone"] == "info":
        parts.append("优先保留信息与事实，情绪镜头次之")
    elif c["tone"] == "emotion":
        parts.append("优先保留情绪、冲突与细节，事实次之")
    if c["must_lines"]:
        parts.append(f"以下原话必须保留：{c['must_lines']}")
    if not parts:
        return ""
    return "剪辑偏好（来自剪辑员，优先级高于默认规则）：" + "；".join(parts) + "。"


def weights(calib: dict | None) -> dict:
    """选段打分权重：信息优先则加信息权重，情绪优先则加音量/冲突权重。"""
    tone = normalize(calib)["tone"]
    if tone == "info":
        return {"info": 1.6, "emotion": 0.5}
    if tone == "emotion":
        return {"info": 0.8, "emotion": 2.0}
    return {"info": 1.0, "emotion": 1.0}


def apply_to_prompt(base: str, calib: dict | None) -> str:
    """把偏好指令拼到提示词末尾（无偏好则原样返回）。"""
    text = directive(calib)
    return f"{base}\n\n{text}" if text else base

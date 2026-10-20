# -*- coding: utf-8 -*-
"""确认与提问页 · 保存答案（KI-05）：「保存并确认」后自动按答案重新选段。

不依赖 server：调用方先校验项目名再传 pdir。决策问题损坏抛 schema.CorruptJSON（server → 409），
还没有决策问题抛 FileNotFoundError（→ 404），answers 不是对象抛 ValueError（→ 400）。
答案先落盘；重新选段起不来（已有任务在跑）不算保存失败，原因随结果返回给页面显示。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from gui import jobs, payloads
from pipeline import fingerprints, questions, schema, select_rules

RESELECT_TASK = "select"
ANSWERS_NOT_OBJECT = "answers 必须是对象（{题目 id: 选项}）"


def _stored_confirmed(work: Path) -> bool:
    """草稿保存（body 没带 confirmed）沿用文件里原来的确认状态；文件坏了当没确认（KI-49 同款，不让保存 409）。"""
    try:
        stored = schema.read_json(work / questions.ANSWERS_FILE, default={})
    except schema.CorruptJSON:
        return False
    return stored.get("confirmed") is True


def save_answers(pdir: Path, name: str, body: dict) -> dict:
    raw = body.get("answers") if body.get("answers") is not None else {}
    if not isinstance(raw, dict):
        raise ValueError(ANSWERS_NOT_OBJECT)
    work = Path(pdir) / "work"
    questions_def = schema.read_json(work / "questions.json", default=None)  # 损坏 → CorruptJSON
    if questions_def is None:
        raise FileNotFoundError(payloads.NO_QUESTIONS_MSG)
    answers = questions.normalize_answers(questions_def, raw)  # KI-49
    confirmed = (body["confirmed"] is True) if "confirmed" in body else _stored_confirmed(work)
    schema.write_json(work / questions.ANSWERS_FILE, {
        "answers": answers, "rules": select_rules.rules_from_answers(answers, questions_def),
        "rules_version": select_rules.RULES_VERSION,  # KI-84
        "confirmed": confirmed, "questions_digest": fingerprints.file_digest(work / "questions.json"),
        "at": datetime.now().isoformat(timespec="seconds")})
    if body.get("confirmed") is not True:  # 只有显式确认才起选段；草稿保存不动原来的确认状态
        return {"ok": True, "job_id": None}
    try:  # select 是本地计算：不外发、不需要 Key，不走 prepare 的前置检查
        return {"ok": True, "job_id": jobs.start_job(name, RESELECT_TASK, [])}
    except jobs.JobConflict as exc:  # 含 StaleJob：答案已保存，只是选段没能马上开始
        return {"ok": True, "job_id": None, "job_error": str(exc)}

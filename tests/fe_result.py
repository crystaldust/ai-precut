"""⑤ 看结果前端测试共用的数据与小工具（node vm）：/api/result 载荷、带手动修改的状态、加载入口。"""
import json
import re

from fe_browse import KEYS_SETUP
from fe_fixtures import NEW_ROUTES, NEW_STATE
from fe_harness import run_app, wizard

PROJECT_Q = "%E6%96%B0%E9%A1%B9%E7%9B%AE"  # encodeURIComponent('新项目')


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def text_of(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def result_wizard(result="available", export="available"):
    w = wizard(analyze="done", browse="done", criteria="done", result=result, export=export)
    return {**w, "next": "result"}


SHOTS = [{"id": "sh01", "in": 0, "out": 100, "sub": "<b>字幕</b>", "note": ""},
         {"id": "sh02", "in": 100, "out": 178, "sub": "二", "note": ""}]
MANUAL_OFF = {"edited": False, "count": 0, "changes": [], "more": 0}
MANUAL_ON = {"edited": True, "count": 3, "more": 2,
             "changes": ["第 4 镜改了字幕<b>", "新增第 7 镜「合同」", "删除了 00:52 那一镜"]}
PREVIEW_NONE = {"status": "none", "reasons": [], "at": None, "duration": None, "shots": None, "url": None}
PREVIEW_FRESH = {"status": "fresh", "reasons": [], "at": "2026-10-20T14:02:00", "duration": 178, "shots": 2,
                 "url": "/media/%E6%96%B0%E9%A1%B9%E7%9B%AE/current-preview?v=2026-10-20T14%3A02%3A00"}


def unused(id, start, end, cause="duration", label="因时长：这个话题的时长已经用完", topic="讲合同", text="原文", sub="字幕"):
    return {"id": id, "start": start, "end": end, "topic": topic, "topic_raw": topic, "text": text,
            "cause": cause, "cause_label": label, "shot": {"in": start, "out": end, "sub": sub}}


UNUSED = [
    unused("U9", 300, 310, "must", "剪辑列表里的片段 · 出片前必须加回", "讲退费<b>", "原文<i>九", "字幕九"),
    unused("U1", 30, 36, "duration", "因时长：这个话题的时长已经用完", "讲合同", "替代<i>句", "字幕一"),
    unused("U2", 120, 126, "removed", "你从分镜表里删掉了", "讲合同", "第二句", "字幕二"),
]
NOTES = {
    "sh01": {"why": "含金额<b>", "topic": "讲合同", "segment_id": "S1",
             "alternatives": [{"id": "U1", "start": 30, "end": 36, "text": "替代<i>句"}]},
    "sh02": {"why": "手动添加", "topic": None, "segment_id": None, "alternatives": []},
}
RESULT = {
    "topbar": {"target": 180, "total": 178, "shots": 2, "clip": {"count": 6, "covered": 6, "missing": []},
               "over_target": False, "must_total": 150, "suggested_target": None},
    "notes": NOTES, "unused": UNUSED, "preview": PREVIEW_NONE, "manual": MANUAL_OFF,
    "source": "selection", "wizard": result_wizard(),
}
RSTATE = {**NEW_STATE, "wizard": result_wizard(), "shots": SHOTS, "shots_from_selection": True,
          "selection_digest": "d1", "manual": MANUAL_OFF, "preview": {"status": "none"},
          "jianying": {"installed": False}, "versions": []}
RROUTES = {**NEW_ROUTES, "GET /api/state": RSTATE, "GET /api/result": RESULT,
           "POST /api/shots": {"ok": True, "count": 2}}

RESULT_SETUP = KEYS_SETUP + """
const R = () => state.result;
const rcalls = () => calls.filter(c => c.path.startsWith('/api/result?'));
const jobs = () => calls.filter(c => c.method === 'POST' && c.path === '/api/job').map(c => c.body);
const shotPosts = () => calls.filter(c => c.method === 'POST' && c.path.startsWith('/api/shots')).map(c => c.body);
"""


def in_result(script, routes=None, *, state=None, result=None, setup=""):
    """打开项目直接落在 ⑤（wizard.next = result），再跑 script。"""
    st = {**RSTATE, **(state or {})}
    body = ("(async () => { await selectProject('新项目'); await tick(); await tick();" + script + " })()")
    return run_app(body, routes={**RROUTES, "GET /api/state": st,
                                 "GET /api/result": {**RESULT, **(result or {})}, **(routes or {})},
                   setup=RESULT_SETUP + setup)


# state.manual（/api/state，refresh 刚读的）与 result.manual（/api/result，可能是 400ms 防抖前的旧值）可以不同
def in_result_split(script, *, state_manual, result_manual, routes=None, result=None, state=None):
    return in_result(script, routes, state={**(state or {}), "manual": state_manual},
                     result={**(result or {}), "manual": result_manual})

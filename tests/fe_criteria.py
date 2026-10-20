"""④ 定标准前端测试共用的数据与小工具（node vm）。"""
import json

from fe_browse import KEYS_SETUP
from fe_fixtures import NEW_ROUTES, NEW_STATE
from fe_harness import run_app, wizard


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def cseg(i, start, end, level, topic, text, *, reason="", override=False, unusable=False):
    return {"id": f"S{i}", "start": start, "end": end, "dur": end - start, "level": level,
            "level_reason": reason, "override": override, "unusable": unusable,
            "topic": topic, "topic_raw": topic, "text": text}


SEGS = [
    cseg(1, 0, 6, 3, "讲合同", "甲<b>粗体</b>", reason="信息密度高"),
    cseg(2, 10, 16, 2, "讲合同", "乙", reason="不确定<i>"),
    cseg(3, 20, 30, 2, "聊吃饭", "丙", reason="可能有用"),
    cseg(4, 40, 45, 2, "聊吃饭", "丁", reason="拿不准"),
    cseg(5, 50, 55, 1, "聊吃饭", "戊", reason="闲聊"),
]
PENDING = [{"id": s["id"], "start": s["start"], "end": s["end"]} for s in SEGS if s["level"] == 2]
QUESTIONS = [
    {"id": "q1", "text": "结尾<b>怎么收</b>？", "type": "single", "options": [
        {"label": "签字<i>", "effect": "结尾落在<u>签字</u>"}, {"label": "全部", "effect": "全收"}]},
    {"id": "q2", "text": "保留哪些？", "type": "multi", "options": [
        {"label": "合同", "effect": "保合同"}, {"label": "吃饭", "effect": "保吃饭"}]},
]
CONFIRM = {
    "questions": QUESTIONS, "fallback": False,
    "topics": [{"topic": "讲合同", "topic_raw": "讲合同", "count": 2},
               {"topic": "聊吃饭<b>", "topic_raw": "聊吃饭", "count": 3}],
    "segments": SEGS, "pending": PENDING,
    "speakers": [{"name": "老王<b>", "seconds": 200}, {"name": "小李", "seconds": 65}],
    "summary": {"summary": "讲了<i>合同</i>", "fallback": False,
                "key_points": [{"at": 12, "text": "关键<b>点</b>", "why": "因为<x>"}]},
    "answers": {}, "confirmed": False, "answers_unreadable": False, "stale_questions": False,
    "stale_hint": "", "warnings": [],
}
ALL_DECIDED = {**CONFIRM, "pending": [], "answers": {"q1": "全部", "q2": ["合同"]},
               "segments": [{**s, "level": 3} if s["level"] == 2 else s for s in SEGS]}
OK_LEVEL = {"ok": True, "segment": None, "clip_list": None, "wizard": None}
CRIT_STATE = {**NEW_STATE, "wizard": wizard()}
CRIT_ROUTES = {**NEW_ROUTES, "GET /api/state": CRIT_STATE, "GET /api/confirm": CONFIRM,
               "POST /api/browse/level": OK_LEVEL,
               "POST /api/confirm/answers": {"ok": True, "job_id": None, "wizard": None},
               "POST /api/topics/rename": {"ok": True, "topic_names": {}}}

# 键盘 / 请求辅助复用 ③ 的（K / press / posts / hold）；再加 ④ 的几个读取函数
CRIT_SETUP = KEYS_SETUP + """
const C = () => state.criteria;
const queueIds = () => C().queue.slice();
const levelPosts = () => calls.filter(c => c.method === 'POST' && c.path === '/api/browse/level').map(c => c.body);
const draftPosts = () => calls.filter(c => c.method === 'POST' && c.path === '/api/confirm/answers').map(c => c.body);
"""


def in_criteria(script, routes=None, wiz=None, setup=""):
    """wizard 默认 next=criteria：selectProject 之后就落在 ④（刷新里触发 enterCriteria），不要再 go 一次。"""
    state = {**CRIT_STATE, **({"wizard": wiz} if wiz else {})}
    body = ("(async () => { await selectProject('新项目'); await tick(); await tick();"
            + script + " })()")
    return run_app(body, routes={**CRIT_ROUTES, "GET /api/state": state, **(routes or {})},
                   setup=CRIT_SETUP + setup)

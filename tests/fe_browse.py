"""③ 看素材前端测试共用的数据与小工具（node vm）。"""
import json

from fe_fixtures import NEW_ROUTES, NEW_STATE
from fe_harness import run_app, wizard


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def seg(i, start, end, level, topic, text, *, reason="", flags=(), must=False, unusable=False,
        in_cut=False, override=False):
    return {"id": f"S{i}", "start": start, "end": end, "dur": round(end - start, 2), "level": level,
            "level_reason": reason, "text": text, "topic": topic, "topic_raw": topic,
            "visual_flags": list(flags), "must_keep": must, "unusable": unusable, "inCut": in_cut,
            "override": override}


SEGS = [
    seg(1, 0, 6, 3, "讲合同", "甲<b>粗体</b>", reason="信息密度高", flags=["soft", "dark"]),
    seg(2, 10, 16, 2, "讲合同", "乙", reason="不确定"),
    seg(3, 20, 30, 1, "聊吃饭", "丙", reason="闲聊", in_cut=True),
    seg(4, 40, 45, 3, "聊吃饭", "丁", reason="有结论", must=True),
    seg(5, 50, 55, 3, "聊吃饭", "戊", reason="有结论", unusable=True),
]

CLIP = {"items": [{"id": "S4", "start": 40, "end": 45, "dur": 5, "topic": "聊吃饭", "text": "丁"}],
        "total": 5, "target": 60, "over_target": False, "over_by": 0, "suggested_target": None}

BROWSE = {
    "project": {"name": "新项目", "title": "新项目", "target_duration": 60},
    "material_duration": 60,
    "summary": {"summary": "讲了<i>合同</i>的事", "fallback": True,
                "key_points": [{"at": 12, "text": "关键<b>点</b>", "why": "因为<x>"}], "cast": []},
    "counts": {"waste": 1, "pending": 1, "usable": 3},
    "topics": [{"name": "讲合同", "topic_raw": "讲合同", "budget": 20}],
    "segments": SEGS, "has_overrides": False,
    "speakers": [{"name": "老王<b>", "seconds": 200}, {"name": "小李", "seconds": 65}],
    "clip_list": CLIP, "warnings": ["有个警告<u>"],
}

STALE_WIZARD = wizard(analyze="done", browse="done", criteria="done",
                      result=("stale", "素材标记改过了 · 重新选段", "reselect"), export="available")
BROWSE_STATE = {**NEW_STATE, "wizard": wizard()}
BROWSE_ROUTES = {**NEW_ROUTES, "GET /api/state": BROWSE_STATE, "GET /api/browse": BROWSE}

KEYS_SETUP = """
const K = (code, extra = {}) => Object.assign({code, key: '', target: {tagName: 'BODY'}, repeat: false,
  prevented: false, stopped: false, preventDefault(){ this.prevented = true; }, stopPropagation(){ this.stopped = true; }}, extra);
const press = async (code, extra) => { const ev = K(code, extra); fireDoc('keydown', ev); await tick(); await tick(); return ev; };
const B = () => state.browse;
const posts = () => calls.filter(c => c.method === 'POST').map(c => [c.path, c.body]);
const hold = pred => {   // 挂起匹配的请求：返回放行函数列表（请求还没真正发出时 calls 里没有它）
  const orig = window.fetch, held = [];
  window.fetch = (p, o) => pred(String(p), o && o.body ? JSON.parse(o.body) : null)
    ? new Promise(r => held.push(() => r(orig(p, o)))) : orig(p, o);
  return held;
};
const ids = () => B().shown.map(i => B().segs[i].id);
"""


SIM = """
function sim(opts = {}){   // 模拟服务端：按请求改自己的一份状态，响应带 segment / clip_list / wizard
  const st = {}, base = JSON.parse(JSON.stringify(B().data));
  B().segs.forEach(s => { st[s.id] = {must_keep: s.must_keep, unusable: s.unusable, level: s.level,
    override: s.override, level_reason: s.level_reason, base: s.level}; });
  const clipOf = () => {
    const items = base.segments.filter(x => st[x.id].must_keep && !st[x.id].unusable)
      .map(x => ({id: x.id, start: x.start, end: x.end, dur: x.dur, topic: x.topic, text: x.text}));
    const total = items.reduce((n, i) => n + i.dur, 0);
    return {items, total, target: 60, over_target: total > 60, over_by: Math.max(0, total - 60), suggested_target: null};
  };
  window.__respond = (method, path, body) => {
    if (method === 'GET' && path.startsWith('/api/browse?')) {   // 重读：把服务端的标记带回去
      const d = JSON.parse(JSON.stringify(base));
      d.segments = d.segments.map(x => ({...x, must_keep: st[x.id].must_keep, unusable: st[x.id].unusable,
        level: st[x.id].level, override: st[x.id].override, level_reason: st[x.id].level_reason}));
      return [200, {...d, clip_list: clipOf()}];
    }
    if (method !== 'POST' || !path.startsWith('/api/browse/')) return respond(method, path);
    if (opts.fail && opts.fail(path, body)) return [500, {error: '炸了'}];
    const s = st[body.id]; let cleared = null, removed = [];
    if (path.endsWith('/must')) { if (body.must && s.unusable) { s.unusable = false; cleared = 'unusable'; } s.must_keep = body.must; }
    else if (path.endsWith('/unusable')) {
      if (body.unusable && s.must_keep) { s.must_keep = false; cleared = 'must_keep'; }
      s.unusable = body.unusable; removed = body.unusable ? (opts.removed || []) : []; }
    else if (body.level === null) { s.level = s.base; s.override = false; s.level_reason = '原因'; }
    else { s.level = body.level; s.override = true; s.level_reason = '人工改为' + body.level; }
    return [200, {ok: true, cleared, removed_shots: removed, segment: {id: body.id, ...s}, clip_list: clipOf(), wizard: SIM_WIZ}];
  };
}
"""


def mark_ok(seg_over=None, clip=CLIP, cleared=None, wiz=STALE_WIZARD, **extra):
    """标记接口的成功响应。seg_over：该段更新后的字段。"""
    return {"ok": True, "cleared": cleared, "segment": seg_over, "clip_list": clip, "wizard": wiz, **extra}


def in_browse(script, routes=None, wiz=None):
    state = {**BROWSE_STATE, **({"wizard": wiz} if wiz else {})}
    body = ("(async () => { await selectProject('新项目'); await go('browse'); await tick(); await tick();"
            + script + " })()")
    setup = KEYS_SETUP + f"const SIM_WIZ = {js(STALE_WIZARD)};" + SIM
    return run_app(body, routes={**BROWSE_ROUTES, "GET /api/state": state, **(routes or {})}, setup=setup)

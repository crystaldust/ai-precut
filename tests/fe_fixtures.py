"""向导前端测试共用的数据与小工具（从 test_frontend_wizard.py 拆出）。"""
import json

from fe_harness import run_app, wizard


"""M13b 向导外壳的前端行为（node vm）：步骤条、横幅、底部导航、更多菜单、项目栏、首次打开、新建、分析页、任务胶囊。"""


W = json.dumps(wizard(analyze="done", browse="available", criteria="available",
                      result=("locked", "先完成「④ 定标准」", None),
                      export=("locked", "先完成「④ 定标准」", None)))


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


PROJECTS = [{"name": "a<b", "title": "<i>片</i>", "versions": [], "step": {"n": 4, "label": "定标准"}},
            {"name": "p2", "title": "", "versions": ["v1"], "step": None}]


def provider(key, configured, source="keyring"):
    return {"key": key, "label": "火山引擎" if key == "mediakit" else "DeepSeek", "hint": "h",
            "configured": configured, "source": source if configured else "", "masked": "ab****cd" if configured else ""}


def config(consent, mediakit, deepseek, source="keyring"):
    return {"consent": consent, "providers": [provider("mediakit", mediakit, source),
                                              provider("deepseek", deepseek, source)]}


PRESETS = {"presets": [{"key": "纪实3min", "name": "纪实", "platform": "douyin", "duration": 175}],
           "warnings": ["已跳过预设「坏」：读不出来 <b>"]}


NEW_WIZARD = wizard(analyze="available", browse=("locked", "先完成「② 分析」", None),
                    criteria=("locked", "先完成「② 分析」", None),
                    result=("locked", "先完成「④ 定标准」", None), export=("locked", "先完成「④ 定标准」", None))


NEW_WIZARD["next"] = "analyze"


NEW_STATE = {"project": {"name": "新项目", "title": "新项目", "preset": "纪实3min", "platform": "douyin"},
             "wizard": NEW_WIZARD, "shots": [], "warnings": [], "versions": [], "segments": [], "job": None,
             "busy": None}


NEW_RESULT = {"topbar": {"target": 180, "total": 0, "shots": 0, "clip": {"count": 0, "covered": 0, "missing": []},
                         "over_target": False, "must_total": 0, "suggested_target": None},
              "notes": {}, "unused": [], "source": None, "wizard": None,
              "preview": {"status": "none", "reasons": [], "at": None, "duration": None, "shots": None, "url": None},
              "manual": {"edited": False, "count": 0, "changes": [], "more": 0}}  # ⑤ 的默认载荷（M14）


NEW_ROUTES = {"GET /api/presets": PRESETS, "GET /api/result": NEW_RESULT, "POST /api/new": {"ok": True, "name": "新项目"},
              "GET /api/projects": {"projects": [], "stale_job": None}, "GET /api/state": NEW_STATE,
              "GET /api/analysis": {"steps": [], "done": 0, "total": 11, "complete": False, "running": None,
                                    "failed": None, "notice": "分析大约 10–15 分钟，可以关掉窗口，回来接着跑"},
              "POST /api/job": {"job_id": "j1"}}


FILL_NEW = """
  el('#npPath').value = '/m/a.mp4'; el('#npName').value = '新项目'; el('#npTitle').value = '片名';
  el('#npPreset').value = '纪实3min'; el('#npMin').value = '3'; el('#npSec').value = '0';
"""


LABELS = ["读取素材", "生成浏览小样", "抽音轨", "云端转写", "声音分析", "画面检查", "AI 理解对话",
          "判定档位", "写内容摘要", "准备决策问题", "初步选段"]


def progress(done=0, running=None, failed=None, complete=False, seconds=None):
    steps = []
    for i, label in enumerate(LABELS):
        status = "done" if i < done else ("failed" if failed and i == done else
                                          ("running" if running == i else "waiting"))
        steps.append({"key": f"s{i}", "label": label, "status": status,
                      "seconds": (seconds if i < done else None)})
    return {"steps": steps, "done": done, "total": 11, "complete": complete,
            "running": f"s{running}" if running is not None else None,
            "notice": "分析大约 10–15 分钟，可以关掉窗口，回来接着跑",
            "failed": failed}


def in_project(script, routes=None):
    """已经打开了一个分析页：state 来自 NEW_STATE。"""
    return run_app("(async () => { await selectProject('新项目'); " + script + " })()",
                   routes={**NEW_ROUTES, **(routes or {})})


JOB_DONE_ROUTES = {"GET /api/job/": {"status": "done", "task": "prepare", "log": [], "elapsed_s": 5, "project": "新项目"}}


DONE_WIZARD = wizard(analyze="done", browse="done", criteria="available",
                     result=("locked", "先完成「④ 定标准」", None), export=("locked", "先完成「④ 定标准」", None))


def run_job_done(view, task="prepare", state_wizard=DONE_WIZARD, extra_state=None):
    st = {**NEW_STATE, "wizard": state_wizard, **(extra_state or {})}
    return in_project(f"""await go('analyze');
      state.view = {view!r};
      await startJob({task!r}, undefined, {{}});
      await runTimers(); await runTimers(); await runTimers();
      return [state.view, el('#toast').textContent, el('#mask').classList.contains('on')];""",
                      {**JOB_DONE_ROUTES, "GET /api/state": st,
                       "GET /api/job/": {**JOB_DONE_ROUTES["GET /api/job/"], "task": task}})


READY_WIZARD = wizard(analyze="done", browse="done", criteria="done", result="available", export="available")


READY_STATE = {**NEW_STATE, "wizard": READY_WIZARD,
               "shots": [{"id": "sh01", "in": 1, "out": 4.5, "sub": "<b>字幕</b>", "note": ""}],
               "shots_from_selection": True,
               "versions": [{"name": "v2", "shots": 3, "duration": 62, "mtime": "10-20 11:00", "draft": "<i>片名</i>_v2",
                             "preview": True, "windows_zip": "v2.zip", "windows_mb": 12.5},
                            {"name": "v1", "shots": 2, "duration": 30, "mtime": "10-19 11:00", "draft": "片名_v1",
                             "preview": False}]}


READY_RESULT = {"topbar": {"target": 180, "total": 3.5, "shots": 1, "clip": {"count": 0, "covered": 0, "missing": []},
                           "over_target": False, "must_total": 0, "suggested_target": None},
                "notes": {}, "unused": [], "source": "selection", "wizard": READY_WIZARD,
                "preview": {"status": "none", "reasons": [], "at": None, "duration": None, "shots": None, "url": None},
                "manual": {"edited": False, "count": 0, "changes": [], "more": 0}}  # ⑤ 的默认载荷（M14）


READY_ROUTES = {**NEW_ROUTES, "GET /api/state": READY_STATE, "GET /api/result": READY_RESULT}


def in_ready(script, routes=None):
    return run_app("(async () => { await selectProject('新项目'); " + script + " })()",
                   routes={**READY_ROUTES, **(routes or {})})

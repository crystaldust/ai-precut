"""M14 T6：⑤ 看结果的数据接口（/api/result、恢复为 AI 选段、两版对比、回到这一版、当前预览片）。"""
import json
from urllib.parse import quote

import pytest

from conftest import call, make_project
from gui import result_payload as rp
from pipeline import fingerprints, media_io, outputs, review, schema

pytestmark = pytest.mark.usefixtures("consented")


def _seg(i, start, topic, *, level=3, text=None, reason=""):
    return {"id": f"S{i}", "start": float(start), "end": start + 10.0, "level": level,
            "topic": topic, "text": text or f"原文{i}", "level_reason": reason}


SEGS = [_seg(1, 0, "合同", reason="含金额"), _seg(2, 20, "合同", reason="含条款"),
        _seg(3, 40, "退费"), _seg(4, 60, "退费"), _seg(5, 80, "合同", level=2),
        _seg(6, 100, "合同"), _seg(7, 120, "合同", level=1), _seg(8, 140, "闲聊")]
AI_SHOTS = [{"id": "sel01", "in": 0.0, "out": 10.0, "sub": "原文1", "note": "合同"},
            {"id": "sel02", "in": 60.0, "out": 70.0, "sub": "原文4", "note": "退费"}]
SELECTION = {
    "target": 175, "total": 20.0,
    "shots": [{"id": "sel01", "segment_id": "S1", "start": 0.0, "end": 10.0, "topic": "合同", "reason": "含金额 · 讲合同"},
              {"id": "sel02", "segment_id": "S4", "start": 60.0, "end": 70.0, "topic": "退费",
               "reason": "剪辑列表里的片段"}],
    "unused": [{"segment_id": "S2", "topic": "合同", "reason": "超出话题预算", "cause": "duration"},
               {"segment_id": "S3", "topic": "退费", "reason": "超出话题预算", "cause": "not_must"},
               {"segment_id": "S8", "topic": "闲聊", "reason": "话题未入选", "cause": "excluded"}],
}


def _project(root, *, manual=None, segs=SEGS, cfg_extra=None):
    files = {"work/segments_scored.json": json.dumps({"segments": segs, "topics": []}, ensure_ascii=False),
             "work/selection.json": json.dumps(SELECTION, ensure_ascii=False),
             "work/shots-selected.json": json.dumps({"shots": AI_SHOTS}, ensure_ascii=False)}
    pdir = make_project(root, shots=manual, **files)
    if cfg_extra:
        cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
        (pdir / "project.json").write_text(json.dumps({**cfg, **cfg_extra}), encoding="utf-8")
    review.set_must(pdir / "work", "S4", True)
    review.set_unusable(pdir / "work", "S6", True)
    return pdir


def _get(gs, path="/api/result?project=p1"):
    status, raw, _ = call(gs, "GET", path)
    return status, json.loads(raw)


def _ids(data):
    return [u["id"] for u in data["unused"]]


# ---------------------------------------------------------------- 顶栏
def test_topbar_for_ai_selection(gui_server):
    _project(gui_server.root)
    status, data = _get(gui_server)
    assert status == 200
    assert data["topbar"] == {"target": 175, "total": 20.0, "shots": 2,
                              "clip": {"count": 1, "covered": 1, "missing": []},
                              "over_target": False, "must_total": 10.0, "suggested_target": None}
    assert data["source"] == "selection"


def test_topbar_over_target_gives_suggested_target(gui_server):
    _project(gui_server.root, cfg_extra={"target_duration": 5})
    _, data = _get(gui_server)
    top = data["topbar"]
    assert top["target"] == 5 and top["over_target"] is True and top["suggested_target"] == 10


def test_clip_list_segment_missing_from_manual_table_is_not_covered(gui_server):
    _project(gui_server.root, manual=[AI_SHOTS[0]])
    _, data = _get(gui_server)
    assert data["source"] == "manual"
    assert data["topbar"]["clip"] == {"count": 1, "covered": 0, "missing": ["S4"]}
    assert data["topbar"]["shots"] == 1 and data["topbar"]["total"] == 10.0


def test_unusable_clip_list_segment_is_not_counted(gui_server):
    pdir = _project(gui_server.root)
    review.set_unusable(pdir / "work", "S4", True)
    _, data = _get(gui_server)
    assert data["topbar"]["clip"] == {"count": 0, "covered": 0, "missing": []}


# ---------------------------------------------------------------- 未采用清单
def test_unused_for_ai_selection_uses_selection_causes(gui_server):
    _project(gui_server.root)
    _, data = _get(gui_server)
    by_id = {u["id"]: u for u in data["unused"]}
    assert _ids(data) == ["S2", "S3", "S8"]          # 3 档以外、不可用、已进片的都不出现
    assert [by_id[k]["cause"] for k in ("S2", "S3", "S8")] == ["duration", "not_must", "excluded"]
    assert by_id["S2"]["cause_label"] == "因时长：这个话题的时长已经用完"
    assert by_id["S3"]["cause_label"] == "未勾选为必须记住的信息"
    assert by_id["S8"]["cause_label"] == "你在决策问题里排除了这个话题"
    assert by_id["S2"]["shot"] == {"in": 20.0, "out": 30.0, "sub": "原文2"}
    assert by_id["S2"]["start"] == 20.0 and by_id["S2"]["topic"] == "合同" and by_id["S2"]["text"] == "原文2"


def test_cause_labels_have_no_duplicate_cause(gui_server):
    """选段没有去重判断（KI-101）：不能出现「因重复」。"""
    assert "重复" not in "".join(rp.CAUSE_LABELS.values())
    assert set(rp.CAUSE_LABELS) == {"must", "removed", "excluded", "not_must", "duration", "other"}


def test_unused_with_manual_table_puts_missing_clip_list_first_and_marks_removed(gui_server):
    manual = [{"id": "m1", "in": 20.0, "out": 30.0, "sub": "手加", "note": ""}]   # 删了 S1、S4，手动加了 S2
    _project(gui_server.root, manual=manual)
    _, data = _get(gui_server)
    by_id = {u["id"]: u for u in data["unused"]}
    assert _ids(data) == ["S4", "S1", "S3", "S8"]     # S2 已被手动表覆盖；剪辑列表段排最前
    assert by_id["S4"]["cause"] == "must" and by_id["S4"]["cause_label"] == "剪辑列表里的片段 · 出片前必须加回"
    assert by_id["S1"]["cause"] == "removed" and by_id["S1"]["cause_label"] == "你从分镜表里删掉了"
    assert by_id["S3"]["cause"] == "not_must" and by_id["S8"]["cause"] == "excluded"


def test_unused_falls_back_to_legacy_reason_text_then_other(gui_server):
    legacy = {**SELECTION, "unused": [{"segment_id": "S2", "topic": "合同", "reason": "超出话题预算"},
                                      {"segment_id": "S3", "topic": "退费", "reason": "不在候选池"},
                                      {"segment_id": "S8", "topic": "闲聊", "reason": "莫名其妙"}]}
    pdir = _project(gui_server.root)
    (pdir / "work" / "selection.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    _, data = _get(gui_server)
    assert [u["cause"] for u in data["unused"]] == ["duration", "other", "other"]
    assert data["unused"][1]["cause_label"] == "没有进片"


def test_unused_text_is_clipped(gui_server):
    segs = [_seg(1, 0, "合同"), _seg(2, 20, "合同", text="长" * 1000)]
    _project(gui_server.root, segs=segs)
    _, data = _get(gui_server)
    assert len(data["unused"][0]["text"]) == 400


def test_unused_short_segment_fully_inside_a_shot_counts_as_used(gui_server):
    segs = [{**_seg(1, 0, "合同"), "end": 0.8}, _seg(2, 20, "合同")]
    _project(gui_server.root, segs=segs)
    _, data = _get(gui_server)
    assert "S1" not in _ids(data)


# ---------------------------------------------------------------- 每镜的说明与替代句
def test_notes_for_ai_selected_shots_use_selection_reason_and_same_topic_alternatives(gui_server):
    _project(gui_server.root)
    _, data = _get(gui_server)
    n1 = data["notes"]["sel01"]
    assert n1["why"] == "含金额 · 讲合同" and n1["topic"] == "合同" and n1["segment_id"] == "S1"
    assert n1["alternatives"] == [{"id": "S2", "start": 20.0, "end": 30.0, "text": "原文2"}]
    n2 = data["notes"]["sel02"]
    assert n2["alternatives"] == [{"id": "S3", "start": 40.0, "end": 50.0, "text": "原文3"}]


def test_alternatives_are_at_most_three_in_time_order(gui_server):
    more = [_seg(i, 200 - 10 * (i - 9), "合同") for i in range(10, 16)]  # S10..S15 倒序放，时间顺序应是 S15..S10
    _project(gui_server.root, segs=[_seg(1, 0, "合同"), _seg(4, 60, "退费"), *more])
    _, data = _get(gui_server)
    alts = data["notes"]["sel01"]["alternatives"]
    assert len(alts) == rp.ALTERNATIVES_MAX == 3
    assert [a["id"] for a in alts] == ["S15", "S14", "S13"]  # 最早的三条


def test_notes_for_manual_shots(gui_server):
    manual = [{"id": "sel01", "in": 0.0, "out": 10.0, "sub": "改过", "note": ""},     # 仍是 AI 那一镜
              {"id": "m1", "in": 21.0, "out": 29.0, "sub": "手加", "note": ""},       # 压在 S2 上
              {"id": "m2", "in": 200.0, "out": 210.0, "sub": "空镜", "note": ""}]     # 不压任何片段
    _project(gui_server.root, manual=manual)
    _, data = _get(gui_server)
    notes = data["notes"]
    assert notes["sel01"]["why"] == "含金额 · 讲合同"
    assert notes["m1"]["why"] == "含条款" and notes["m1"]["segment_id"] == "S2" and notes["m1"]["topic"] == "合同"
    assert notes["m2"] == {"why": "手动添加", "topic": None, "segment_id": None, "alternatives": []}


def test_same_id_but_different_time_is_not_the_ai_shot(gui_server):
    """AI 每次都从 sel01 编号：id 相同但时间不重叠，不能沿用旧说明。"""
    manual = [{"id": "sel01", "in": 200.0, "out": 210.0, "sub": "x", "note": ""}]
    _project(gui_server.root, manual=manual)
    _, data = _get(gui_server)
    assert data["notes"]["sel01"]["why"] == "手动添加"


# ---------------------------------------------------------------- 预览片 / 手动改动 / 向导
def test_preview_none_has_no_url(gui_server):
    _project(gui_server.root)
    _, data = _get(gui_server)
    assert data["preview"]["status"] == "none" and data["preview"]["url"] is None


def test_preview_fresh_has_cache_busting_url(gui_server):
    pdir = _project(gui_server.root)
    cfg = schema.read_json(pdir / "project.json")
    staging = outputs.staging_dir(pdir)
    staging.mkdir(parents=True)
    with media_io.atomic_output(staging / "preview.mp4") as tmp:
        tmp.write_bytes(b"x")
    outputs.write_stamp(staging, fingerprints.preview_inputs(pdir, cfg), 2, 20.0)
    _, data = _get(gui_server)
    p = data["preview"]
    assert p["status"] == "fresh" and p["url"] == f"/media/p1/current-preview?v={quote(p['at'])}"  # 时间里的 + 必须编码，否则被读成空格


def test_manual_changes_source_and_wizard_present(gui_server):
    _project(gui_server.root, manual=[AI_SHOTS[0]])
    _, data = _get(gui_server)
    assert data["manual"]["edited"] is True and data["manual"]["count"] == 1
    assert [s["key"] for s in data["wizard"]["steps"]][-2:] == ["result", "export"]


# ---------------------------------------------------------------- 错误与边界
def test_result_errors(gui_server):
    pdir = _project(gui_server.root)
    assert call(gui_server, "GET", "/api/result?project=nope")[0] == 404
    assert call(gui_server, "GET", "/api/result?project=..%2Fx")[0] == 400
    assert call(gui_server, "GET", "/api/result")[0] == 400
    (pdir / "work" / "overrides.json").write_text("{坏", encoding="utf-8")
    assert call(gui_server, "GET", "/api/result?project=p1")[0] == 409


def test_corrupt_shots_json_is_409_not_empty(gui_server):
    pdir = _project(gui_server.root)
    (pdir / "shots.json").write_text("{坏", encoding="utf-8")
    assert call(gui_server, "GET", "/api/result?project=p1")[0] == 409


def test_corrupt_project_json_is_409(gui_server):
    pdir = _project(gui_server.root)
    (pdir / "project.json").write_text("{坏", encoding="utf-8")
    assert call(gui_server, "GET", "/api/result?project=p1")[0] == 409


def test_not_analyzed_project_is_200_with_empty_lists(gui_server):
    make_project(gui_server.root, shots=AI_SHOTS)
    status, data = _get(gui_server)
    assert status == 200 and data["unused"] == [] and data["notes"] == {}
    assert data["topbar"]["shots"] == 2 and data["topbar"]["clip"]["count"] == 0


# ---------------------------------------------------------------- 恢复为 AI 选段
def _restore_ai(gs):
    status, raw, _ = call(gs, "POST", "/api/result/restore-ai", {"project": "p1"})
    return status, json.loads(raw)


def test_restore_ai_backs_up_and_removes_manual_table_and_baseline(gui_server):
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    schema.write_json(pdir / "work" / "manual_base.json", {"shots": AI_SHOTS, "at": "t"})
    status, data = _restore_ai(gui_server)
    assert status == 200 and data["ok"] is True and data["backup"]
    assert not (pdir / "shots.json").exists() and not (pdir / "work" / "manual_base.json").exists()
    assert len(list((pdir / "work" / "shots_backups").glob("*-restore-ai.json"))) == 1
    assert "steps" in data["wizard"]


def test_restore_ai_without_manual_table_is_a_noop_200(gui_server):
    _project(gui_server.root)
    status, data = _restore_ai(gui_server)
    assert status == 200 and data["ok"] is True and data["backup"] is None


def test_restore_ai_without_ai_selection_is_409_and_keeps_manual(gui_server):
    pdir = make_project(gui_server.root, shots=AI_SHOTS)
    before = (pdir / "shots.json").read_bytes()
    status, data = _restore_ai(gui_server)
    assert status == 409 and data["error"] == rp.NO_AI_SELECTION_MSG
    assert (pdir / "shots.json").read_bytes() == before


def test_restore_ai_409_while_a_job_runs(gui_server, monkeypatch):
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    monkeypatch.setattr(gui_server.module.jobs, "project_job", lambda n: {"id": "j", "task": "select"})
    status, data = _restore_ai(gui_server)
    assert status == 409 and "重新选段" in data["error"] and (pdir / "shots.json").exists()


def test_restore_ai_bad_project_and_corrupt(gui_server):
    assert call(gui_server, "POST", "/api/result/restore-ai", {"project": "nope"})[0] == 404
    assert call(gui_server, "POST", "/api/result/restore-ai", {"project": "../x"})[0] == 400
    pdir = _project(gui_server.root)
    (pdir / "project.json").write_text("{坏", encoding="utf-8")
    assert call(gui_server, "POST", "/api/result/restore-ai", {"project": "p1"})[0] == 409


# ---------------------------------------------------------------- 两版对比
V1 = [{"id": "a", "in": 10, "out": 20, "sub": "甲"}, {"id": "b", "in": 40, "out": 50, "sub": "乙"}]
V2 = [{"id": "a", "in": 10, "out": 20, "sub": "甲改"}, {"id": "c", "in": 70, "out": 80, "sub": "丙"}]


def _version(pdir, name, snapshot):
    vdir = pdir / "output" / name
    vdir.mkdir(parents=True)
    (vdir / "timeline.json").write_text(json.dumps(
        {"video": [{"timeline_in": 0, "in": 0, "out": 10}]}), encoding="utf-8")
    if snapshot is not None:
        (vdir / "shots_snapshot.json").write_text(json.dumps({"shots": snapshot}), encoding="utf-8")
    return vdir


def _compare(gs, a="v1", b="v2"):
    return _get(gs, f"/api/versions/compare?project=p1&a={a}&b={b}")


def test_compare_two_versions_with_snapshots(gui_server):
    pdir = make_project(gui_server.root)
    _version(pdir, "v1", V1)
    _version(pdir, "v2", V2)
    status, data = _compare(gui_server)
    assert status == 200
    assert [len(data["diff"][k]) for k in ("added", "removed", "sub_changed", "retimed")] == [1, 1, 1, 0]
    assert data["count"] == 3 and len(data["lines"]) == 3 and data["more"] == 0 and data["note"] is None
    assert data["a"] == {"name": "v1", "preview": False, "shots": 1, "duration": 10.0, "has_snapshot": True}
    assert data["b"]["name"] == "v2"


def test_compare_missing_snapshot_gives_null_diff_and_note(gui_server):
    pdir = make_project(gui_server.root)
    _version(pdir, "v1", V1)
    _version(pdir, "v2", None)
    status, data = _compare(gui_server)
    assert status == 200 and data["diff"] is None and data["note"] == rp.COMPARE_NO_SNAPSHOT
    assert data["b"]["has_snapshot"] is False and data["lines"] == []


def test_compare_corrupt_snapshot_is_treated_as_missing(gui_server):
    pdir = make_project(gui_server.root)
    _version(pdir, "v1", V1)
    v2 = _version(pdir, "v2", V2)
    (v2 / "shots_snapshot.json").write_text("{坏", encoding="utf-8")
    status, data = _compare(gui_server)
    assert status == 200 and data["diff"] is None and data["b"]["has_snapshot"] is False


@pytest.mark.parametrize("a,b,code", [("v1", "v1", 400), ("v1", "../x", 400), ("x", "v1", 400),
                                      ("v1", "v9", 404), ("v9", "v1", 404)])
def test_compare_validation(gui_server, a, b, code):
    pdir = make_project(gui_server.root)
    _version(pdir, "v1", V1)
    assert _compare(gui_server, a, b)[0] == code


def test_compare_does_not_find_staging_dir_as_a_version(gui_server):
    pdir = make_project(gui_server.root)
    _version(pdir, "v1", V1)
    staging = pdir / "output" / "preview"
    staging.mkdir()
    (staging / "timeline.json").write_text("{}", encoding="utf-8")
    assert _compare(gui_server, "v1", "preview")[0] == 400


# ---------------------------------------------------------------- 回到这一版
def _restore(gs, version="v1"):
    status, raw, _ = call(gs, "POST", "/api/versions/restore", {"project": "p1", "version": version})
    return status, json.loads(raw)


def _dirs(pdir):
    return sorted(p.name for p in (pdir / "output").iterdir())


def test_restore_version_writes_snapshot_as_manual_table_and_keeps_every_version(gui_server):
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    _version(pdir, "v1", V1)
    _version(pdir, "v2", V2)
    before = _dirs(pdir)
    status, data = _restore(gui_server)
    assert status == 200 and data["ok"] is True and data["count"] == 2 and data["dropped"] == []
    assert [s["id"] for s in schema.read_shots(pdir / "shots.json")] == ["a", "b"]
    assert len(list((pdir / "work" / "shots_backups").glob("*-restore-v1.json"))) == 1 and data["backup"]
    assert _dirs(pdir) == before


def test_restore_version_without_manual_table_writes_baseline_and_no_backup(gui_server):
    pdir = _project(gui_server.root)
    _version(pdir, "v1", V1)
    status, data = _restore(gui_server)
    assert status == 200 and data["backup"] is None
    base = json.loads((pdir / "work" / "manual_base.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in base["shots"]] == ["sel01", "sel02"]


def test_restore_version_drops_shots_overlapping_unusable_segments(gui_server):
    pdir = _project(gui_server.root)
    _version(pdir, "v1", [{"id": "a", "in": 100, "out": 110, "sub": "含 S6"}, {"id": "b", "in": 40, "out": 50, "sub": "乙"}])
    status, data = _restore(gui_server)
    assert status == 200 and data["dropped"] == ["a"] and data["count"] == 1
    assert [s["id"] for s in schema.read_shots(pdir / "shots.json")] == ["b"]


def test_restore_version_all_dropped_is_409_and_changes_nothing(gui_server):
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    _version(pdir, "v1", [{"id": "a", "in": 100, "out": 110, "sub": "含 S6"}])
    before = (pdir / "shots.json").read_bytes()
    status, data = _restore(gui_server)
    assert status == 409 and data["error"] == rp.RESTORE_EMPTY_MSG
    assert (pdir / "shots.json").read_bytes() == before
    assert not (pdir / "work" / "shots_backups").exists()


def test_restore_version_without_snapshot_is_409(gui_server):
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    _version(pdir, "v1", None)
    status, data = _restore(gui_server)
    assert status == 409 and data["error"] == rp.RESTORE_NO_SNAPSHOT


def test_restore_version_corrupt_snapshot_is_409(gui_server):
    pdir = _project(gui_server.root)
    v1 = _version(pdir, "v1", V1)
    (v1 / "shots_snapshot.json").write_text("{坏", encoding="utf-8")
    assert _restore(gui_server)[0] == 409


def test_restore_version_validation_and_busy(gui_server, monkeypatch):
    pdir = _project(gui_server.root)
    _version(pdir, "v1", V1)
    assert _restore(gui_server, "../x")[0] == 400
    assert _restore(gui_server, "v9")[0] == 404
    assert call(gui_server, "POST", "/api/versions/restore", {"project": "p1"})[0] == 400
    monkeypatch.setattr(gui_server.module.jobs, "project_job", lambda n: {"id": "j", "task": "preview"})
    status, data = _restore(gui_server)
    assert status == 409 and "生成预览片" in data["error"] and not (pdir / "shots.json").exists()


# ---------------------------------------------------------------- 当前预览片的媒体路由
def test_current_preview_media_is_served_and_404_when_missing(gui_server):
    pdir = _project(gui_server.root)
    assert call(gui_server, "GET", "/media/p1/current-preview")[0] == 404
    staging = outputs.staging_dir(pdir)
    staging.mkdir(parents=True)
    (staging / "preview.mp4").write_bytes(b"0123456789")
    status, raw, hdr = call(gui_server, "GET", "/media/p1/current-preview?v=abc")
    assert status == 200 and raw == b"0123456789"


def test_current_preview_rejects_traversal_and_extra_segments(gui_server):
    _project(gui_server.root)
    assert call(gui_server, "GET", "/media/..%2Fp1/current-preview")[0] == 400
    assert call(gui_server, "GET", "/media/p1%2Fcurrent-preview")[0] in (400, 404)
    assert call(gui_server, "GET", "/media/p1/current-preview/x")[0] == 404
    assert call(gui_server, "GET", "/media/p1/current-preview", token=False)[0] == 403


# ================================================================ 审查修复
def _seq_jobs(monkeypatch, gs, *answers):
    """project_job 依次返回 answers（用完后一直返回最后一个）：第一次是外层快速检查，第二次是锁内复查。"""
    it = iter(answers)
    last = [None]

    def fake(name):
        last[0] = next(it, last[0])
        return last[0]
    monkeypatch.setattr(gs.module.jobs, "project_job", fake)


# ---- HIGH-1：写之后才可能失败的东西，要么先算好，要么失败也不能把已成功的写说成失败
def test_restore_ai_oserror_on_write_is_500_chinese_and_manual_kept(gui_server, monkeypatch):
    from pipeline import shots_store
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    before = (pdir / "shots.json").read_bytes()

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(shots_store, "drop_manual", boom)
    status, data = _restore_ai(gui_server)
    assert status == 500 and "写入失败" in data["error"] and "/" not in data["error"]
    assert (pdir / "shots.json").read_bytes() == before


def test_restore_ai_project_json_unreadable_is_409_before_anything_is_deleted(gui_server, monkeypatch):
    from gui import result_routes
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])

    def corrupt(_pdir):
        raise schema.CorruptJSON("project.json 坏了")
    monkeypatch.setattr(result_routes, "_read_cfg", corrupt)
    status, _ = _restore_ai(gui_server)
    assert status == 409 and (pdir / "shots.json").exists()
    assert not (pdir / "work" / "shots_backups").exists()


def test_restore_ai_wizard_failure_after_write_is_still_200_ok(gui_server, monkeypatch):
    from gui import result_routes
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])

    def boom(*a, **k):
        raise RuntimeError("wizard 坏了")
    monkeypatch.setattr(result_routes.wizard, "derive", boom)
    status, data = _restore_ai(gui_server)
    assert status == 200 and data["ok"] is True and data["wizard"] is None and data["warning"]
    assert not (pdir / "shots.json").exists()


def test_restore_version_oserror_on_write_is_500(gui_server, monkeypatch):
    from pipeline import shots_store
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    _version(pdir, "v1", V1)
    before = (pdir / "shots.json").read_bytes()

    def boom(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(shots_store, "write_manual", boom)
    status, data = _restore(gui_server)
    assert status == 500 and "写入失败" in data["error"]
    assert (pdir / "shots.json").read_bytes() == before


def test_restore_version_wizard_failure_after_write_is_200_with_warning(gui_server, monkeypatch):
    from gui import result_routes
    pdir = _project(gui_server.root)
    _version(pdir, "v1", V1)
    monkeypatch.setattr(result_routes.wizard, "derive", lambda *a, **k: 1 / 0)
    status, data = _restore(gui_server)
    assert status == 200 and data["wizard"] is None and data["warning"] and data["count"] == 2
    assert (pdir / "shots.json").exists()


def test_restore_version_project_json_unreadable_is_409_and_writes_nothing(gui_server, monkeypatch):
    from gui import result_routes
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    _version(pdir, "v1", V1)
    before = (pdir / "shots.json").read_bytes()
    monkeypatch.setattr(result_routes, "_read_cfg", lambda p: (_ for _ in ()).throw(schema.CorruptJSON("坏")))
    assert _restore(gui_server)[0] == 409
    assert (pdir / "shots.json").read_bytes() == before and not (pdir / "work" / "shots_backups").exists()


def test_restore_version_invalid_shots_is_400_not_500(gui_server, monkeypatch):
    from gui import result_routes
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    _version(pdir, "v1", V1)
    before = (pdir / "shots.json").read_bytes()
    monkeypatch.setattr(result_routes.exclusions, "drop_overlapping", lambda s, m: ([{"id": "x"}], []))
    status, _ = _restore(gui_server)
    assert status == 400 and (pdir / "shots.json").read_bytes() == before


@pytest.mark.parametrize("exc", [KeyError("start"), TypeError("x")])
def test_restore_version_malformed_analysis_is_409(gui_server, monkeypatch, exc):
    from gui import result_routes
    pdir = _project(gui_server.root)
    _version(pdir, "v1", V1)

    def boom(_w):
        raise exc
    monkeypatch.setattr(result_routes.exclusions, "spans", boom)
    assert _restore(gui_server)[0] == 409 and not (pdir / "shots.json").exists()


# ---- MEDIUM-4：锁内复查任务
def test_restore_ai_rechecks_running_job_inside_the_lock(gui_server, monkeypatch):
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    _seq_jobs(monkeypatch, gui_server, None, {"id": "j", "task": "select"})  # 外层放行，拿到锁时任务已起来
    status, data = _restore_ai(gui_server)
    assert status == 409 and "重新选段" in data["error"] and (pdir / "shots.json").exists()


def test_restore_version_rechecks_running_job_inside_the_lock(gui_server, monkeypatch):
    pdir = _project(gui_server.root, manual=[AI_SHOTS[0]])
    _version(pdir, "v1", V1)
    before = (pdir / "shots.json").read_bytes()
    _seq_jobs(monkeypatch, gui_server, None, {"id": "j", "task": "select"})
    status, _ = _restore(gui_server)
    assert status == 409 and (pdir / "shots.json").read_bytes() == before
    assert not (pdir / "work" / "shots_backups").exists()


# ---- MEDIUM-6
def test_compare_and_restore_treat_unreadable_snapshot_as_missing(gui_server, monkeypatch):
    from gui import result_payload
    pdir = _project(gui_server.root)
    _version(pdir, "v1", V1)
    _version(pdir, "v2", V2)

    def boom(path):
        raise OSError(5, "io")
    monkeypatch.setattr(result_payload.schema, "read_shots", boom)
    assert _compare(gui_server)[1]["diff"] is None
    assert _restore(gui_server)[0] == 409


# ---- HIGH-3：宽松读到的数据不能把接口打成 500
@pytest.mark.parametrize("bad", [{"id": "S9", "start": 1.0, "end": 2.0},     # 缺 level
                                 {"start": 1.0, "end": 2.0, "level": 3}])     # 缺 id
def test_malformed_analysis_segment_is_409_not_500(gui_server, bad):
    _project(gui_server.root, segs=[*SEGS, bad])
    assert call(gui_server, "GET", "/api/result?project=p1")[0] == 409


def test_garbage_in_selection_json_never_breaks_the_page(gui_server):
    pdir = _project(gui_server.root)
    junk = {"shots": ["x", {"id": "sel01"}, {"id": "sel02", "start": "a", "end": None}, None],
            "unused": [3, {"segment_id": "S2"}, None]}
    (pdir / "work" / "selection.json").write_text(json.dumps(junk), encoding="utf-8")
    status, data = _get(gui_server)
    assert status == 200 and "S2" in _ids(data)


# ---- LOW：③ 与 ⑤ 的「已进片」同一条规则
def test_short_sentence_inside_a_shot_is_used_in_both_browse_and_result(gui_server):
    from gui import payloads
    segs = [{**_seg(1, 0, "合同"), "end": 0.8}, _seg(2, 20, "合同")]
    pdir = _project(gui_server.root, segs=segs)
    browse = {s["id"]: s for s in payloads.browse(pdir, "p1")["segments"]}
    assert browse["S1"]["inCut"] is True and browse["S2"]["inCut"] is False
    assert "S1" not in _ids(_get(gui_server)[1]) and "S2" in _ids(_get(gui_server)[1])


def test_in_cut_rule_is_shared():
    from gui import payloads, result_payload
    assert result_payload.IN_CUT_OVERLAP_S is payloads.IN_CUT_OVERLAP_S
    shot = [{"in": 0.0, "out": 10.0}]
    assert payloads.in_cut({"start": 8.5, "end": 12.0}, shot) is True         # 重叠 1.0 秒以上
    assert payloads.in_cut({"start": 9.5, "end": 12.0}, shot) is False        # 只重叠 0.5 秒且没整段落在里面
    assert payloads.in_cut({"start": 2.0, "end": 2.5}, shot) is True          # 短句整段落在里面

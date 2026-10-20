# -*- coding: utf-8 -*-
"""aicut preview / build 的「暂存 → 晋升」（M14 T4）与 select --manual（T5）。

打桩方式同 tests/test_aicut_build.py：只替换耗时的切片 / 渲染 / 装草稿，其余逻辑真实运行。
"""
import json
from argparse import Namespace
from pathlib import Path

import pytest

import aicut
from pipeline import fingerprints, media_io, outputs, schema

SHOTS = [{"id": "sel01", "in": 0.0, "out": 5.0, "sub": "甲"},
         {"id": "sel02", "in": 10.0, "out": 15.0, "sub": "乙"}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """项目 p + 打桩：切片、真实时长、时间线、渲染（写一个假 mp4）、装草稿（记录名字）。"""
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = tmp_path / "p"
    schema.save(pdir / "project.json", {**schema.default_project("p", str(tmp_path / "src.mov")), "title": "片名"})
    (pdir / "work").mkdir(exist_ok=True)
    schema.write_json(pdir / "work" / "shots-selected.json", {"shots": SHOTS})
    calls = {"clips": 0, "render": 0, "draft": [], "pkg": []}

    def clips(*a):
        calls["clips"] += 1
        return pdir / "work/clips"

    def render(module, argv):
        calls["render"] += 1
        Path(argv[-1]).write_bytes(b"fake-mp4-%d" % calls["render"])

    monkeypatch.setattr(aicut.select, "missing_must_keep", lambda *a: [])
    monkeypatch.setattr(aicut, "ensure_clips", clips)
    monkeypatch.setattr(aicut, "actual_durations", lambda c, shots: {s["id"]: s["out"] - s["in"] for s in shots})
    monkeypatch.setattr(aicut, "compose_timeline",
                        lambda c, p, shots, cp, d: {"video": [{"id": s["id"], "in": s["in"]} for s in shots], "text": []})
    monkeypatch.setattr(aicut, "_run_pipeline", render)
    monkeypatch.setattr(aicut, "install_draft", lambda vdir, name: calls["draft"].append((vdir.name, name)))

    def package(timeline, name, out):
        calls["pkg"].append((Path(timeline).parent.name, name))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"zip")
        return {"zip": str(out), "size": 3, "warnings": []}
    monkeypatch.setattr(aicut.outputs.export_draft, "build_windows_package", package)
    monkeypatch.setattr(aicut.clips, "restore_missing", lambda *a: None)
    return Namespace(pdir=pdir, calls=calls)


def _write_manual(pdir, shots):
    schema.write_json(pdir / "shots.json", {"shots": shots})


def preview():
    return aicut.cmd_preview(Namespace(name="p"))


def build(**kw):
    return aicut.cmd_build(Namespace(name="p", version=kw.pop("version", None), no_draft=kw.pop("no_draft", False), **kw))


def _versions(pdir):
    return sorted(p.name for p in (pdir / "output").glob("v*"))


# ---------------------------------------------------------------- aicut preview
def test_preview_writes_staging_only_and_no_version(env):
    cfg = aicut.cfg(env.pdir)
    expected = fingerprints.preview_inputs(env.pdir, cfg)
    preview()
    staging = outputs.staging_dir(env.pdir)
    for name in ("timeline.json", "shots_snapshot.json", "preview.mp4", ".timeline.sha", "preview.json"):
        assert (staging / name).is_file(), name
    assert outputs.read_stamp(staging)["inputs"] == expected
    assert media_io.is_complete(staging / "preview.mp4")
    assert _versions(env.pdir) == []
    assert env.calls["draft"] == []


def test_preview_twice_skips_render(env, capsys):
    preview()
    capsys.readouterr()
    preview()
    assert env.calls["render"] == 1
    assert "预览片无变化，跳过渲染" in capsys.readouterr().out


def test_preview_missing_must_keep_dies_without_stamp(env, monkeypatch, capsys):
    monkeypatch.setattr(aicut.select, "missing_must_keep", lambda *a: [{"id": "S9", "start": 1, "end": 2, "text": "x"}])
    with pytest.raises(SystemExit):
        preview()
    assert "[x]" in capsys.readouterr().out
    assert outputs.read_stamp(outputs.staging_dir(env.pdir)) is None


def test_preview_all_dropped_dies_without_stamp(env, monkeypatch, capsys):
    monkeypatch.setattr(aicut.exclusions, "filter_shots", lambda w, s: ([], ["sel01", "sel02"]))
    with pytest.raises(SystemExit):
        preview()
    assert outputs.read_stamp(outputs.staging_dir(env.pdir)) is None


def test_preview_render_failure_keeps_old_stamp(env, monkeypatch):
    preview()
    old = outputs.read_stamp(outputs.staging_dir(env.pdir))
    _write_manual(env.pdir, [{**SHOTS[0], "sub": "改了"}])

    def boom(module, argv):
        raise media_io.MediaError("渲染炸了")
    monkeypatch.setattr(aicut, "_run_pipeline", boom)
    with pytest.raises(SystemExit):
        preview()
    assert outputs.read_stamp(outputs.staging_dir(env.pdir)) == old


def test_preview_stamp_uses_inputs_taken_at_start(env, monkeypatch):
    """渲染期间分镜表又被改了：戳里记的是开始时的输入，所以会被判为过期而不是误判为新鲜。"""
    start = fingerprints.preview_inputs(env.pdir, aicut.cfg(env.pdir))

    def render_and_edit(module, argv):
        Path(argv[-1]).write_bytes(b"x")
        _write_manual(env.pdir, [{**SHOTS[0], "sub": "渲染期间改的"}])
    monkeypatch.setattr(aicut, "_run_pipeline", render_and_edit)
    preview()
    assert outputs.read_stamp(outputs.staging_dir(env.pdir))["inputs"] == start
    assert outputs.preview_state(env.pdir, aicut.cfg(env.pdir))["status"] == "outdated"


# ---------------------------------------------------------------- aicut build 晋升
def test_build_stages_promotes_and_installs_draft(env):
    build()
    assert _versions(env.pdir) == ["v1"]
    vdir = env.pdir / "output" / "v1"
    assert (vdir / "preview.mp4").stat().st_ino == (outputs.staging_dir(env.pdir) / "preview.mp4").stat().st_ino
    assert env.calls["draft"] == [("v1", "片名_v1")]
    assert outputs.read_exports(vdir)["mac"]["draft"] == "片名_v1"
    assert outputs.read_exports(vdir)["windows"] is None


def test_build_no_draft_records_no_mac_export(env):
    build(no_draft=True)
    assert env.calls["draft"] == []
    assert outputs.read_exports(env.pdir / "output" / "v1")["mac"] is None


def test_build_second_time_makes_new_version(env):
    build(no_draft=True)
    build(no_draft=True)
    assert _versions(env.pdir) == ["v1", "v2"]


# ---------------------------------------------------------------- --require-preview
def test_require_preview_stale_dies_and_creates_nothing(env, capsys):
    preview()
    _write_manual(env.pdir, [{**SHOTS[0], "sub": "改了"}])
    env.calls["clips"] = env.calls["render"] = 0
    with pytest.raises(SystemExit):
        build(require_preview=True)
    assert outputs.PREVIEW_STALE in capsys.readouterr().out
    assert _versions(env.pdir) == []
    assert env.calls["clips"] == 0 and env.calls["render"] == 0


def test_require_preview_without_any_preview_dies(env, capsys):
    with pytest.raises(SystemExit):
        build(require_preview=True)
    assert outputs.PREVIEW_NONE in capsys.readouterr().out
    assert _versions(env.pdir) == []


def test_require_preview_fresh_promotes_without_rendering(env):
    preview()
    env.calls["clips"] = env.calls["render"] = 0
    build(require_preview=True)
    assert _versions(env.pdir) == ["v1"]
    assert env.calls["clips"] == 0 and env.calls["render"] == 0
    assert env.calls["draft"] == [("v1", "片名_v1")]


def test_require_preview_still_blocks_when_must_keep_added_after_preview(env, monkeypatch, capsys):
    """必留标记不在预览指纹里：晋升前必须再核对一次，缺必留段不能出片（GL-25）。"""
    preview()
    monkeypatch.setattr(aicut.select, "missing_must_keep", lambda *a: [{"id": "S9", "start": 1, "end": 2, "text": "x"}])
    with pytest.raises(SystemExit):
        build(require_preview=True)
    assert _versions(env.pdir) == []


# ---------------------------------------------------------------- --windows
def test_build_windows_packages_promoted_version(env):
    preview()
    build(require_preview=True, windows=True, no_draft=True)
    vdir = env.pdir / "output" / "v1"
    zip_path = outputs.windows_zip(env.pdir, "v1", "片名")
    assert zip_path.is_file() and env.calls["pkg"] == [("v1", zip_path.stem)]
    ex = outputs.read_exports(vdir)
    assert ex["windows"]["zip"] == zip_path.name and ex["mac"] is None
    assert env.calls["draft"] == []


def test_build_windows_failure_dies_keeps_version_and_no_windows_mark(env, monkeypatch, capsys):
    preview()

    def fail(t, n, out):
        raise RuntimeError("打包失败了")
    monkeypatch.setattr(aicut.outputs.export_draft, "build_windows_package", fail)
    with pytest.raises(SystemExit):
        build(require_preview=True, windows=True, no_draft=True)
    assert "打包失败了" in capsys.readouterr().out
    vdir = env.pdir / "output" / "v1"
    assert (vdir / "timeline.json").is_file()
    assert outputs.read_exports(vdir)["windows"] is None


def test_reuse_version_adds_windows_to_same_version(env):
    """⚑Q1：同一张表先 Mac 后 Windows，算同一个版本。"""
    preview()
    build(require_preview=True)
    build(require_preview=True, version="v1", windows=True, no_draft=True)
    assert _versions(env.pdir) == ["v1"]
    ex = outputs.read_exports(env.pdir / "output" / "v1")
    assert ex["mac"]["draft"] == "片名_v1" and ex["windows"]["zip"].endswith("_v1_Windows.zip")
    assert len(env.calls["draft"]) == 1


def test_reuse_version_with_mac_already_exported_skips_draft(env, capsys):
    preview()
    build(require_preview=True)
    capsys.readouterr()
    build(require_preview=True, version="v1")
    assert len(env.calls["draft"]) == 1
    assert "已经在 Mac 剪映里" in capsys.readouterr().out


# ---------------------------------------------------------------- aicut export 默认时间线
def test_export_default_timeline_ignores_staging(env, monkeypatch):
    for name in ("v1", "v2", "preview"):
        d = env.pdir / "output" / name
        d.mkdir(parents=True)
        (d / "timeline.json").write_text("{}", encoding="utf-8")
    (env.pdir / "output" / "preview" / "timeline.json").touch()  # 暂存最新
    monkeypatch.setattr(aicut.exclusions, "timeline_hits", lambda w, d: 0)
    seen = []
    monkeypatch.setattr(aicut.outputs.export_draft, "build_windows_package",
                        lambda t, n, out: seen.append(Path(t).parent.name) or {"zip": str(out), "size": 1, "warnings": []})
    aicut.cmd_export(Namespace(name="p", timeline=None, package_name=None, out=str(env.pdir / "out")))
    assert seen == ["v2"]


# ================================================================ T5 · select --manual
def _stub_select(monkeypatch, *, fail=False):
    def run(*a, **k):
        if fail:
            raise aicut.select.SelectionError("必留段未进片：S001")
        return {"missing_must_topics": [], "stats": {"shots": 1}, "total": 1.0, "target": 175.0,
                "over_target": False, "warnings": []}
    monkeypatch.setattr(aicut.select, "run", run)


def _select_env(env):
    schema.write_json(env.pdir / "work" / "segments_scored.json", {"segments": []})
    _write_manual(env.pdir, [SHOTS[0]])
    from pipeline import shots_store
    with shots_store.locked(env.pdir):  # 第一次写出时建基线
        (env.pdir / "shots.json").unlink()
        shots_store.write_manual(env.pdir, schema.clean_shots([SHOTS[0]]), {})


def _select(**kw):
    return aicut.cmd_select(Namespace(name="p", target=None, **kw))


def test_select_manual_replace_backs_up_and_deletes_manual_table(env, monkeypatch, capsys):
    from pipeline import shots_store
    _stub_select(monkeypatch)
    _select_env(env)
    original = (env.pdir / "shots.json").read_bytes()
    _select(manual="replace")
    assert not (env.pdir / "shots.json").exists() and not (env.pdir / shots_store.BASE_FILE).exists()
    backups = list((env.pdir / shots_store.BACKUP_DIR).glob("*-replace.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert "备份在 work/shots_backups" in capsys.readouterr().out


def test_select_manual_replace_failure_keeps_manual_table(env, monkeypatch):
    _stub_select(monkeypatch, fail=True)
    _select_env(env)
    before = (env.pdir / "shots.json").read_bytes()
    with pytest.raises(SystemExit):
        _select(manual="replace")
    assert (env.pdir / "shots.json").read_bytes() == before


def test_select_manual_replace_without_manual_table_is_noop(env, monkeypatch):
    from pipeline import shots_store
    _stub_select(monkeypatch)
    schema.write_json(env.pdir / "work" / "segments_scored.json", {"segments": []})
    _select(manual="replace")
    assert not (env.pdir / shots_store.BACKUP_DIR).exists()


@pytest.mark.parametrize("args", [{}, {"manual": "keep"}])
def test_select_manual_keep_or_default_leaves_manual_table(env, monkeypatch, args):
    _stub_select(monkeypatch)
    _select_env(env)
    before = (env.pdir / "shots.json").read_bytes()
    _select(**args)
    assert (env.pdir / "shots.json").read_bytes() == before


def test_select_manual_invalid_value_rejected_by_argparse(capsys):
    with pytest.raises(SystemExit):
        aicut.main(["select", "p", "--manual=nuke"])
    assert "invalid choice" in capsys.readouterr().err


def test_select_replace_waits_for_shots_lock_so_concurrent_save_is_not_lost(env, monkeypatch):
    """不丢编辑：GUI 保存持着锁时，replace 必须等；等到之后删表前先备份，保存的内容留在备份里。"""
    import threading
    from pipeline import shots_store
    _stub_select(monkeypatch)
    _select_env(env)
    done = threading.Event()
    with shots_store.locked(env.pdir):
        t = threading.Thread(target=lambda: (_select(manual="replace"), done.set()))
        t.start()
        assert not done.wait(0.4)                       # 被锁挡住
        shots_store.write_manual(env.pdir, schema.clean_shots([{**SHOTS[0], "sub": "刚保存的编辑"}]), {})
    assert done.wait(5)
    t.join(5)
    saved = [p.read_text(encoding="utf-8") for p in (env.pdir / shots_store.BACKUP_DIR).glob("*-replace.json")]
    assert len(saved) == 1 and "刚保存的编辑" in saved[0]


# ================================================================ T5 · jobs.job_extra
@pytest.fixture
def jobs_mod():
    from gui import jobs
    return jobs


def test_job_commands_and_labels_include_preview(jobs_mod):
    assert jobs_mod.JOB_COMMANDS["preview"] == ["preview"]
    assert jobs_mod.TASK_LABELS["preview"] == "生成预览片"


def test_job_extra_select_manual(env, jobs_mod):
    ex = lambda body: jobs_mod.job_extra(env.pdir, "select", body, "片名")  # noqa: E731
    assert ex({"manual": "replace"}) == ["--manual=replace"]
    assert ex({"manual": "keep"}) == ["--manual=keep"]
    assert ex({"target": 120, "manual": "replace"}) == ["--target", "120", "--manual=replace"]
    assert ex({}) == []
    with pytest.raises(ValueError, match="manual 只能是 replace 或 keep"):
        ex({"manual": "nuke"})
    with pytest.raises(ValueError):
        ex({"manual": ["replace"]})


def test_job_extra_preview_has_no_args(env, jobs_mod):
    assert jobs_mod.job_extra(env.pdir, "preview", {"anything": 1}, "片名") == []


def _extra(jobs_mod, env, body):
    return jobs_mod.job_extra(env.pdir, "build", body, "片名")


def test_job_extra_build_requires_a_target(env, jobs_mod):
    """M14c：旧的暂存界面（无 target、--no-draft 勾选）已删除，GUI 的导出必须说清导出到哪里。"""
    for body in ({}, {"version": "v2", "no_draft": True}, {"target": None}):
        with pytest.raises(ValueError, match="缺少导出目标：mac 或 windows"):
            _extra(jobs_mod, env, body)


def test_job_extra_build_target_requires_fresh_preview(env, jobs_mod):
    with pytest.raises(ValueError, match="还没有当前分镜表的预览片"):
        _extra(jobs_mod, env, {"target": "mac"})
    preview()
    _write_manual(env.pdir, [{**SHOTS[0], "sub": "改了"}])
    with pytest.raises(ValueError) as exc:
        _extra(jobs_mod, env, {"target": "mac"})
    assert str(exc.value) == outputs.PREVIEW_STALE


def test_job_extra_build_targets_new_version_when_none_matches(env, jobs_mod):
    preview()
    assert _extra(jobs_mod, env, {"target": "mac"}) == ["--require-preview"]
    assert _extra(jobs_mod, env, {"target": "windows"}) == ["--require-preview", "--windows", "--no-draft"]


def test_job_extra_build_reuses_matching_version(env, jobs_mod):
    preview()
    build(require_preview=True, no_draft=True)             # v1 = 当前分镜表，只做过打包前的晋升
    assert _extra(jobs_mod, env, {"target": "mac"}) == ["--require-preview", "--version", "v1"]
    assert _extra(jobs_mod, env, {"target": "windows"}) == \
        ["--require-preview", "--version", "v1", "--windows", "--no-draft"]


def test_job_extra_build_mac_already_in_jianying_is_rejected(env, jobs_mod):
    preview()
    build(require_preview=True)                            # v1 已装进剪映
    with pytest.raises(ValueError, match="已经在 Mac 剪映里：片名_v1"):
        _extra(jobs_mod, env, {"target": "mac"})
    assert _extra(jobs_mod, env, {"target": "windows"})[:3] == ["--require-preview", "--version", "v1"]


def test_job_extra_build_bad_target(env, jobs_mod):
    preview()
    with pytest.raises(ValueError):
        _extra(jobs_mod, env, {"target": "linux"})


# ================================================================ T5 · settings.check_ready
def test_check_ready_build_mac_blocks_when_jianying_running(env, monkeypatch):
    from gui import settings
    monkeypatch.setattr(settings.to_jianying, "jianying_running", lambda: True)
    with pytest.raises(settings.PrepareBlocked) as exc:
        settings.check_ready(env.pdir, "build", {"target": "mac"})
    assert exc.value.need == "close_jianying" and "剪映正在运行" in str(exc.value)


def test_check_ready_build_windows_or_other_tasks_do_not_check_jianying(env, monkeypatch):
    from gui import settings
    monkeypatch.setattr(settings.to_jianying, "jianying_running", lambda: pytest.fail("不该检查"))
    settings.check_ready(env.pdir, "build", {"target": "windows"})
    settings.check_ready(env.pdir, "build", {})
    settings.check_ready(env.pdir, "select", {"target": "mac"})
    settings.check_ready(env.pdir, "preview")


def test_check_ready_build_mac_passes_when_jianying_closed(env, monkeypatch):
    from gui import settings
    monkeypatch.setattr(settings.to_jianying, "jianying_running", lambda: False)
    settings.check_ready(env.pdir, "build", {"target": "mac"})


# ================================================================ 审查修复回归
def _snapshot(vdir):
    return {p.name: p.read_bytes() for p in vdir.iterdir()}


def test_new_preview_never_changes_an_already_promoted_version(env):
    """HIGH-1：晋升后表又改了、重新生成预览片（不同哈希）→ v1 里每个文件逐字节不变。"""
    preview()
    build(require_preview=True, no_draft=True)
    vdir = env.pdir / "output" / "v1"
    before = _snapshot(vdir)
    _write_manual(env.pdir, [{**SHOTS[0], "sub": "改了"}])
    preview()
    assert env.calls["render"] == 2
    assert _snapshot(vdir) == before
    assert media_io.is_complete(vdir / "preview.mp4")


def test_overwrite_version_with_new_content_warns_and_refuses_mac_install(env, capsys):
    """HIGH-2：--version vN 用不同内容覆盖已装进剪映的版本：重置导出记录、警告旧草稿、拒绝再装同名草稿。"""
    preview()
    build(require_preview=True)
    zip_path = outputs.windows_zip(env.pdir, "v1", "片名")
    zip_path.write_bytes(b"old-zip")
    _write_manual(env.pdir, [{**SHOTS[0], "sub": "改了"}])
    preview()
    capsys.readouterr()
    with pytest.raises(SystemExit):
        build(require_preview=True, version="v1")
    out = capsys.readouterr().out
    assert "剪映里的「片名_v1」是旧内容" in out and "生成新版本" in out
    assert len(env.calls["draft"]) == 1                          # 没有再装
    assert outputs.read_exports(env.pdir / "output" / "v1") == {"mac": None, "windows": None}
    assert not zip_path.exists()


def test_overwrite_version_without_draft_still_warns_but_succeeds(env, capsys):
    preview()
    build(require_preview=True)
    _write_manual(env.pdir, [{**SHOTS[0], "sub": "改了"}])
    preview()
    capsys.readouterr()
    build(require_preview=True, version="v1", no_draft=True)
    assert "是旧内容" in capsys.readouterr().out
    assert (env.pdir / "output" / "v1" / "preview.mp4").is_file()


def test_failed_promotion_leaves_no_version(env, monkeypatch, capsys):
    preview()
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(outputs, "_link_or_copy", boom)
    with pytest.raises(SystemExit):
        build(require_preview=True)
    assert _versions(env.pdir) == []
    assert "Traceback" not in capsys.readouterr().out


def _recording_section(monkeypatch, events):
    import contextlib
    from pipeline import project_lock

    @contextlib.contextmanager
    def section(pdir, **kw):
        events.append("lock")
        yield
        events.append("unlock")
    monkeypatch.setattr(project_lock, "build_section", section)


def test_require_preview_check_and_promotion_share_one_lock_section(env, monkeypatch):
    """MEDIUM-2：新鲜度检查与晋升在同一个 build_section 里，中间不会被另一次预览插进来。"""
    preview()
    events = []
    _recording_section(monkeypatch, events)
    real_state, real_promote = outputs.preview_state, outputs.promote
    monkeypatch.setattr(outputs, "preview_state", lambda *a: events.append("check") or real_state(*a))
    monkeypatch.setattr(outputs, "promote", lambda *a, **k: events.append("promote") or real_promote(*a, **k))
    build(require_preview=True, no_draft=True)
    assert events == ["lock", "check", "promote", "unlock"]


def test_preview_render_happens_inside_the_build_lock(env, monkeypatch):
    events = []
    _recording_section(monkeypatch, events)
    real = aicut._run_pipeline
    monkeypatch.setattr(aicut, "_run_pipeline", lambda m, argv: events.append("render") or real(m, argv))
    preview()
    assert events == ["lock", "render", "unlock"]


def test_non_require_build_stages_and_promotes_in_one_lock_section(env, monkeypatch):
    events = []
    _recording_section(monkeypatch, events)
    real_promote = outputs.promote
    monkeypatch.setattr(outputs, "promote", lambda *a, **k: events.append("promote") or real_promote(*a, **k))
    build(no_draft=True)
    assert events == ["lock", "promote", "unlock"]


def test_promote_is_verified_against_the_preview_this_build_made(env, monkeypatch):
    """MEDIUM-2：晋升时再核对暂存戳；暂存被别人换掉了就停，不晋升别人的预览片。"""
    seen = {}
    real = outputs.promote
    monkeypatch.setattr(outputs, "promote", lambda s, v, **k: seen.update(k) or real(s, v, **k))
    build(no_draft=True)
    assert seen["expect_inputs"] == outputs.read_stamp(outputs.staging_dir(env.pdir))["inputs"]


def test_mark_export_failure_after_draft_install_dies_with_clear_message(env, monkeypatch, capsys):
    """MEDIUM-3:草稿已装进剪映,记录失败:中文说明,不是 traceback。"""
    preview()
    real = outputs.mark_export

    def flaky(vdir, kind, **info):
        if kind == "mac":
            raise OSError("read-only fs")
        return real(vdir, kind, **info)
    monkeypatch.setattr(outputs, "mark_export", flaky)
    with pytest.raises(SystemExit):
        build(require_preview=True)
    out = capsys.readouterr().out
    assert "草稿已经装进剪映" in out and "片名_v1" in out and "Traceback" not in out
    assert env.calls["draft"] == [("v1", "片名_v1")]


def test_preview_dies_if_table_changes_while_reading_it(env, monkeypatch, capsys):
    """MEDIUM-8：读分镜表前后指纹不一致（有人同时在改）→ 不渲染、不写戳。"""
    def edit_while_checking(workdir, shots):
        _write_manual(env.pdir, [{**SHOTS[0], "sub": "读的时候被改了"}])
        return []
    monkeypatch.setattr(aicut.select, "missing_must_keep", edit_while_checking)
    with pytest.raises(SystemExit):
        preview()
    assert "分镜表在读取时被修改" in capsys.readouterr().out
    assert env.calls["render"] == 0 and outputs.read_stamp(outputs.staging_dir(env.pdir)) is None


def test_cmd_export_and_versions_ignore_dot_dirs_and_incomplete_dirs(env, monkeypatch):
    from gui import views
    for name, tl in (("v1", True), ("v2", False), (".v3.tmp", True)):
        d = env.pdir / "output" / name
        d.mkdir(parents=True)
        if tl:
            (d / "timeline.json").write_text("{}", encoding="utf-8")
    assert aicut.next_version(env.pdir) == "v3"
    assert [v["name"] for v in views._versions(env.pdir, aicut.cfg(env.pdir), "p")] == ["v1"]
    monkeypatch.setattr(aicut.exclusions, "timeline_hits", lambda w, d: 0)
    seen = []
    monkeypatch.setattr(aicut.outputs.export_draft, "build_windows_package",
                        lambda t, n, out: seen.append(Path(t).parent.name) or {"zip": str(out), "size": 1, "warnings": []})
    aicut.cmd_export(Namespace(name="p", timeline=None, package_name=None, out=str(env.pdir / "out")))
    assert seen == ["v1"]


# ---- 覆盖(replace)的失败 / 忙
def test_select_replace_backup_failure_dies_with_reason_and_keeps_table(env, monkeypatch, capsys):
    from pipeline import shots_store
    _stub_select(monkeypatch)
    _select_env(env)
    before = (env.pdir / "shots.json").read_bytes()

    def boom(*a, **k):
        raise OSError("No space left")
    monkeypatch.setattr(shots_store.shutil, "copyfile", boom)
    with pytest.raises(SystemExit):
        _select(manual="replace")
    out = capsys.readouterr().out
    assert "备份失败" in out and "No space left" in out and "Traceback" not in out
    assert (env.pdir / "shots.json").read_bytes() == before


def test_select_replace_busy_prints_clear_message_and_keeps_table(env, monkeypatch, capsys):
    from pipeline import shots_store
    from test_shots_store import _hold_flock_in_subprocess, _release
    _stub_select(monkeypatch)
    _select_env(env)
    monkeypatch.setattr(shots_store, "BUSY_TIMEOUT_S", 0.3)
    before = (env.pdir / "shots.json").read_bytes()
    holder = _hold_flock_in_subprocess(env.pdir)
    try:
        with pytest.raises(SystemExit):
            _select(manual="replace")
    finally:
        _release(holder)
    assert "分镜表正忙" in capsys.readouterr().out
    assert (env.pdir / "shots.json").read_bytes() == before


def test_replace_manual_waits_for_another_process_holding_the_flock(env):
    """真正的跨进程:子进程持 flock,replace_manual 必须等到它放开才删表。"""
    import threading
    from test_shots_store import _hold_flock_in_subprocess, _release
    _select_env(env)
    holder = _hold_flock_in_subprocess(env.pdir)
    done = threading.Event()
    t = threading.Thread(target=lambda: (outputs.replace_manual(env.pdir), done.set()))
    t.start()
    try:
        assert not done.wait(0.5)
        assert (env.pdir / "shots.json").exists()
    finally:
        _release(holder)
    assert done.wait(5)
    t.join(5)
    assert not (env.pdir / "shots.json").exists()

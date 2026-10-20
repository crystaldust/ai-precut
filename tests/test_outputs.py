# -*- coding: utf-8 -*-
"""预览暂存与版本晋升（M14 T3）：output/preview 不是版本；晋升用硬链接，不重渲染。"""
import json
import os
from pathlib import Path

import pytest

from pipeline import fingerprints, media_io, outputs, schema

CFG = {"preset": "p", "material": "/nonexistent/a.mp4"}
SHOTS = [{"id": "s1", "in": 0, "out": 2, "sub": "甲"}]


def _project(tmp_path):
    pdir = tmp_path / "proj"
    (pdir / "work").mkdir(parents=True)
    (pdir / "work" / "shots-selected.json").write_text(json.dumps({"shots": SHOTS}), encoding="utf-8")
    return pdir


def _stage(pdir, *, inputs=None, content=b"mp4-bytes"):
    """造一份完整的暂存预览片（与 aicut preview 的产物同构）。"""
    d = outputs.staging_dir(pdir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "timeline.json").write_text("{}", encoding="utf-8")
    (d / "shots_snapshot.json").write_text(json.dumps({"shots": SHOTS}), encoding="utf-8")
    (d / ".timeline.sha").write_text("abc", encoding="utf-8")
    with media_io.atomic_output(d / "preview.mp4") as tmp:
        tmp.write_bytes(content)
    outputs.write_stamp(d, inputs if inputs is not None else fingerprints.preview_inputs(pdir, CFG), 1, 2.0)
    return d


# ---------------------------------------------------------------- 戳
def test_staging_dir_is_not_a_version_name(tmp_path):
    d = outputs.staging_dir(tmp_path / "p")
    assert d == tmp_path / "p" / "output" / "preview" and outputs.PREVIEW_DIR == "preview"
    assert not d.name[1:].isdigit()


def test_stamp_roundtrip_and_corrupt_is_none(tmp_path):
    outputs.write_stamp(tmp_path, {"table": "x"}, 3, 12.5)
    stamp = outputs.read_stamp(tmp_path)
    assert stamp["inputs"] == {"table": "x"} and stamp["shots"] == 3 and stamp["duration"] == 12.5 and stamp["at"]
    (tmp_path / outputs.STAMP_FILE).write_text("{坏", encoding="utf-8")
    assert outputs.read_stamp(tmp_path) is None
    assert outputs.read_stamp(tmp_path / "nope") is None


# ---------------------------------------------------------------- preview_state
def test_preview_state_none_fresh_outdated(tmp_path):
    pdir = _project(tmp_path)
    assert outputs.preview_state(pdir, CFG)["status"] == "none"
    _stage(pdir)
    st = outputs.preview_state(pdir, CFG)
    assert st["status"] == "fresh" and st["reasons"] == [] and st["shots"] == 1 and st["duration"] == 2.0 and st["at"]
    # 改一个字：outdated，原因 = table
    (pdir / "shots.json").write_text(json.dumps({"shots": [{**SHOTS[0], "sub": "乙"}]}), encoding="utf-8")
    st = outputs.preview_state(pdir, CFG)
    assert st["status"] == "outdated" and st["reasons"] == ["table"]


def test_preview_state_incomplete_mp4_counts_as_none_and_does_not_write(tmp_path):
    pdir = _project(tmp_path)
    d = _stage(pdir)
    media_io.done_marker(d / "preview.mp4").unlink()
    assert outputs.preview_state(pdir, CFG)["status"] == "none"
    assert not media_io.done_marker(d / "preview.mp4").exists()  # 状态判定不能写盘（不认领）


def test_preview_state_preset_change_is_outdated(tmp_path):
    pdir = _project(tmp_path)
    _stage(pdir)
    assert outputs.preview_state(pdir, {**CFG, "preset": "q"})["reasons"] == ["preset"]


# ---------------------------------------------------------------- promote
def test_promote_links_only_the_big_preview_and_copies_small_mutable_files(tmp_path):
    """HIGH-1：.timeline.sha 等小文件会被原地改写，不能与暂存共用 inode；只有大文件 preview.mp4 硬链接。"""
    pdir = _project(tmp_path)
    staging = _stage(pdir)
    vdir = pdir / "output" / "v1"
    outputs.promote(staging, vdir)
    assert (vdir / "preview.mp4").stat().st_ino == (staging / "preview.mp4").stat().st_ino
    for name in outputs.PROMOTED:
        assert (vdir / name).read_bytes() == (staging / name).read_bytes(), name
        if name != "preview.mp4":
            assert (vdir / name).stat().st_ino != (staging / name).stat().st_ino, name
    assert media_io.is_complete(vdir / "preview.mp4")


def test_staging_rewrites_never_change_a_promoted_version(tmp_path):
    pdir = _project(tmp_path)
    staging = _stage(pdir)
    vdir = pdir / "output" / "v1"
    outputs.promote(staging, vdir)
    before = {p.name: p.read_bytes() for p in vdir.iterdir()}
    (staging / ".timeline.sha").write_text("another-hash")        # 原地改写（旧的 ensure_preview 就是这样）
    (staging / "timeline.json").write_text('{"x": 1}', encoding="utf-8")
    with media_io.atomic_output(staging / "preview.mp4") as tmp:
        tmp.write_bytes(b"re-rendered")
    outputs.write_stamp(staging, {"table": "zzz"}, 9, 9.0)
    assert {p.name: p.read_bytes() for p in vdir.iterdir()} == before


def test_write_text_is_atomic_new_inode(tmp_path):
    f = tmp_path / "a.sha"
    f.write_text("one")
    ino = f.stat().st_ino
    keep = os.link(f, tmp_path / "other") or tmp_path / "other"
    schema.write_text(f, "two")
    assert f.read_text() == "two" and f.stat().st_ino != ino
    assert keep.read_text() == "one"                              # 另一个硬链接不受影响


def test_promote_falls_back_to_copy_when_link_fails(tmp_path, monkeypatch):
    pdir = _project(tmp_path)
    staging = _stage(pdir)

    def no_link(*a, **k):
        raise OSError("cross-device")
    monkeypatch.setattr(outputs.os, "link", no_link)
    vdir = pdir / "output" / "v1"
    outputs.promote(staging, vdir)
    assert (vdir / "preview.mp4").read_bytes() == b"mp4-bytes"
    assert (vdir / "preview.mp4").stat().st_ino != (staging / "preview.mp4").stat().st_ino
    assert media_io.is_complete(vdir / "preview.mp4")


def test_promote_replaces_existing_target(tmp_path):
    pdir = _project(tmp_path)
    staging = _stage(pdir)
    vdir = pdir / "output" / "v1"
    vdir.mkdir(parents=True)
    (vdir / "timeline.json").write_text("旧", encoding="utf-8")
    outputs.promote(staging, vdir)
    assert (vdir / "timeline.json").read_text(encoding="utf-8") == "{}"


def test_promote_without_complete_preview_raises_and_creates_nothing(tmp_path):
    pdir = _project(tmp_path)
    staging = _stage(pdir)
    media_io.done_marker(staging / "preview.mp4").unlink()
    with pytest.raises(outputs.PreviewMissing):
        outputs.promote(staging, pdir / "output" / "v1")
    assert not (pdir / "output" / "v1").exists()


def test_rerender_staging_does_not_change_promoted_version(tmp_path):
    """硬链接共享 inode：重新渲染（atomic_output 写新文件再改名）不能改到已晋升的那一份。"""
    pdir = _project(tmp_path)
    staging = _stage(pdir)
    vdir = pdir / "output" / "v1"
    outputs.promote(staging, vdir)
    with media_io.atomic_output(staging / "preview.mp4") as tmp:
        tmp.write_bytes(b"new-render")
    assert (vdir / "preview.mp4").read_bytes() == b"mp4-bytes"
    assert media_io.is_complete(vdir / "preview.mp4")


# ---------------------------------------------------------------- export.json
def test_mark_export_merges_kinds_and_legacy_is_none(tmp_path):
    vdir = tmp_path / "p" / "output" / "v1"
    vdir.mkdir(parents=True)
    assert outputs.read_exports(vdir) is None            # 旧版本没有 export.json = legacy
    outputs.mark_export(vdir, "mac", draft="片名_v1")
    assert outputs.read_exports(vdir)["mac"]["draft"] == "片名_v1"
    assert outputs.read_exports(vdir)["windows"] is None
    outputs.mark_export(vdir, "windows", zip="a.zip")
    got = outputs.read_exports(vdir)
    assert got["mac"]["draft"] == "片名_v1" and got["windows"]["zip"] == "a.zip" and got["windows"]["at"]


def test_mark_export_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        outputs.mark_export(tmp_path / "p" / "output" / "v1", "linux", zip="x")


def test_read_exports_corrupt_is_none(tmp_path):
    (tmp_path / outputs.EXPORT_FILE).write_text("{坏", encoding="utf-8")
    assert outputs.read_exports(tmp_path) is None


# ---------------------------------------------------------------- matching_version
def test_matching_version_picks_largest_matching_numeric_version(tmp_path):
    pdir = _project(tmp_path)
    inputs = {"table": "a"}
    for name, ins in (("v1", inputs), ("v2", {"table": "b"}), ("v10", inputs), ("v3", inputs), ("vx", inputs),
                      ("preview", inputs)):
        d = pdir / "output" / name
        d.mkdir(parents=True)
        (d / "timeline.json").write_text("{}", encoding="utf-8")
        outputs.write_stamp(d, ins, 1, 1.0)
    assert outputs.matching_version(pdir, inputs) == "v10"
    assert outputs.matching_version(pdir, {"table": "zzz"}) is None
    assert outputs.matching_version(tmp_path / "none", inputs) is None


# ---------------------------------------------------------------- windows_zip
@pytest.mark.parametrize("title", ["片名", 123, None, "", "a/b:c", "x" * 200, "​‮片.exe"])
def test_windows_zip_same_as_jobs(tmp_path, title):
    from gui import jobs
    pdir = tmp_path / "p1"
    assert outputs.windows_zip(pdir, "v1", title) == jobs.windows_zip(pdir, "v1", title)


def test_windows_zip_path_shape(tmp_path):
    assert outputs.windows_zip(tmp_path / "p1", "v2", "片名") == tmp_path / "p1/output/v2/片名_v2_Windows.zip"




# ---------------------------------------------------------------- HIGH-2：覆盖已有版本
def _promoted_v1_with_exports(pdir, inputs_table="old"):
    staging = _stage(pdir, inputs={"table": inputs_table})
    vdir = pdir / "output" / "v1"
    outputs.promote(staging, vdir)
    outputs.mark_export(vdir, "mac", draft="片名_v1")
    zip_path = outputs.windows_zip(pdir, "v1", "片名")
    zip_path.write_bytes(b"zip")
    outputs.mark_export(vdir, "windows", zip=zip_path.name)
    return vdir, zip_path


def test_promote_overwrite_with_new_content_resets_exports_and_removes_zip(tmp_path):
    pdir = _project(tmp_path)
    vdir, zip_path = _promoted_v1_with_exports(pdir)
    staging = _stage(pdir, inputs={"table": "new"}, content=b"new-mp4")
    res = outputs.promote(staging, vdir)
    assert res["replaced"] is True and res["old_mac"] == "片名_v1"
    assert outputs.read_exports(vdir) == {"mac": None, "windows": None}
    assert not zip_path.exists()
    assert (vdir / "preview.mp4").read_bytes() == b"new-mp4"


def test_promote_same_content_keeps_exports_and_zip(tmp_path):
    """⚑Q1：同一张表再晋升（补另一种导出物）不能抹掉已有的导出记录。"""
    pdir = _project(tmp_path)
    vdir, zip_path = _promoted_v1_with_exports(pdir)
    staging = _stage(pdir, inputs={"table": "old"})
    res = outputs.promote(staging, vdir)
    assert res == {"replaced": False, "old_mac": None}
    assert outputs.read_exports(vdir)["mac"]["draft"] == "片名_v1" and zip_path.exists()


def test_promote_overwrite_legacy_version_without_export_json(tmp_path):
    pdir = _project(tmp_path)
    vdir = pdir / "output" / "v1"
    vdir.mkdir(parents=True)
    (vdir / "timeline.json").write_text("旧", encoding="utf-8")
    old_zip = outputs.windows_zip(pdir, "v1", "片名")
    old_zip.write_bytes(b"zip")
    res = outputs.promote(_stage(pdir), vdir)
    assert res["replaced"] is True and res["old_mac"] is None
    assert not old_zip.exists() and outputs.read_exports(vdir) == {"mac": None, "windows": None}


# ---------------------------------------------------------------- MEDIUM-1：原子晋升
def test_failure_mid_promotion_leaves_no_version_dir(tmp_path, monkeypatch):
    pdir = _project(tmp_path)
    staging = _stage(pdir)
    calls = []
    real = outputs._link_or_copy

    def flaky(src, dst):
        calls.append(dst.name)
        if len(calls) == 3:
            raise OSError("disk full")
        real(src, dst)
    monkeypatch.setattr(outputs, "_link_or_copy", flaky)
    with pytest.raises(OSError):
        outputs.promote(staging, pdir / "output" / "v1")
    assert not (pdir / "output" / "v1").exists()
    assert [p.name for p in (pdir / "output").iterdir()] == ["preview"]   # 临时目录也清掉了


def test_promote_cleans_leftover_tmp_from_a_crashed_run(tmp_path):
    pdir = _project(tmp_path)
    staging = _stage(pdir)
    (pdir / "output" / ".v7.tmp").mkdir(parents=True)
    (pdir / "output" / ".v7.tmp" / "x").write_text("半成品")
    vdir = pdir / "output" / "v1"
    vdir.mkdir()
    (vdir / ".timeline.sha.promote.tmp").write_text("残片")
    outputs.promote(staging, vdir)
    assert not (pdir / "output" / ".v7.tmp").exists() and not (vdir / ".timeline.sha.promote.tmp").exists()


def test_version_listing_ignores_dot_dirs_and_incomplete_dirs(tmp_path):
    pdir = _project(tmp_path)
    out = pdir / "output"
    for name, has_tl in (("v1", True), ("v2", False), (".v3.tmp", True), ("vx", True), ("preview", True), ("v10", True)):
        (out / name).mkdir(parents=True)
        if has_tl:
            (out / name / "timeline.json").write_text("{}", encoding="utf-8")
    assert [d.name for d in outputs.version_dirs(pdir)] == ["v1", "v10"]
    assert outputs.next_version(pdir) == "v11"                     # 不完整的 v2 仍占着号，绝不覆盖它


def test_promote_expect_inputs_mismatch_raises_before_touching_anything(tmp_path):
    pdir = _project(tmp_path)
    staging = _stage(pdir, inputs={"table": "a"})
    with pytest.raises(outputs.PreviewStale):
        outputs.promote(staging, pdir / "output" / "v1", expect_inputs={"table": "b"})
    assert not (pdir / "output" / "v1").exists()
    outputs.promote(staging, pdir / "output" / "v1", expect_inputs={"table": "a"})


# ---------------------------------------------------------------- MEDIUM-3：export.json 读改写在锁内
def test_mark_export_runs_inside_build_section(tmp_path, monkeypatch):
    import contextlib
    events = []

    @contextlib.contextmanager
    def section(pdir, **kw):
        events.append(("lock", Path(pdir).name))
        yield
        events.append("unlock")
    monkeypatch.setattr(outputs.project_lock, "build_section", section)
    vdir = tmp_path / "proj" / "output" / "v1"
    vdir.mkdir(parents=True)
    outputs.mark_export(vdir, "mac", draft="d")
    assert events == [("lock", "proj"), "unlock"]

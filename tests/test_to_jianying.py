"""pipeline/to_jianying：分轨（GL-10）、安装事务与校验门（GL-11/GL-13）及审查修复。

分轨用纯文本时间线；安装相关用 ffmpeg 现做的 1 秒小片段。草稿根一律在 tmp_path 下。
"""
import errno
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import encode, plat, proc
from pipeline import to_jianying as tj

VOL = "D:/Volumes" if plat.IS_WIN else "/Volumes"   # 绝对路径前缀：Windows 需要盘符
SUB = {"style": {"align": 2}}
CARD = {"style": {"align": 5}}


def text_timeline(texts):
    return {"project": {"width": 1080, "height": 1920, "fps": 30},
            "video": [], "audio": [], "text": texts}


def _content(d):
    return json.loads((d / "draft_content.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- GL-10
def test_build_staging_card_overlapping_subtitle_does_not_crash(tmp_path):
    tl = text_timeline([{"text": "第一句", "start": 0.0, "end": 2.0, **SUB},
                        {"text": "片头卡", "start": 0.0, "end": 4.5, **CARD}])
    d = tj.build_staging(tl, tmp_path / "stg", "N")  # 改前：SegmentOverlap
    text_tracks = [t for t in _content(d)["tracks"] if t["type"] == "text"]
    assert sorted(t["name"] for t in text_tracks) == sorted([tj.SUBTITLE_TRACK, tj.CARD_TRACK])


def test_build_staging_skips_nonpositive_text(tmp_path):
    tl = text_timeline([{"text": "坏卡", "start": 5.0, "end": 3.0, **CARD},
                        {"text": "好字幕", "start": 0.0, "end": 1.0, **SUB}])
    d = tj.build_staging(tl, tmp_path / "stg", "N")
    durs = [s["target_timerange"]["duration"] for t in _content(d)["tracks"] for s in t["segments"]]
    assert durs and all(x > 0 for x in durs)


def test_build_staging_no_text_track_when_no_text(tmp_path):
    d = tj.build_staging(text_timeline([]), tmp_path / "stg", "N")
    assert [t for t in _content(d)["tracks"] if t["type"] == "text"] == []


def test_build_staging_adjacent_subtitles_do_not_overlap_by_rounding(tmp_path):
    # us(a)+us(b-a) ≠ us(b) 时会出现 1µs 重叠；共用绝对终点避免之
    tl = text_timeline([{"text": "a", "start": 76.3774619, "end": 78.0252725, **SUB},
                        {"text": "b", "start": 78.0252725, "end": 79.0, **SUB}])
    d = tj.build_staging(tl, tmp_path / "stg", "N")
    segs = [s["target_timerange"] for t in _content(d)["tracks"] for s in t["segments"]]
    assert segs[0]["start"] + segs[0]["duration"] <= segs[1]["start"]


def test_layout_texts_trims_same_track_overlap():
    out = tj.layout_texts([{"text": "a", "start": 0.0, "end": 2.0, **SUB},
                           {"text": "b", "start": 1.5, "end": 3.0, **SUB}])
    assert out[tj.SUBTITLE_TRACK][1]["start"] == 2.0
    assert out[tj.CARD_TRACK] == []


def test_layout_texts_does_not_mutate_input():
    items = [{"text": "a", "start": 0.0, "end": 2.0, **SUB},
             {"text": "b", "start": 1.5, "end": 3.0, **SUB}]
    tj.layout_texts(items)
    assert items[1]["start"] == 1.5


def test_layout_texts_warns_count_of_shifted_subtitles(capsys):
    tj.layout_texts([{"text": "a", "start": 0.0, "end": 2.0, **SUB},
                     {"text": "b", "start": 1.5, "end": 3.0, **SUB},
                     {"text": "c", "start": 2.5, "end": 4.0, **SUB}])
    out = capsys.readouterr().out
    assert "[warn]" in out and "2 条字幕" in out


def test_layout_texts_clamps_negative_start():
    out = tj.layout_texts([{"text": "a", "start": -0.5, "end": 1.0, **SUB}])
    assert out[tj.SUBTITLE_TRACK][0]["start"] == 0.0


# ---------------------------------------------------------------- GL-11 / GL-13


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("本机无 ffmpeg")
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                              text=True).stdout
    # 与产品同一套编码参数（VideoToolbox）；没有 VT 的 LGPL 构建（如 Linux CI）退回原生 mpeg4
    codec = encode.h264_args("clip") if " h264_videotoolbox " in encoders \
        else ["-c:v", "mpeg4", "-pix_fmt", "yuv420p"]
    out = tmp_path_factory.mktemp("media") / "S01.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=108x192:r=30:d=1", *codec, str(out)], check=True)
    return out


def full_timeline(clip, texts=None):
    texts = [{"text": "字幕", "start": 0.0, "end": 1.0, **SUB}] if texts is None else texts
    return {"project": {"width": 1080, "height": 1920, "fps": 30},
            "video": [{"id": "S01", "source": str(clip), "in": 0.0, "out": 1.0,
                       "timeline_in": 0.0}],
            "audio": [], "text": texts}


@pytest.fixture
def jy_root(tmp_path, monkeypatch):
    root = tmp_path / "draft_root"
    root.mkdir()
    (root / "root_meta_info.json").write_text(json.dumps(
        {"all_draft_store": [], "draft_ids": 1, "root_path": str(root)}), encoding="utf-8")
    monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(root))
    monkeypatch.setattr(tj, "jianying_running", lambda: False)  # 开发机上剪映可能真在跑
    return root


def staged(tmp_path, root, clip, name="T"):
    tl = full_timeline(clip)
    d = tj.build_staging(tl, tmp_path / "stg", name)
    draft_id = tj.normalize(d)
    size = tj.bundle_media(d, root / name)
    info = tj.macify(d, name, size, draft_id, root)
    return d, info, size, tj.expected(tl)


def registry(root):
    return json.loads((root / "root_meta_info.json").read_text(encoding="utf-8"))


def backups(root):
    return sorted(root.glob("root_meta_info.json.*.bak"))


def test_macify_points_meta_at_given_root(tmp_path, jy_root, clip):
    d, _, _, _ = staged(tmp_path, jy_root, clip)
    meta = json.loads((d / "draft_meta_info.json").read_text(encoding="utf-8"))
    assert meta["draft_root_path"] == str(jy_root)
    assert meta["draft_fold_path"] == str(jy_root / "T")


def test_install_registers_validated_draft(tmp_path, jy_root, clip, capsys):
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    target, _ = tj.install(d, jy_root, "T", info, size, expect)
    assert (target / "draft_info.json").exists()
    assert not (target / tj.INSTALL_MARKER).exists()
    assert not d.exists(), "安装成功后暂存目录不再保留"
    entry = registry(jy_root)["all_draft_store"][0]
    assert entry["draft_name"] == "T" and entry["draft_fold_path"] == str(target)
    assert "校验通过" in capsys.readouterr().out
    assert [p.name for p in jy_root.iterdir() if p.name.startswith(".")] == []


def test_with_entry_returns_new_registry():
    reg = {"all_draft_store": [{"draft_name": "T", "old": 1}, {"draft_name": "U"}], "x": 1}
    new = tj.with_entry(reg, {"draft_name": "T"})
    assert [e["draft_name"] for e in new["all_draft_store"]] == ["T", "U"]
    assert "old" not in new["all_draft_store"][0] and new["x"] == 1
    assert reg["all_draft_store"][0]["old"] == 1  # 不原地改


def test_install_rolls_back_when_register_fails(tmp_path, jy_root, clip, monkeypatch):
    before = (jy_root / "root_meta_info.json").read_bytes()
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    real = tj.write_json

    def flaky(path, obj):
        if path.name == "root_meta_info.json":
            raise OSError("disk full")
        real(path, obj)
    monkeypatch.setattr(tj, "write_json", flaky)
    with pytest.raises(OSError, match="disk full"):
        tj.install(d, jy_root, "T", info, size, expect)
    assert not (jy_root / "T").exists()  # 不留孤儿
    assert (jy_root / "root_meta_info.json").read_bytes() == before
    assert d.exists() and not (d / tj.INSTALL_MARKER).exists()
    assert backups(jy_root) == [], "回滚成功后删掉本次备份"
    monkeypatch.setattr(tj, "write_json", real)
    tj.install(d, jy_root, "T", info, size, expect)  # 重试不报「已存在」
    assert registry(jy_root)["all_draft_store"][0]["draft_name"] == "T"


def test_install_rejects_draft_failing_validation(tmp_path, jy_root, clip):
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    (d / "draft_meta_info.json").unlink()  # 校验 A 段 FAIL
    with pytest.raises(tj.InstallError, match="校验未通过") as exc:
        tj.install(d, jy_root, "T", info, size, expect)
    assert "[FAIL]" in str(exc.value)
    assert not (jy_root / "T").exists()
    assert registry(jy_root)["all_draft_store"] == []
    assert d.exists(), "未通过校验的草稿应留在暂存目录供排查"


def test_install_rejects_draft_not_matching_timeline(tmp_path, jy_root, clip):
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    with pytest.raises(tj.InstallError, match="视频片段数"):
        tj.install(d, jy_root, "T", info, size, {**expect, "videos": 2})
    assert registry(jy_root)["all_draft_store"] == []


def test_install_clears_own_orphan_from_crash(tmp_path, jy_root, clip):
    for orphan in (jy_root / "T", jy_root / f".T{tj.TMP_SUFFIX}"):
        orphan.mkdir()
        (orphan / tj.INSTALL_MARKER).write_text("T", encoding="utf-8")
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    tj.install(d, jy_root, "T", info, size, expect)
    assert registry(jy_root)["all_draft_store"][0]["draft_name"] == "T"
    assert not (jy_root / f".T{tj.TMP_SUFFIX}").exists()


def test_install_never_touches_user_folder_with_same_name(tmp_path, jy_root, clip):
    mine = jy_root / "T"
    mine.mkdir()
    (mine / "keep.txt").write_text("x")
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    with pytest.raises(tj.InstallError, match="已存在"):
        tj.install(d, jy_root, "T", info, size, expect)
    assert (mine / "keep.txt").exists()
    assert d.exists()


# ---------------------------------------------------------------- 审查修复 5：剪映中途被打开
def test_install_refuses_when_jianying_started(tmp_path, jy_root, clip, monkeypatch):
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    monkeypatch.setattr(tj, "jianying_running", lambda: True)
    with pytest.raises(tj.InstallError, match="剪映正在运行"):
        tj.install(d, jy_root, "T", info, size, expect)
    assert backups(jy_root) == [] and d.exists()


def test_install_rechecks_jianying_before_registering(tmp_path, jy_root, clip, monkeypatch):
    before = (jy_root / "root_meta_info.json").read_bytes()
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    answers = iter([False, True])  # 备份前没开，写注册表前开了
    monkeypatch.setattr(tj, "jianying_running", lambda: next(answers))
    with pytest.raises(tj.InstallError, match="剪映正在运行"):
        tj.install(d, jy_root, "T", info, size, expect)
    assert (jy_root / "root_meta_info.json").read_bytes() == before
    assert not (jy_root / "T").exists() and d.exists()


# ---------------------------------------------------------------- 审查修复 6：回滚与跨卷
def test_rollback_failure_is_loud_and_chained(tmp_path, jy_root, clip, monkeypatch, capsys):
    d, info, size, expect = staged(tmp_path, jy_root, clip)

    def flaky(path, obj):
        raise OSError("disk full")

    def stuck(*a, **k):
        raise OSError("目录被占用")
    monkeypatch.setattr(tj, "write_json", flaky)
    monkeypatch.setattr(tj, "_undo_placement", stuck)
    with pytest.raises(tj.InstallError, match="回滚失败") as exc:
        tj.install(d, jy_root, "T", info, size, expect)
    assert "disk full" in str(exc.value)                 # 原因不能丢
    assert isinstance(exc.value.__cause__, OSError) and "disk full" in str(exc.value.__cause__)
    assert "[ERROR] 回滚失败" in capsys.readouterr().out
    assert backups(jy_root), "回滚没成功时保留注册表备份"


def _exdev_for(src_dir, monkeypatch):
    real = os.rename

    def rename(src, dst):
        if Path(src) == src_dir:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(src, dst)
    monkeypatch.setattr(os, "rename", rename)


def test_install_across_volumes_copies_via_tmp(tmp_path, jy_root, clip, monkeypatch):
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    _exdev_for(d, monkeypatch)
    target, _ = tj.install(d, jy_root, "T", info, size, expect)
    assert (target / "draft_info.json").exists() and not (target / tj.INSTALL_MARKER).exists()
    assert not (jy_root / f".T{tj.TMP_SUFFIX}").exists()
    assert registry(jy_root)["all_draft_store"][0]["draft_name"] == "T"


def test_install_half_copy_across_volumes_is_cleaned(tmp_path, jy_root, clip, monkeypatch):
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    _exdev_for(d, monkeypatch)
    real_copytree = shutil.copytree

    def copy(a, b, **k):
        if Path(a).suffix == ".mp4":  # 拷到一半磁盘满
            raise OSError(errno.ENOSPC, "No space left on device")
        return shutil.copy2(a, b, **k)

    def copy_then_die(src, dst, symlinks=False, ignore=None, copy_function=None, *rest, **kw):
        return real_copytree(src, dst, symlinks, ignore, copy, *rest, **kw)
    monkeypatch.setattr(shutil, "copytree", copy_then_die)
    with pytest.raises(OSError):
        tj.install(d, jy_root, "T", info, size, expect)
    assert [p.name for p in jy_root.iterdir() if not p.name.startswith("root_meta")] == []
    assert d.exists() and (d / "Resources").exists() and not (d / tj.INSTALL_MARKER).exists()


# ---------------------------------------------------------------- 审查修复 10：备份数量
def test_successful_installs_keep_newest_backups(tmp_path, jy_root, clip):
    for i in range(tj.BACKUP_KEEP + 2):
        old = jy_root / f"root_meta_info.json.2020010{i}-000000.bak"
        old.write_text("{}", encoding="utf-8")
        os.utime(old, (1_600_000_000 + i, 1_600_000_000 + i))
    d, info, size, expect = staged(tmp_path, jy_root, clip)
    tj.install(d, jy_root, "T", info, size, expect)
    left = backups(jy_root)
    assert len(left) == tj.BACKUP_KEEP
    assert not (jy_root / "root_meta_info.json.20200100-000000.bak").exists()  # 最旧的被删


# ---------------------------------------------------------------- 审查修复 9：封面
def test_cover_failure_is_a_warning(tmp_path, jy_root, clip):
    tl = full_timeline(clip)
    d = tj.build_staging(tl, tmp_path / "stg", "T")
    size = tj.bundle_media(d, jy_root / "T")

    def runner(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "moov atom not found")
    tj.reset_warnings()
    tj.macify(d, "T", size, tj.normalize(d), jy_root, runner=runner)
    assert any("封面" in w for w in tj.warnings())


def test_cover_without_ffmpeg_is_install_error(tmp_path, jy_root, clip):
    d = tj.build_staging(full_timeline(clip), tmp_path / "stg", "T")
    size = tj.bundle_media(d, jy_root / "T")

    def runner(cmd, **kw):
        raise FileNotFoundError("ffmpeg")
    with pytest.raises(tj.InstallError, match="ffmpeg"):
        tj.macify(d, "T", size, tj.normalize(d), jy_root, runner=runner)


# ---------------------------------------------------------------- 注册表 / 草稿根
@pytest.mark.parametrize("setup", ["no_root", "no_meta", "bad_json", "bad_shape"])
def test_load_registry_clear_error_when_jianying_missing(tmp_path, setup):
    root = tmp_path / "r"
    if setup != "no_root":
        root.mkdir()
    if setup == "bad_json":
        (root / "root_meta_info.json").write_text("{坏", encoding="utf-8")
    if setup == "bad_shape":
        (root / "root_meta_info.json").write_text("[]", encoding="utf-8")
    with pytest.raises(tj.InstallError, match="剪映"):
        tj.load_registry(root)


def _setting(tmp_path, monkeypatch, value):
    monkeypatch.delenv("AI_CUT_DRAFT_ROOT", raising=False)
    setting = tmp_path / tj.JY_SETTING
    setting.parent.mkdir(parents=True)
    setting.write_text(f"[General]\ncurrentCustomDraftPath={value}\n", encoding="utf-8")
    return setting


def test_resolve_draft_root_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(tmp_path / "x"))
    assert tj.resolve_draft_root(home=tmp_path) == tmp_path / "x"


def test_resolve_draft_root_reads_jianying_custom_path(monkeypatch, tmp_path):
    _setting(tmp_path, monkeypatch, f"{VOL}/外接盘/drafts")
    assert tj.resolve_draft_root(home=tmp_path) == Path(f"{VOL}/外接盘/drafts")


def test_resolve_draft_root_decodes_qt_escapes(monkeypatch, tmp_path):
    _setting(tmp_path, monkeypatch, f"{VOL}/\\x5916\\x63a5/d")
    assert tj.resolve_draft_root(home=tmp_path) == Path(f"{VOL}/外接/d")


def test_resolve_draft_root_decodes_surrogate_pairs(monkeypatch, tmp_path):
    _setting(tmp_path, monkeypatch, f'"{VOL}/\\xd83d\\xde00/d"')
    assert tj.resolve_draft_root(home=tmp_path) == Path(f"{VOL}/\U0001F600/d")


def test_resolve_draft_root_default(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_CUT_DRAFT_ROOT", raising=False)
    assert tj.resolve_draft_root(home=tmp_path) == tmp_path / tj.DEFAULT_DRAFT_ROOT


@pytest.mark.parametrize("text", ["[General]\nother=1\n", "[General]\ncurrentCustomDraftPath=\n"])
def test_resolve_draft_root_default_when_not_customised(monkeypatch, tmp_path, text):
    monkeypatch.delenv("AI_CUT_DRAFT_ROOT", raising=False)
    setting = tmp_path / tj.JY_SETTING
    setting.parent.mkdir(parents=True)
    setting.write_text(text, encoding="utf-8")
    assert tj.resolve_draft_root(home=tmp_path) == tmp_path / tj.DEFAULT_DRAFT_ROOT


UNUSABLE = ["drafts/relative", f"@ByteArray({VOL}/x)", f"{VOL}/\\xd83d/lone", f"{VOL}/\\q"]
if not plat.IS_WIN:  # Windows 上 \\\\ 是 Qt 对反斜杠的合法转义
    UNUSABLE.append("/Volumes/a\\\\b")


@pytest.mark.parametrize("value", UNUSABLE)
def test_resolve_draft_root_unusable_custom_path_is_loud(monkeypatch, tmp_path, value):
    _setting(tmp_path, monkeypatch, value)
    with pytest.raises(tj.InstallError) as exc:
        tj.resolve_draft_root(home=tmp_path)  # 不能悄悄退回默认目录
    assert value in str(exc.value)


def test_resolve_draft_root_unreadable_setting_is_loud(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_CUT_DRAFT_ROOT", raising=False)
    (tmp_path / tj.JY_SETTING).mkdir(parents=True)  # 读文件会 IsADirectoryError
    with pytest.raises(tj.InstallError, match="全局设置"):
        tj.resolve_draft_root(home=tmp_path)


# ---------------------------------------------------------------- 入口（冻结路径）
def _timeline_file(tmp_path, tl):
    f = tmp_path / "timeline.json"
    f.write_text(json.dumps(tl), encoding="utf-8")
    return f


def _run_main(tmp_path, tl_file, *extra):
    return proc.run_inprocess("pipeline.to_jianying",
                              [str(tl_file), "--name", "T", "--staging", str(tmp_path / "stg"),
                               *extra])


def test_frozen_path_reports_missing_jianying(tmp_path, monkeypatch):
    tl = _timeline_file(tmp_path, text_timeline([{"text": "a", "start": 0.0, "end": 1.0, **SUB}]))
    monkeypatch.setattr(tj, "jianying_running", lambda: False)
    code, out = _run_main(tmp_path, tl)
    assert code == 1 and "找不到剪映草稿库" in out  # GL-12 + GL-13：conftest 指向的根不存在
    assert not (tmp_path / "stg" / "T").exists(), "确认剪映在之前不该先花时间生成草稿"


def test_main_reports_unusable_custom_path(tmp_path, monkeypatch):
    monkeypatch.setattr(tj.Path, "home", classmethod(lambda cls: tmp_path))
    _setting(tmp_path, monkeypatch, "@ByteArray(x)")
    tl = _timeline_file(tmp_path, text_timeline([]))
    code, out = _run_main(tmp_path, tl)
    assert code == 1 and "@ByteArray(x)" in out


def test_main_refuses_while_jianying_running(tmp_path, jy_root, clip, monkeypatch):
    tl = _timeline_file(tmp_path, full_timeline(clip))
    monkeypatch.setattr(tj, "jianying_running", lambda: True)
    code, out = _run_main(tmp_path, tl)
    assert code == 1 and "剪映正在运行" in out
    assert registry(jy_root)["all_draft_store"] == []


def test_main_installs_end_to_end(tmp_path, jy_root, clip):
    tl = _timeline_file(tmp_path, full_timeline(clip, [
        {"text": "a", "start": 0.0, "end": 1.0, **SUB},
        {"text": "卡", "start": 0.0, "end": 0.8, **CARD}]))
    code, out = _run_main(tmp_path, tl)
    assert code == 0, out
    assert "校验通过" in out and registry(jy_root)["all_draft_store"][0]["draft_name"] == "T"
    rep = tj.parse_report(out)
    assert rep["draft_path"] == str(jy_root / "T")
    assert rep["backup"] and rep["warnings"] == []


def test_main_summarises_warnings(tmp_path, jy_root, clip):
    tl = _timeline_file(tmp_path, full_timeline(clip, [
        {"text": "a", "start": 0.0, "end": 0.6, **SUB},
        {"text": "b", "start": 0.5, "end": 1.0, **SUB},     # 重叠 → 顺延
        {"text": "坏", "start": 0.9, "end": 0.2, **SUB}]))  # 非正时长 → 丢弃
    code, out = _run_main(tmp_path, tl)
    assert code == 0, out
    rep = tj.parse_report(out)
    assert len(rep["warnings"]) == 2
    assert out.strip().splitlines()[-1].startswith("  - ")  # 汇总块在最后


def test_main_validation_fail_exits_nonzero(tmp_path, jy_root, clip, monkeypatch):
    tl = _timeline_file(tmp_path, full_timeline(clip))
    from research import validate_draft
    monkeypatch.setattr(validate_draft, "check",
                        lambda d, *a, **k: {"fails": ["人为 FAIL"], "warns": [], "oks": []})
    code, out = _run_main(tmp_path, tl)
    assert code == 1 and "人为 FAIL" in out and "完成" not in out
    assert registry(jy_root)["all_draft_store"] == []
    assert not (jy_root / "T").exists()


def test_dry_run_does_not_require_jianying(tmp_path, clip):
    # Windows 导出（export_draft）走 --dry-run + 不存在的临时根，必须继续可用
    code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)), "--dry-run")
    assert code == 0, out
    assert "校验通过" in out  # 审查修复 2：dry-run 也过校验门（素材路径映射回暂存目录）
    assert (tmp_path / "stg" / "T" / "draft_info.json").exists()


def test_dry_run_validation_fail_exits_nonzero(tmp_path, clip, monkeypatch):
    from research import validate_draft
    monkeypatch.setattr(validate_draft, "check",
                        lambda d, *a, **k: {"fails": ["人为 FAIL"], "warns": [], "oks": []})
    code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)), "--dry-run")
    assert code == 1 and "人为 FAIL" in out


def test_parse_report_without_summary():
    assert tj.parse_report("随便什么输出\n") == {"warnings": [], "draft_path": None,
                                                 "backup": None}


# ---------------------------------------------------------------- M7：KI-18 模板缺失 / KI-59 同名 / KI-17 版本
def test_missing_template_fails_before_generating(tmp_path, clip, monkeypatch):
    monkeypatch.setattr(tj, "TEMPLATE", tmp_path / "nope.json")
    code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)), "--dry-run")
    assert code == 1 and "骨架模板" in out and "nope.json" in out
    assert not (tmp_path / "stg" / "T").exists()


def test_align_with_template_missing_is_install_error(tmp_path):
    with pytest.raises(tj.InstallError, match="骨架模板"):
        tj.align_with_template(tmp_path, tmp_path / "nope.json")


def test_same_name_draft_rejected_before_copying_media(tmp_path, jy_root, clip, monkeypatch):
    (jy_root / "T").mkdir()
    (jy_root / "T" / "keep.txt").write_text("x")
    monkeypatch.setattr(tj, "bundle_media", lambda *a: pytest.fail("不该先拷媒体"))
    code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)))
    assert code == 1 and "草稿已存在" in out
    assert not (tmp_path / "stg" / "T").exists() and (jy_root / "T" / "keep.txt").exists()


def test_own_orphan_does_not_block_precheck(tmp_path, jy_root, clip):
    (jy_root / "T").mkdir()
    (jy_root / "T" / tj.INSTALL_MARKER).write_text("T")
    code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)))
    assert code == 0, out


def test_major_version_mismatch_is_reported_as_warning(tmp_path, jy_root, clip, monkeypatch):
    monkeypatch.setattr(tj.jy_version, "installed_version", lambda *a: "12.0.0")
    code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)))
    assert code == 0, out
    assert any("12.0.0" in w for w in tj.parse_report(out)["warnings"])


def test_same_major_version_is_silent(tmp_path, jy_root, clip, monkeypatch):
    monkeypatch.setattr(tj.jy_version, "installed_version", lambda *a: "11.6.0")
    code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)))
    assert code == 0, out
    assert not any("11.6.0" in w for w in tj.parse_report(out)["warnings"])


def test_platform_app_version_comes_from_jy_version(tmp_path, jy_root, clip):
    d, _, _, _ = staged(tmp_path, jy_root, clip)
    assert _content(d)["platform"]["app_version"] == tj.jy_version.VERIFIED_VERSION

"""research/validate_draft：可导入、可重复调用（GL-11），以及安装校验门的覆盖面（审查修复 4）。"""
import json

import pytest

from pipeline import proc
from research import validate_draft as vd

VIDEO_ID = "0123456789abcdef0123456789abcdef"
TEXT_ID = "fedcba9876543210fedcba9876543210"


def _good_draft(tmp_path, name="good", *, videos=1, texts=1, media_path=None):
    d = tmp_path / name
    (d / "Resources").mkdir(parents=True)
    clip = d / "Resources" / "S01.mp4"
    clip.write_bytes(b"x")
    tracks, video_mats = [], []
    if videos:
        video_mats = [{"id": VIDEO_ID, "path": media_path or str(clip), "duration": 5_000_000}]
        tracks.append({"type": "video", "segments": [
            {"id": f"v{i}", "material_id": VIDEO_ID,
             "target_timerange": {"start": i * 1_000_000, "duration": 1_000_000},
             "source_timerange": {"start": 0, "duration": 1_000_000}} for i in range(videos)]})
    text_mats = [{"id": TEXT_ID, "content": json.dumps({"text": "字幕", "styles": []})}]
    if texts:
        tracks.append({"type": "text", "segments": [
            {"id": f"t{i}", "material_id": TEXT_ID,
             "target_timerange": {"start": i * 100_000, "duration": 100_000}} for i in range(texts)]})
    content = {k: {} for k in ("canvas_config", "config", "keyframes")}
    content.update({"duration": max(videos, 1) * 1_000_000, "fps": 30.0,
                    "id": "48F27DD5-BD09-41F9-A570-4415480DE4A7",
                    "materials": {"videos": video_mats, "texts": text_mats},
                    "tracks": tracks, "version": 360000, "new_version": "x"})
    for f in ("draft_content.json", "draft_info.json"):
        (d / f).write_text(json.dumps(content), encoding="utf-8")
    (d / "draft_meta_info.json").write_text("{}", encoding="utf-8")
    return d


def test_good_draft_passes(tmp_path):
    assert vd.check(str(_good_draft(tmp_path)))["fails"] == []


def test_check_does_not_carry_fails_between_calls(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    assert vd.check(str(bad))["fails"], "缺 draft_content.json 应判 FAIL"
    # 冻结版同进程第二次调用不能带着上一次的 FAIL
    assert vd.check(str(_good_draft(tmp_path)))["fails"] == []


def test_check_does_not_print(tmp_path, capsys):
    vd.check(str(_good_draft(tmp_path)))
    assert capsys.readouterr().out == ""


def test_run_inprocess_propagates_validation_fail(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    code, out = proc.run_inprocess("research.validate_draft", [str(bad)])
    assert code == 1 and "FAIL" in out


def test_cli_report_format_unchanged(tmp_path):
    code, out = proc.run_inprocess("research.validate_draft", [str(_good_draft(tmp_path))])
    assert code == 0, out
    assert "结果：OK=" in out and "=>  PASS" in out


# ---------------------------------------------------------------- 审查修复 4
def test_missing_mac_entry_file_fails(tmp_path):
    d = _good_draft(tmp_path)
    (d / "draft_info.json").unlink()  # Mac 版剪映的入口文件
    assert any("draft_info.json" in m for m in vd.check(str(d))["fails"])


def test_non_plain_mac_entry_file_only_warns(tmp_path):
    # 剪映打开过的草稿（真实 九月一号_v3）会把 draft_info.json 改写成加密格式，不能判 FAIL
    d = _good_draft(tmp_path)
    (d / "draft_info.json").write_bytes(b"\x00\x01binary")
    res = vd.check(str(d))
    assert res["fails"] == [] and any("draft_info.json" in m for m in res["warns"])


def test_draft_without_video_fails(tmp_path):
    res = vd.check(str(_good_draft(tmp_path, videos=0)))
    assert any("视频" in m for m in res["fails"])


def test_expect_matching_counts_passes(tmp_path):
    d = _good_draft(tmp_path, videos=2, texts=3)
    expect = {"videos": 2, "texts": 3, "video_end_us": 2_000_000 + 20_000}  # 取整/切片误差内
    assert vd.check(str(d), expect=expect)["fails"] == []


@pytest.mark.parametrize("expect, word", [
    ({"videos": 3, "texts": 3, "video_end_us": 2_000_000}, "视频片段"),
    ({"videos": 2, "texts": 5, "video_end_us": 2_000_000}, "文字片段"),
    ({"videos": 2, "texts": 3, "video_end_us": 9_000_000}, "成片时长"),
])
def test_expect_mismatch_fails(tmp_path, expect, word):
    d = _good_draft(tmp_path, videos=2, texts=3)
    assert any(word in m for m in vd.check(str(d), expect=expect)["fails"])


def test_relocate_checks_media_in_staging(tmp_path):
    # dry-run：素材路径指向"安装后"位置（尚不存在），校验时映射回暂存目录
    final = tmp_path / "root" / "good"
    d = _good_draft(tmp_path, media_path=str(final / "Resources" / "S01.mp4"))
    assert vd.check(str(d))["fails"], "不映射时安装后路径不存在 → FAIL"
    assert vd.check(str(d), relocate=(str(final), str(d)))["fails"] == []

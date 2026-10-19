import json
import zipfile

import pytest

from pipeline import export_draft as ex


def fake_draft(tmp_path):
    d = tmp_path / "draft" / "MyDraft"
    (d / "Resources").mkdir(parents=True)
    (d / "Resources" / "clip01.mp4").write_bytes(b"fake")
    content = {
        "duration": 10_000_000,
        "platform": {"os": "mac"},
        "materials": {
            "videos": [{"path": str(d / "Resources/clip01.mp4"), "duration": 5_000_000,
                        "width": 1080, "height": 1920, "type": "video"}],
            "audios": [],
        },
        "tracks": [],
    }
    (d / "draft_content.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (d / "draft_info.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (d / "draft_meta_info.json").write_text(json.dumps({"draft_id": "OLD"}, ensure_ascii=False),
                                            encoding="utf-8")
    return d


def test_package_draft_rewrites_paths_and_adds_installer(tmp_path):
    d = fake_draft(tmp_path)
    out = tmp_path / "out" / "Pkg.zip"
    ex.package_draft(d, "Test_Pack", out)
    info = ex.inspect_package(out)
    assert info["install"] and info["fix_paths"]
    assert info["placeholder"] is True
    assert info["drafts"], "应包含 draft_content.json"
    with zipfile.ZipFile(out) as z:
        content = json.loads(z.read(info["drafts"][0]).decode("utf-8"))
        path = content["materials"]["videos"][0]["path"]
        assert path.startswith("__DRAFT_DIR__")
        assert content["platform"]["os"] == "windows"


def test_ascii_name_sanitized(tmp_path):
    assert ex._api_name("九月一号 v4") == "v4"
    assert ex._api_name("ShangYue_v4") == "ShangYue_v4"
    assert ex._api_name("!!!") == "JianYing_Draft"


def test_missing_timeline_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        ex.build_windows_package(tmp_path / "nope.json", "x", tmp_path / "o.zip")


# ---------------------------------------------------------------- 审查修复 2：导出包校验
def _leftovers(out_dir):
    return [p.name for p in out_dir.iterdir()] if out_dir.exists() else []


def test_package_missing_installer_is_rejected(tmp_path, monkeypatch):
    d = fake_draft(tmp_path)
    monkeypatch.setattr(ex, "write_installer", lambda pkg: None)
    out = tmp_path / "out" / "Pkg.zip"
    with pytest.raises(RuntimeError, match="INSTALL.bat"):
        ex.package_draft(d, "Test_Pack", out)
    assert _leftovers(out.parent) == []  # 不留坏 zip、不留 _pkg 临时目录


def test_package_without_placeholder_is_rejected(tmp_path, monkeypatch):
    d = fake_draft(tmp_path)
    monkeypatch.setattr(ex, "rewrite_for_windows", lambda target: None)
    out = tmp_path / "out" / "Pkg.zip"
    with pytest.raises(RuntimeError, match="占位符"):
        ex.package_draft(d, "Test_Pack", out)
    assert _leftovers(out.parent) == []


def test_package_failure_cleans_temp_dir(tmp_path, monkeypatch):
    d = fake_draft(tmp_path)

    def boom(target):
        raise OSError("disk full")
    monkeypatch.setattr(ex, "rewrite_for_windows", boom)
    out = tmp_path / "out" / "Pkg.zip"
    with pytest.raises(OSError):
        ex.package_draft(d, "Test_Pack", out)
    assert _leftovers(out.parent) == []


def test_package_success_leaves_only_zip(tmp_path):
    out = tmp_path / "out" / "Pkg.zip"
    ex.package_draft(fake_draft(tmp_path), "Test_Pack", out)
    assert _leftovers(out.parent) == ["Pkg.zip"]  # 用户输出目录里不放 .done 标记

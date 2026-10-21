# -*- coding: utf-8 -*-
"""packaging/fetch_ffmpeg_win.py 的纯逻辑：自检输出判定、哈希校验下载、与 build_ffmpeg.sh 的滤镜清单一致。

不联网、不执行任何 ffmpeg：命令输出用伪造文本。packaging/ 与 PyPI 的 packaging 同名，按文件路径加载。
"""
import hashlib
import importlib.util
import io
import re
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("fetch_ffmpeg_win", ROOT / "packaging" / "fetch_ffmpeg_win.py")
fw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fw)

# 字面量：常量被改错时测试要能报出来
VERSION_LINE = "ffmpeg version n8.1.3-9-g29e619e767-20260930 Copyright (c) 2000-2026 the FFmpeg developers"
LICENSE_TEXT = ("ffmpeg is free software; you can redistribute it and/or modify\nit under the terms of the "
                "GNU Lesser General Public\nLicense as published by the Free Software Foundation; either\n"
                "version 3 of the License, or (at your option) any later version.")
BUILDCONF = "\n".join([
    "configuration:",
    "  --prefix=/ffbuild/prefix",
    "  --enable-version3",
    "  --disable-gpl",
    "  --disable-autodetect",
    "  --enable-libfreetype",
    "  --enable-libharfbuzz",
    "  --enable-libopenh264",
])


def encoders_text(names=("aac", "pcm_s16le", "rawvideo", "h264_mf")):
    return "Encoders:\n ------\n" + "".join(f" V....D {n:<20} desc\n" for n in names)


def filters_text(names=None):
    names = fw.REQUIRED_FILTERS if names is None else names
    return "Filters:\n" + "".join(f" T.C {n:<17} V->V       desc\n" for n in names)


def run_verify(**over):
    args = dict(version=VERSION_LINE, license_text=LICENSE_TEXT, buildconf=BUILDCONF,
                encoders=encoders_text(), filters=filters_text())
    args.update(over)
    return fw.check_outputs(**args)


def test_good_build_has_no_problems():
    assert run_verify() == []


def test_openh264_alone_is_enough():
    enc = encoders_text(("aac", "pcm_s16le", "rawvideo", "libopenh264"))
    assert run_verify(encoders=enc) == []


@pytest.mark.parametrize("flag", ["--enable-gpl", "--enable-nonfree", "--enable-libx264", "--enable-libx265"])
def test_gpl_buildconf_rejected(flag):
    problems = run_verify(buildconf=BUILDCONF + "\n  " + flag)
    assert any("GPL" in p for p in problems)


def test_disable_gpl_is_not_a_false_positive():
    assert "--disable-gpl" in BUILDCONF and run_verify() == []


@pytest.mark.parametrize("name", ["libxvid", "libvidstab", "libfdk-aac"])
def test_other_forbidden_libs_rejected(name):
    assert any("GPL" in p for p in run_verify(buildconf=BUILDCONF + f"\n  --enable-{name}"))


def test_substring_is_not_a_match():
    # --enable-libx2640 之类不是 --enable-libx264；token 精确匹配
    assert run_verify(buildconf=BUILDCONF + "\n  --enable-libx2640") == []


def test_missing_version3_rejected():
    conf = BUILDCONF.replace("--enable-version3", "")
    assert any("version3" in p for p in run_verify(buildconf=conf))


def test_license_text_without_v3_rejected():
    txt = LICENSE_TEXT.replace("version 3", "version 2.1")
    assert any("v3" in p for p in run_verify(license_text=txt))


def test_license_files_are_v3():
    assert fw.LICENSE_FILES == ("COPYING.LGPLv3", "COPYING.GPLv3")


def test_non_lgpl_license_rejected():
    problems = run_verify(license_text="GNU General Public License")
    assert any("LGPL" in p for p in problems)


@pytest.mark.parametrize("lib", ["libfreetype", "libharfbuzz"])
def test_missing_text_libs_rejected(lib):
    conf = BUILDCONF.replace(f"--enable-{lib}", "")
    assert any(lib in p for p in run_verify(buildconf=conf))


def test_missing_both_h264_encoders_rejected():
    enc = encoders_text(("aac", "pcm_s16le", "rawvideo"))
    problems = run_verify(encoders=enc)
    assert any("h264_mf" in p and "libopenh264" in p for p in problems)


def test_missing_base_encoder_rejected():
    enc = encoders_text(("aac", "rawvideo", "h264_mf"))
    assert any("pcm_s16le" in p for p in run_verify(encoders=enc))


def test_missing_filter_rejected():
    names = [f for f in fw.REQUIRED_FILTERS if f != "drawtext"]
    problems = run_verify(filters=filters_text(names))
    assert any("drawtext" in p for p in problems)


def test_filter_prefix_is_not_a_match():
    # 「scale2ref」之类不能顶替「scale」
    names = [f for f in fw.REQUIRED_FILTERS if f != "scale"] + ["scale2ref"]
    assert any("scale" in p for p in run_verify(filters=filters_text(names)))


def test_wrong_version_rejected():
    problems = run_verify(version="ffmpeg version n7.1-1-gabcdef Copyright")
    assert any("版本" in p for p in problems)


def test_problems_are_all_collected():
    problems = run_verify(version="x", license_text="", buildconf="", encoders="", filters="")
    assert len(problems) >= 5


def test_required_filters_match_build_ffmpeg_sh():
    text = (ROOT / "packaging" / "build_ffmpeg.sh").read_text(encoding="utf-8")
    m = re.search(r'^REQUIRED_FILTERS="([^"]+)"', text, re.M)
    assert m, "build_ffmpeg.sh 里找不到 REQUIRED_FILTERS"
    assert list(fw.REQUIRED_FILTERS) == m.group(1).split()


def test_sanitize_buildconf_strips_prefix():
    out = fw.sanitize_buildconf("  --prefix=/ffbuild/prefix --enable-libfreetype")
    assert "/ffbuild" not in out and "--prefix=<build-prefix>" in out


# ---------- 下载与哈希 ----------

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def make_opener(payload: bytes):
    calls = []

    def opener(url, timeout=None):
        calls.append((url, timeout))
        return FakeResponse(payload)
    opener.calls = calls
    return opener


def test_download_ok_keeps_file(tmp_path):
    data = b"hello"
    dest = tmp_path / "a.bin"
    opener = make_opener(data)
    fw.download("https://example.invalid/a", dest, hashlib.sha256(data).hexdigest(), opener=opener)
    assert dest.read_bytes() == data
    assert opener.calls[0][1] == fw.TIMEOUT_S
    assert not list(tmp_path.glob("*.part"))


def test_download_hash_mismatch_deletes_file(tmp_path):
    dest = tmp_path / "a.bin"
    with pytest.raises(RuntimeError, match="校验失败"):
        fw.download("https://example.invalid/a", dest, "0" * 64, opener=make_opener(b"evil"))
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part"))


def test_download_skips_when_cached_file_matches(tmp_path):
    data = b"cached"
    dest = tmp_path / "a.bin"
    dest.write_bytes(data)
    opener = make_opener(b"other")
    fw.download("https://example.invalid/a", dest, hashlib.sha256(data).hexdigest(), opener=opener)
    assert opener.calls == []


def test_download_redownloads_when_cached_file_is_corrupt(tmp_path):
    data = b"good"
    dest = tmp_path / "a.bin"
    dest.write_bytes(b"corrupt")
    fw.download("https://example.invalid/a", dest, hashlib.sha256(data).hexdigest(), opener=make_opener(data))
    assert dest.read_bytes() == data


def test_download_network_error_leaves_no_file(tmp_path):
    def boom(url, timeout=None):
        raise OSError("断网")
    dest = tmp_path / "a.bin"
    with pytest.raises(RuntimeError, match="下载失败"):
        fw.download("https://example.invalid/a", dest, "0" * 64, opener=boom)
    assert not dest.exists() and not list(tmp_path.glob("*.part"))


def test_download_rejects_non_200(tmp_path):
    def opener(url, timeout=None):
        r = FakeResponse(b"x")
        r.status = 404
        return r
    with pytest.raises(RuntimeError, match="HTTP 404"):
        fw.download("https://example.invalid/a", tmp_path / "a.bin", "0" * 64, opener=opener)
    assert not list(tmp_path.iterdir())


def test_download_caps_total_bytes(tmp_path):
    with pytest.raises(RuntimeError, match="大小上限"):
        fw.download("https://example.invalid/a", tmp_path / "a.bin", "0" * 64,
                    opener=make_opener(b"x" * 100), max_bytes=10)
    assert not list(tmp_path.iterdir())


def test_download_stale_part_is_replaced(tmp_path):
    data = b"fresh"
    (tmp_path / "a.bin.part").write_bytes(b"stale-half-file")
    dest = tmp_path / "a.bin"
    fw.download("https://example.invalid/a", dest, hashlib.sha256(data).hexdigest(), opener=make_opener(data))
    assert dest.read_bytes() == data and not (tmp_path / "a.bin.part").exists()


def test_download_replace_failure_becomes_runtimeerror(tmp_path, monkeypatch):
    data = b"ok"
    def bad_replace(src, dst):
        raise PermissionError("被占用")
    monkeypatch.setattr(fw.os, "replace", bad_replace)
    with pytest.raises(RuntimeError, match="下载失败"):
        fw.download("https://example.invalid/a", tmp_path / "a.bin", hashlib.sha256(data).hexdigest(),
                    opener=make_opener(data))
    assert not list(tmp_path.iterdir())


# ---------- 解压 ----------

def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def test_extract_binaries_picks_exes_only(tmp_path):
    zp = _zip(tmp_path / "b.zip", {"ffmpeg-x/bin/ffmpeg.exe": b"F", "ffmpeg-x/bin/ffprobe.exe": b"P",
                                   "ffmpeg-x/bin/ffplay.exe": b"X", "ffmpeg-x/../evil.exe": b"E"})
    out = tmp_path / "bin"
    fw.extract_binaries(zp, out)
    assert sorted(p.name for p in out.iterdir()) == ["ffmpeg.exe", "ffprobe.exe"]
    assert (out / "ffmpeg.exe").read_bytes() == b"F"


def test_extract_ignores_deeper_or_shallower_paths(tmp_path):
    zp = _zip(tmp_path / "b.zip", {"a/b/bin/ffmpeg.exe": b"DEEP", "bin/ffmpeg.exe": b"SHALLOW",
                                   "a/bin/ffmpeg.exe": b"F", "a/bin/ffprobe.exe": b"P"})
    out = tmp_path / "bin"
    fw.extract_binaries(zp, out)
    assert (out / "ffmpeg.exe").read_bytes() == b"F"


def test_extract_only_deep_member_fails(tmp_path):
    zp = _zip(tmp_path / "b.zip", {"a/b/bin/ffmpeg.exe": b"DEEP", "a/bin/ffprobe.exe": b"P"})
    with pytest.raises(RuntimeError, match="ffmpeg.exe"):
        fw.extract_binaries(zp, tmp_path / "bin")
    assert not (tmp_path / "bin" / "ffmpeg.exe").exists()


def test_extract_ambiguous_member_fails(tmp_path):
    zp = _zip(tmp_path / "b.zip", {"a/bin/ffmpeg.exe": b"1", "b/bin/ffmpeg.exe": b"2", "a/bin/ffprobe.exe": b"P"})
    with pytest.raises(RuntimeError, match="ffmpeg.exe"):
        fw.extract_binaries(zp, tmp_path / "bin")


def test_extract_binaries_missing_member_fails(tmp_path):
    zp = _zip(tmp_path / "b.zip", {"ffmpeg-x/bin/ffmpeg.exe": b"F"})
    with pytest.raises(RuntimeError, match="ffprobe.exe"):
        fw.extract_binaries(zp, tmp_path / "bin")


def test_extract_leaves_no_tmp_files(tmp_path):
    zp = _zip(tmp_path / "b.zip", {"a/bin/ffmpeg.exe": b"F", "a/bin/ffprobe.exe": b"P"})
    fw.extract_binaries(zp, tmp_path / "bin")
    assert not list((tmp_path / "bin").glob("*.tmp"))


def _tar(path, files):
    import tarfile
    with tarfile.open(path, "w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(f"FFmpeg-{fw.FFMPEG_COMMIT}/{name}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return path


def test_extract_license_writes_v3_texts(tmp_path):
    tp = _tar(tmp_path / "s.tar.gz", {"COPYING.LGPLv3": b"L3", "COPYING.GPLv3": b"G3"})
    fw.extract_license(tp, tmp_path / "lic")
    assert (tmp_path / "lic" / "FFmpeg-COPYING.LGPLv3").read_bytes() == b"L3"
    assert (tmp_path / "lic" / "FFmpeg-COPYING.GPLv3").read_bytes() == b"G3"


def test_extract_license_missing_or_oversize_fails(tmp_path):
    with pytest.raises(RuntimeError, match="找不到"):
        fw.extract_license(_tar(tmp_path / "a.tar.gz", {"COPYING.LGPLv3": b"L3"}), tmp_path / "lic")
    big = b"x" * (fw.MAX_LICENSE_BYTES + 1)
    with pytest.raises(RuntimeError, match="正常大小"):
        fw.extract_license(_tar(tmp_path / "b.tar.gz", {"COPYING.LGPLv3": big, "COPYING.GPLv3": b"G"}),
                           tmp_path / "lic2")


# ---------- verify()（_run 用伪造输出） ----------

def _fake_run(version=VERSION_LINE, probe_version=None, buildconf=BUILDCONF):
    probe_version = probe_version or version.replace("ffmpeg", "ffprobe", 1)

    def run(exe, *args):
        if args == ("-version",):
            return (probe_version if exe.name == "ffprobe.exe" else version) + "\nbuilt with gcc\n"
        return {"-L": LICENSE_TEXT, "-buildconf": buildconf, "-encoders": encoders_text(),
                "-filters": filters_text()}[args[0]]
    return run


def _bin_dir(tmp_path):
    (tmp_path / "bin").mkdir()
    for n in ("ffmpeg.exe", "ffprobe.exe"):
        (tmp_path / "bin" / n).write_bytes(b"")
    return tmp_path


def test_verify_writes_sanitized_buildconf(tmp_path, monkeypatch):
    monkeypatch.setattr(fw, "_run", _fake_run())
    fw.verify(_bin_dir(tmp_path))
    text = (tmp_path / "licenses" / "ffmpeg-buildconf.txt").read_text(encoding="utf-8")
    assert "<build-prefix>" in text and "/ffbuild" not in text


def test_verify_rejects_bad_probe_version(tmp_path, monkeypatch):
    monkeypatch.setattr(fw, "_run", _fake_run(probe_version="ffprobe version n7.0 x"))
    with pytest.raises(RuntimeError, match="ffprobe 版本不符"):
        fw.verify(_bin_dir(tmp_path))
    assert not (tmp_path / "licenses").exists()


def test_verify_rejects_gpl_build(tmp_path, monkeypatch):
    monkeypatch.setattr(fw, "_run", _fake_run(buildconf=BUILDCONF + " --enable-gpl"))
    with pytest.raises(RuntimeError, match="GPL"):
        fw.verify(_bin_dir(tmp_path))


def test_verify_missing_exes(tmp_path):
    with pytest.raises(RuntimeError, match="缺少"):
        fw.verify(tmp_path)


def test_pinned_constants_are_well_formed():
    assert re.fullmatch(r"autobuild-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}", fw.RELEASE_TAG)
    assert "latest" not in fw.FFMPEG_ZIP_URL
    for sha in (fw.FFMPEG_ZIP_SHA256, fw.FFMPEG_SRC_SHA256, fw.BUILD_SCRIPTS_SHA256):
        assert re.fullmatch(r"[0-9a-f]{64}", sha)
    assert fw.RELEASE_TAG in fw.FFMPEG_ZIP_URL
    assert fw.FFMPEG_COMMIT in fw.FFMPEG_SRC_URL

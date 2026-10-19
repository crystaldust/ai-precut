"""M5 终审整改：ffmpeg 自检的执行级测试、编码器预检、云端重试边界、计时、诊断与日志细节。"""
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import applog, cloud, encode

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "packaging" / "build_ffmpeg.sh"
KEY = "AKLTsecretkey123456"

# ---------------------------------------------------------------- 12. 用假 ffmpeg / otool 真跑 --verify-only
FAKE_FFMPEG = r"""#!/bin/bash
case "$*" in
  *-version*) echo "ffmpeg version ${FAKE_VERSION:-8.1.3} Copyright (c) 2000-2026"; echo "built with clang";;
  *-L*) if [[ "$FAKE_GPL" == 1 ]]; then echo "GNU General Public License"; else
        printf 'modify it under the terms of the GNU Lesser General Public\nLicense as published\n'; fi;;
  *-buildconf*) echo "  configuration:"; echo "    --prefix=/private/tmp/secret-build-machine/prefix";
        echo "    --enable-libfreetype"; echo "    --enable-libharfbuzz";
        [[ "$FAKE_GPL" == 1 ]] && echo "    --enable-gpl"; true;;
  *-encoders*) for e in h264_videotoolbox aac pcm_s16le rawvideo; do echo " V....D $e   x"; done;;
  *-filters*) for f in drawtext scdet blackdetect freezedetect silencedetect concat scale pad setsar fps trim setpts atrim asetpts aresample format anullsrc aformat; do
        [[ "$f" == drawtext && "$FAKE_NO_DRAWTEXT" == 1 ]] && continue; echo " .. $f   V->V   x"; done;;
esac
"""
FAKE_OTOOL = r"""#!/bin/bash
echo "$2:"
if [[ "$FAKE_BREW_LIB" == 1 ]]; then echo "	/opt/homebrew/lib/liblzma.5.dylib (x)"; fi
echo "	/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)"
"""


def _write_exec(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def fake_out(tmp_path):
    out = tmp_path / "out"
    (out / "bin").mkdir(parents=True)
    for name in ("ffmpeg", "ffprobe"):
        _write_exec(out / "bin" / name, FAKE_FFMPEG)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _write_exec(stubs / "otool", FAKE_OTOOL)
    return out, stubs


def run_script(out, stubs, *args, **env):
    e = {**os.environ, "AICUT_FFMPEG_OUT": str(out), "AICUT_FFMPEG_WORK": str(out.parent / "work"),
         "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", **env}
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=e,
                          timeout=60)


def test_verify_only_passes_lgpl_build_and_strips_build_prefix(fake_out):
    out, stubs = fake_out
    r = run_script(out, stubs, "--verify-only")
    assert r.returncode == 0, r.stdout + r.stderr
    conf = (out / "licenses" / "ffmpeg-buildconf.txt").read_text(encoding="utf-8")
    assert "secret-build-machine" not in conf and "--prefix=<build-prefix>" in conf
    assert "--enable-libharfbuzz" in conf


@pytest.mark.parametrize("env, msg", [
    ({"FAKE_GPL": "1"}, "不是 LGPL"),
    ({"FAKE_VERSION": "7.1"}, "版本"),
    ({"FAKE_NO_DRAWTEXT": "1"}, "缺滤镜 drawtext"),
    ({"FAKE_BREW_LIB": "1"}, "非系统库"),
])
def test_verify_only_rejects_bad_builds(fake_out, env, msg):
    out, stubs = fake_out
    r = run_script(out, stubs, "--verify-only", **env)
    assert r.returncode != 0 and msg in r.stdout + r.stderr
    assert not (out / "licenses" / "ffmpeg-buildconf.txt").exists()


def test_verify_only_fails_when_otool_fails(fake_out):
    out, stubs = fake_out
    _write_exec(stubs / "otool", "#!/bin/bash\necho 'not an object file' >&2\nexit 1\n")
    r = run_script(out, stubs, "--verify-only")
    assert r.returncode != 0 and "链接库" in r.stdout + r.stderr


def test_verify_sources_requires_pinned_tarballs(fake_out):
    out, stubs = fake_out
    (out / "sources").mkdir()
    (out / "sources" / "ffmpeg-8.1.3.tar.xz").write_bytes(b"not the real tarball")
    r = run_script(out, stubs, "--verify-sources")
    assert r.returncode != 0 and "ffmpeg-8.1.3.tar.xz" in r.stdout + r.stderr


def test_build_app_checks_sources_before_bundling():
    sh = (ROOT / "packaging/build_app.sh").read_text(encoding="utf-8")
    assert sh.index("build_ffmpeg.sh --verify-sources") < sh.index("mkdir -p dist/sources")


BUILD_TOOLS = ("clang", "make", "pkg-config", "cmake", "shasum", "tar")


@pytest.mark.skipif(any(shutil.which(t) is None for t in BUILD_TOOLS), reason="需要构建工具")
def test_download_failure_stops_at_curl(fake_out):
    out, stubs = fake_out
    _write_exec(stubs / "curl", "#!/bin/bash\necho 'curl: (22) 404' >&2\nexit 22\n")
    r = run_script(out, stubs)
    assert r.returncode == 22
    assert not list((out / "sources").glob("*.tar.xz"))
    assert "编译" not in r.stdout


def test_build_script_has_no_and_chains_for_build_steps():
    sh = SCRIPT.read_text(encoding="utf-8")
    assert " && mv " not in sh and "&& cmake --install" not in sh and "&& make install" not in sh


# ---------------------------------------------------------------- 2. 编码器预检
@pytest.fixture
def fresh_preflight(monkeypatch):
    monkeypatch.setattr(encode, "_PREFLIGHT", {})
    return encode


def test_preflight_ok_runs_once_per_process(fresh_preflight):
    calls = []

    def runner(cmd, **k):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stderr="")
    assert encode.preflight(runner=runner) is None
    assert encode.preflight(runner=runner) is None
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[:2] == ["ffmpeg", "-hide_banner"] and "lavfi" in cmd
    assert cmd[-3:] == ["-f", "null", "-"] and "h264_videotoolbox" in cmd


@pytest.mark.parametrize("result", [SimpleNamespace(returncode=1, stderr="Error: cannot create session"),
                                    OSError("no ffmpeg")])
def test_preflight_failure_gives_clear_message(fresh_preflight, result):
    def runner(cmd, **k):
        if isinstance(result, Exception):
            raise result
        return result
    msg = encode.preflight(runner=runner)
    assert msg.startswith("本机无法使用 VideoToolbox 硬件编码") and msg == encode.preflight()


def test_cli_prepare_fails_fast_when_encoder_unavailable(monkeypatch, capsys, consented, tmp_path):
    import aicut
    from test_aicut_cli import _project, _record_stages
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path)
    aicut.secrets.set("mediakit", "AKLTabcdefghij9f2a")
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    calls = _record_stages(monkeypatch)
    monkeypatch.setattr(aicut.encode, "preflight", lambda: encode.ENCODER_UNAVAILABLE)
    with pytest.raises(SystemExit):
        aicut.main(["prepare", "p1"])
    assert calls == [] and "VideoToolbox" in capsys.readouterr().out


def test_gui_prepare_blocked_when_encoder_unavailable(monkeypatch, consented, tmp_path):
    from gui import settings
    secrets = settings.secrets
    secrets.set("mediakit", "AKLTabcdefghij9f2a")
    secrets.set("deepseek", "sk-abcdefghijkl")
    monkeypatch.setattr(settings.encode, "preflight", lambda: encode.ENCODER_UNAVAILABLE)
    with pytest.raises(settings.PrepareBlocked) as ei:
        settings.check_prepare_ready(tmp_path)
    assert ei.value.need == "encoder" and "VideoToolbox" in str(ei.value)


# ---------------------------------------------------------------- 3. 不可重试的传输错误不重试
from test_cloud import ROUTES, SUBMIT, TASK, make, _wav  # noqa: E402


def test_non_retryable_transport_error_is_not_retried(tmp_path):
    c, http, _ = make({**ROUTES, SUBMIT: [cloud.CloudError("云端响应过大")]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert http.count(SUBMIT) == 1 and ei.value.retryable is False


def test_non_retryable_upload_error_is_not_retried(tmp_path):
    c, _, ups = make(ROUTES, uploads=[cloud.CloudError("请求地址无效")])
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert len(ups) == 1 and ei.value.retryable is False


@pytest.mark.parametrize("payload", [
    {"task_id": "t1", "status": "completed", "result": {"subtitles": [{"subtitle_text": "a"}]}},
    {"task_id": "t1", "result": {"status": "completed", "subtitles": [{"subtitle_text": "a"}]}},
])
def test_wait_task_accepts_status_top_level_or_in_result(payload):
    c, _, _ = make({TASK("t1"): [(200, payload)]})
    data = c.wait_task("t1", total_timeout=10)
    assert data["status"] == "completed" and data["subtitles"][0]["subtitle_text"] == "a"


def test_wait_task_failed_status_inside_result_is_terminal():
    c, _, _ = make({TASK("t1"): [(200, {"result": {"status": "failed"}})]})
    with pytest.raises(cloud.CloudError) as ei:
        c.wait_task("t1", total_timeout=10)
    assert ei.value.terminal is True


# ---------------------------------------------------------------- 5. 跳过的阶段不覆盖已记录时长
def test_quick_rerun_does_not_overwrite_recorded_duration(tmp_path, monkeypatch):
    work = tmp_path / "work"
    t = iter([0.0, 120.0, 500.0, 500.05])
    monkeypatch.setattr(applog.time, "monotonic", lambda: next(t))
    with applog.stage(work, "transcribe"):
        pass
    with applog.stage(work, "transcribe"):
        pass
    entry = json.loads((work / "timings.json").read_text(encoding="utf-8"))["transcribe"]
    assert entry["seconds"] == 120.0 and entry["ok"] is True
    assert entry["last_skipped"]


def test_failed_rerun_still_recorded(tmp_path, monkeypatch):
    work = tmp_path / "work"
    t = iter([0.0, 120.0, 500.0, 500.05])
    monkeypatch.setattr(applog.time, "monotonic", lambda: next(t))
    with applog.stage(work, "text"):
        pass
    with pytest.raises(RuntimeError):
        with applog.stage(work, "text"):
            raise RuntimeError("x")
    entry = json.loads((work / "timings.json").read_text(encoding="utf-8"))["text"]
    assert entry["ok"] is False


# ---------------------------------------------------------------- 7. 访达选中失败
def test_reveal_reports_open_failure(monkeypatch, tmp_path):
    from gui import support
    monkeypatch.setattr(support.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stderr="LSOpen failed"))
    assert support.reveal(tmp_path / "x.zip") is False
    monkeypatch.setattr(support.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    assert support.reveal(tmp_path / "x.zip") is True


def test_export_reports_reveal_false_with_message(monkeypatch, tmp_path):
    from gui import support
    monkeypatch.setattr(support.diagnostics, "build_bundle", lambda *a: tmp_path / "d.zip")
    monkeypatch.setattr(support, "reveal", lambda p: False)
    code, body = support.export_diagnostics({}, lambda n: tmp_path)
    assert code == 200 and body["revealed"] is False and body["message"] == support.REVEAL_FAILED_MSG


# ---------------------------------------------------------------- 8. 并发清理旧 CLI 日志
def test_prune_tolerates_files_vanishing(tmp_path, monkeypatch):
    for i in range(applog.CLI_LOG_KEEP + 3):
        (tmp_path / f"cli-x-{i}.log").write_text("x", encoding="utf-8")
    real_unlink = Path.unlink

    def racing_unlink(self, missing_ok=False):
        real_unlink(self, missing_ok=True)
        raise FileNotFoundError(self)  # 别的进程刚删掉
    monkeypatch.setattr(Path, "unlink", racing_unlink)
    applog._prune_cli_logs(tmp_path)  # 不抛


# ---------------------------------------------------------------- 10. setup 之前的日志不走 lastResort
def test_logging_before_setup_is_silent(capsys):
    applog.register_secret(KEY)
    applog.get("cli").error("早期错误 %s", KEY)
    err = capsys.readouterr().err
    assert KEY not in err and "早期错误" not in err


# ---------------------------------------------------------------- 11. 导出诊断包期间按钮不可重复点
from test_frontend_jobs import NODE, run_js  # noqa: E402


@pytest.mark.skipif(NODE is None, reason="需要 node")
def test_export_diag_ignores_clicks_while_in_flight():
    out = run_js("""
      let release; window.__api = () => new Promise(r => { release = r; });
      const btn = {disabled: false}; __rows = [btn];
      const p1 = exportDiag(); const during = btn.disabled; exportDiag();
      release({ok: true, name: 'a.zip', folder: 'Downloads'});
      p1.then(() => [calls.filter(c => c[0] === 'api').length, during, btn.disabled]);
    """, files=["support.js"])
    assert out == [1, True, False]

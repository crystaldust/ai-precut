"""M5 安全审查整改（MEDIUM 1–3，LOW 4–12）：诊断包不带用户内容、密钥登记、文件权限、HTTP 加固。"""
import json
import logging
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from pipeline import applog, cloud, diagnostics, llm, secrets

KEY = "AKLTsecretkey123456"


def _flush():
    for h in logging.getLogger(applog.ROOT_LOGGER).handlers:
        h.flush()


def _applog_text() -> str:
    _flush()
    return applog.current_log_file().read_text(encoding="utf-8")


# ---------------------------------------------------------------- 1. app.log 只记任务要点
def test_job_log_keeps_only_errors_and_summary(gui_server, monkeypatch):
    from conftest import make_project
    from gui import jobs
    from test_server_jobs import fake_command, wait_for
    applog.setup("app")
    make_project(gui_server.root)
    script = ("print('[·] 字幕卡 \\'隐私台词\\' 已跳过'); print('普通输出 隐私文稿');"
              "print('[!] 必留内容超过目标'); print('[x] 转写失败：网络 /Users/me/Movies/秘密.mov');"
              "print('[错误] ' + 'z' * 600)")
    fake_command(monkeypatch, jobs, [sys.executable, "-c", script])
    job_id = jobs.start_job("p1", "build")
    assert wait_for(lambda: jobs.JOBS[job_id]["status"] != "running")
    text = _applog_text()
    assert "隐私台词" not in text and "隐私文稿" not in text
    assert "必留内容超过目标" in text and "转写失败：网络" in text
    assert "/Users/me/Movies" not in text and "秘密.mov" in text
    assert "z" * 301 not in text
    assert "任务结束" in text and "5 行" in text


# ---------------------------------------------------------------- 1. LLMError 不回显模型内容
@pytest.mark.parametrize("content", ["这是转写原文，没有 JSON", "{坏 JSON 原文"])
def test_llm_parse_errors_do_not_echo_content(content):
    with pytest.raises(llm.LLMError) as ei:
        llm._parse_json(content)
    assert "原文" not in str(ei.value) and f"{len(content)} 字" in str(ei.value)


def test_llm_shape_and_http_errors_do_not_echo_body():
    def transport(url, headers, body, timeout):
        return 200, json.dumps({"choices": [{"message": {"content": 1}}], "x": "隐私分镜"})
    c = llm.DeepSeekClient(api_key="sk-abcdefgh12345678", sleep=lambda _: None,
                           transport=transport)
    with pytest.raises(llm.LLMError) as ei:
        c.chat_json("s", "u")
    assert "隐私分镜" not in str(ei.value)

    def bad(url, headers, body, timeout):
        return 400, json.dumps({"error": {"message": "context too long"}, "echo": "隐私文稿"})
    c2 = llm.DeepSeekClient(api_key="sk-abcdefgh12345678", sleep=lambda _: None, transport=bad)
    with pytest.raises(llm.LLMError) as ei:
        c2.chat_json("s", "u")
    assert "context too long" in str(ei.value) and "隐私文稿" not in str(ei.value)


def test_annotation_shape_error_does_not_echo_model_output():
    from pipeline import understand_text

    class Fake:
        def chat_json(self, *a, **k):
            return {"segments": "隐私标注原文"}
    with pytest.raises(llm.LLMError) as ei:
        understand_text._annotate_once(Fake(), [{"id": 1, "text": "x", "start": 0, "end": 1}], "")
    assert "隐私标注原文" not in str(ei.value)


# ---------------------------------------------------------------- 1. 诊断包路径只留文件名
def test_diagnostics_scrubs_absolute_paths_to_basenames():
    out = diagnostics._scrub("读 /Volumes/盘/素材/秘密.mov 失败；~/Movies/a.wav；"
                             "url https://x.example/a/b?…")
    assert "/Volumes" not in out and "秘密.mov" in out and "Movies" not in out
    assert "a.wav" in out and "https://x.example/a/b" in out


def test_diagnostics_docstring_and_ui_notice():
    assert "不保证" in diagnostics.__doc__ or "尽力" in diagnostics.__doc__
    js = (Path(__file__).resolve().parent.parent / "gui/static/support.js").read_text(encoding="utf-8")
    assert "COPY_DIAG_NOTICE" in js


# ---------------------------------------------------------------- 2. 登记密钥 + 模式
def test_save_key_registers_secret():
    from gui import settings
    settings.save_key({"provider": "mediakit", "value": KEY})
    assert KEY not in applog.redact(f"x {KEY}")


def test_register_known_secrets_reads_env_and_file_without_keyring(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-envkey12345678")
    secrets.set("mediakit", "AKLTfilekey12345678")
    monkeypatch.setattr(secrets, "_keyring", lambda: pytest.fail("不能为了脱敏去碰钥匙串"))
    applog.register_known_secrets()
    out = applog.redact("sk-envkey12345678 AKLTfilekey12345678")
    assert "envkey" not in out and "filekey" not in out


def test_start_job_and_diagnostics_register_known_secrets(gui_server, monkeypatch):
    from gui import jobs, support
    calls = []
    monkeypatch.setattr(applog, "register_known_secrets", lambda: calls.append(1))
    monkeypatch.setattr(support.diagnostics, "build_bundle", lambda *a: Path("/tmp/x.zip"))
    monkeypatch.setattr(support, "reveal", lambda p: None)
    support.export_diagnostics({}, lambda n: Path(n))
    from conftest import make_project
    from test_server_jobs import fake_command, wait_for
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "pass"])
    jid = jobs.start_job("p1", "build")
    wait_for(lambda: jobs.JOBS[jid]["status"] != "running")
    assert len(calls) == 2


@pytest.mark.parametrize("raw, leaked", [
    ("authorization: bearer abcDEF123456", "abcDEF123456"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA=="),
    ("key sk-proj-AbC_def-123456789", "AbC_def-123456789"),
    ("unregistered AKLTzzzz9999yyyy8888", "zzzz9999yyyy8888"),
])
def test_patterns_mask_unregistered_tokens(raw, leaked):
    assert leaked not in applog.redact(raw)


# ---------------------------------------------------------------- 3. failed.json
def test_failed_json_stores_audio_basename(tmp_path):
    cloud.record_failure(tmp_path, "asr", "boom", {"audio": str(tmp_path / "work/audio/asr.wav")})
    entry = json.loads((tmp_path / "failed.json").read_text(encoding="utf-8"))[-1]
    assert entry["context"]["audio"] == "asr.wav"


def test_diagnostics_filters_failed_json_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "ffmpeg_info", lambda: None)
    work = tmp_path / "p1/work"
    work.mkdir(parents=True)
    (tmp_path / "p1/project.json").write_text('{"name": "p1"}', encoding="utf-8")
    (work / "failed.json").write_text(json.dumps([{"stage": "asr", "error": "e", "at": "t",
                                                   "context": {"audio": "/x/秘密.wav"}}]),
                                      encoding="utf-8")
    z = diagnostics.build_bundle(tmp_path / "out", tmp_path / "p1")
    with zipfile.ZipFile(z) as f:
        items = json.loads(f.read("project/work/failed.json"))
    assert items == [{"stage": "asr", "error": "e", "at": "t"}]


# ---------------------------------------------------------------- 4. 权限
def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_log_dir_and_files_private(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    monkeypatch.setenv("AI_CUT_LOG_DIR", str(d))
    applog.setup("app", max_bytes=200, backups=2)
    log = applog.get("t")
    for i in range(30):
        log.info("行 %d %s", i, "x" * 20)
    _flush()
    assert _mode(d) == 0o700
    files = list(d.iterdir())
    assert len(files) >= 2 and all(_mode(f) == 0o600 for f in files)


def test_diagnostics_zip_private(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "ffmpeg_info", lambda: None)
    assert _mode(diagnostics.build_bundle(tmp_path, None)) == 0o600


# ---------------------------------------------------------------- 5–9. HTTP 加固
from test_cloud import ROUTES, SUBMIT, UPLOAD, make, _wav  # noqa: E402


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/y", "https:///nohost", "http://x/y"])
def test_upload_url_must_be_https_with_host(tmp_path, url):
    target = {"success": True, "result": {"file_id": "mediakit://F", "upload_url": url}}
    c, _, ups = make({**ROUTES, UPLOAD: [(200, target)]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert ups == [] and "上传地址" in str(ei.value)


def test_request_construction_value_error_becomes_cloud_error():
    with pytest.raises(cloud.CloudError) as ei:
        cloud.default_transport("GET", "not a url?sig=SECRET", {}, None, 5)
    assert "SECRET" not in str(ei.value)


def test_upload_failure_records_only_status_and_code(tmp_path):
    body = "<Error><Code>SignatureDoesNotMatch</Code><Message>隐私 detail</Message></Error>"
    c, _, _ = make(ROUTES, uploads=[(403, body)], retries=0)
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert "SignatureDoesNotMatch" in str(ei.value) and "403" in str(ei.value)
    assert "隐私" not in str(ei.value)


def test_response_size_is_capped(monkeypatch):
    class Resp:
        status = 200

        def read(self, n=-1):
            return b"x" * (n if n > 0 else cloud.MAX_RESPONSE_BYTES + 10)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(cloud, "_open", lambda req, timeout: Resp())
    with pytest.raises(cloud.CloudError) as ei:
        cloud.default_transport("GET", "https://x/api", {}, None, 5)
    assert "过大" in str(ei.value)


def test_submit_non_json_200_is_retryable_and_keeps_token(tmp_path):
    wav = _wav(tmp_path)
    c, http, _ = make({**ROUTES, SUBMIT: [(200, "<html>gw</html>")]}, retries=1)
    with pytest.raises(cloud.CloudError) as ei:
        c.transcribe(wav, tmp_path)
    assert ei.value.retryable is True and http.count(SUBMIT) == 2
    assert (tmp_path / cloud.SUBMIT_TOKEN_FILE).exists()


def test_non_ascii_key_rejected(tmp_path):
    c, http, _ = make(ROUTES, api_key="AKLT密钥key123456")
    with pytest.raises(cloud.CloudError):
        c.submit_asr(_wav(tmp_path))
    assert http.calls == []


# ---------------------------------------------------------------- 10. 多 CLI 进程各写各的
def test_cli_logs_are_per_run_with_retention(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    d.mkdir()
    monkeypatch.setenv("AI_CUT_LOG_DIR", str(d))
    for i in range(applog.CLI_LOG_KEEP + 5):
        old = d / f"cli-20260101-0000{i:02d}-{i}.log"
        old.write_text("old", encoding="utf-8")
        os.utime(old, (1000 + i, 1000 + i))
    applog.setup("cli")
    current = applog.current_log_file()
    assert current.name.startswith("cli-") and str(os.getpid()) in current.name
    assert len(list(d.glob("cli-*.log"))) == applog.CLI_LOG_KEEP
    assert current.exists()


# ---------------------------------------------------------------- 11. llm 不跟随重定向
def test_llm_transport_does_not_follow_redirects(monkeypatch):
    import urllib.error
    seen = {}

    def fake_open(req, timeout):
        seen["opener"] = True
        raise urllib.error.HTTPError(req.full_url, 302, "Found", {}, None)
    monkeypatch.setattr(llm, "_open", fake_open)
    status, _ = llm.default_transport("https://api.x/chat", {"Authorization": "Bearer k"}, b"{}", 5)
    assert status == 302 and seen


# ---------------------------------------------------------------- 12. meta 不带掩码 Key
def test_meta_credentials_only_configured_and_source(monkeypatch):
    monkeypatch.setattr(diagnostics, "ffmpeg_info", lambda: None)
    monkeypatch.setattr(diagnostics.secrets, "status", lambda: {
        "mediakit": {"configured": True, "source": "keyring", "masked": "AKLT****3456"}})
    meta = diagnostics._meta(None)
    assert meta["credentials"] == {"mediakit": {"configured": True, "source": "keyring"}}

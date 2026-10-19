"""日志落盘 / 轮转 / 脱敏 / 异常钩子 / 阶段计时（GL-19）。日志目录由 AI_CUT_LOG_DIR 指到 tmp。"""
import json
import logging
import os
import sys
import threading
from pathlib import Path

import pytest

from pipeline import applog

KEY = "AKLTsecretkey123456"


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    monkeypatch.setenv("AI_CUT_LOG_DIR", str(d))
    return d


def _flush():
    for h in logging.getLogger(applog.ROOT_LOGGER).handlers:
        h.flush()


def _text(path: Path) -> str:
    _flush()
    return path.read_text(encoding="utf-8")


def test_setup_writes_utf8_file_once(log_dir):
    log = applog.setup("app")
    applog.setup("app")
    log.info("转写开始")
    assert _text(log_dir / "app.log").count("转写开始") == 1


def test_child_logger_goes_to_same_file(log_dir):
    applog.setup("cli")
    applog.get("cloud").warning("上传重试")
    assert "上传重试" in _text(applog.current_log_file())
    assert applog.current_log_file().parent == log_dir


def test_default_dir_is_library_logs(monkeypatch):
    monkeypatch.delenv("AI_CUT_LOG_DIR", raising=False)
    assert applog.log_dir() == Path.home() / "Library" / "Logs" / "剪辑台"


def test_registered_secret_is_masked(log_dir):
    applog.register_secret(KEY)
    log = applog.setup("app")
    log.info(f"key={KEY}")
    text = _text(log_dir / "app.log")
    assert "****3456" in text and KEY not in text  # KI-67 新掩码


def test_short_secret_not_registered():
    applog.register_secret("abc")
    applog.register_secret(None)
    assert applog.redact("abc") == "abc"


def test_bearer_and_presigned_query_masked(log_dir):
    log = applog.setup("app")
    log.info("Authorization: Bearer sk-abcdef1234567890")
    log.info("PUT https://tos.x/obj?X-Tos-Signature=SIG123&X-Tos-Credential=CRED456 失败")
    log.info("key sk-zyxwvu9876543210 用完")
    text = _text(log_dir / "app.log")
    assert "sk-abcdef1234567890" not in text and "sk-zyxwvu9876543210" not in text
    assert "SIG123" not in text and "CRED456" not in text
    assert "https://tos.x/obj?…" in text


def test_args_and_exception_text_masked(log_dir):
    applog.register_secret(KEY)
    log = applog.setup("app")
    log.error("失败：%s", KEY)
    try:
        raise RuntimeError(f"boom {KEY}")
    except RuntimeError:
        log.exception("出错了")
    text = _text(log_dir / "app.log")
    assert KEY not in text and "Traceback" in text and "boom ****3456" in text


def test_rotation(log_dir):
    log = applog.setup("app", max_bytes=200, backups=2)
    for i in range(50):
        log.info("第 %d 行 %s", i, "x" * 20)
    _flush()
    names = sorted(p.name for p in log_dir.iterdir())
    assert "app.log.1" in names and len(names) <= 3


def test_unwritable_dir_falls_back_without_crash(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("AI_CUT_LOG_DIR", str(blocker / "sub"))
    log = applog.setup("app")
    log.info("不会崩")
    assert applog.current_log_file() is None


def test_current_log_file(log_dir):
    applog.setup("app")
    assert applog.current_log_file() == log_dir / "app.log"


def test_uncaught_thread_exception_logged(log_dir, monkeypatch):
    applog.setup("app")
    monkeypatch.setattr(applog, "_ORIG_THREAD_HOOK", lambda args: None)  # 不把堆栈再打到 stderr

    def boom():
        raise RuntimeError("线程炸了")
    t = threading.Thread(target=boom)
    t.start()
    t.join()
    text = _text(log_dir / "app.log")
    assert "线程炸了" in text and "Traceback" in text


def test_uncaught_main_exception_logged(log_dir, monkeypatch):
    applog.setup("app")
    monkeypatch.setattr(applog, "_ORIG_SYS_HOOK", lambda *a: None)
    try:
        raise ValueError("主线程炸了")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    assert "主线程炸了" in _text(log_dir / "app.log")


def test_reset_restores_hooks(log_dir):
    before = (sys.excepthook, threading.excepthook)
    applog.setup("app")
    applog.reset_for_tests()
    assert (sys.excepthook, threading.excepthook) == before
    assert not [h for h in logging.getLogger(applog.ROOT_LOGGER).handlers
                if getattr(h, "_aicut", False)]


def test_stage_records_timing(tmp_path, log_dir):
    work = tmp_path / "work"
    with applog.stage(work, "transcribe"):
        pass
    data = json.loads((work / "timings.json").read_text(encoding="utf-8"))
    assert data["transcribe"]["ok"] is True
    assert isinstance(data["transcribe"]["seconds"], float) and data["transcribe"]["seconds"] >= 0
    assert data["transcribe"]["started"]


def test_stage_failure_and_system_exit_recorded(tmp_path, log_dir):
    work = tmp_path / "work"
    with pytest.raises(RuntimeError):
        with applog.stage(work, "text"):
            raise RuntimeError("x")
    with pytest.raises(SystemExit):
        with applog.stage(work, "score"):
            sys.exit(1)
    data = json.loads((work / "timings.json").read_text(encoding="utf-8"))
    assert data["text"]["ok"] is False and data["score"]["ok"] is False


def test_stage_tolerates_corrupt_timings(tmp_path, log_dir):
    work = tmp_path / "work"
    work.mkdir()
    (work / "timings.json").write_text("{坏", encoding="utf-8")
    with applog.stage(work, "ingest"):
        pass
    assert json.loads((work / "timings.json").read_text(encoding="utf-8"))["ingest"]["ok"]


def test_stage_never_breaks_the_stage_when_disk_fails(tmp_path, log_dir, monkeypatch):
    work = tmp_path / "work"
    monkeypatch.setattr(applog.schema, "write_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with applog.stage(work, "ingest"):
        pass  # 记不下时长不能让阶段本身失败


def test_log_dir_not_created_on_import(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CUT_LOG_DIR", str(tmp_path / "never"))
    applog.log_dir()
    assert not os.path.exists(tmp_path / "never")


def test_hooks_restored_even_if_chain_target_patched(log_dir, monkeypatch):
    before = (sys.excepthook, threading.excepthook)
    applog.setup("app")
    monkeypatch.setattr(applog, "_ORIG_THREAD_HOOK", lambda args: None)
    monkeypatch.setattr(applog, "_ORIG_SYS_HOOK", lambda *a: None)
    applog.reset_for_tests()
    assert (sys.excepthook, threading.excepthook) == before


def test_bad_format_args_never_raise_into_caller():
    # Handler.filter 不在 emit 的 try 里：格式串与参数不匹配不能把异常抛给业务代码
    record = logging.LogRecord("aicut", logging.INFO, __file__, 1, "两个占位 %s %s",
                               (KEY,), None)
    applog.register_secret(KEY)
    assert applog.RedactFilter().filter(record) is True
    assert "两个占位" in record.msg and KEY not in record.msg and record.args is None


def test_stack_info_is_redacted(log_dir):
    applog.register_secret(KEY)
    log = applog.setup("app")

    def inner(k):
        log.info("看栈", stack_info=True)
    inner(KEY)
    assert "Stack (most recent call last)" in _text(log_dir / "app.log")
    assert KEY not in _text(log_dir / "app.log")


def test_concurrent_setup_installs_one_handler(log_dir):
    threads = [threading.Thread(target=applog.setup, args=("app",)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ours = [h for h in logging.getLogger(applog.ROOT_LOGGER).handlers if getattr(h, "_aicut", False)]
    assert len(ours) == 1

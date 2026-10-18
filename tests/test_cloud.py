import json
import subprocess
from pathlib import Path

import pytest

from pipeline import cloud


class FakeProc:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def make_runner(sequence):
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        item = sequence[min(len(calls) - 1, len(sequence) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return runner, calls


def client(sequence, **kw):
    runner, calls = make_runner(sequence)
    c = cloud.CloudClient(env={}, runner=runner, sleep=lambda _: None, **kw)
    return c, calls


def test_submit_parses_task_id():
    c, calls = client([FakeProc(out=json.dumps({"task_id": "t1"}))])
    assert c.submit_asr(Path("/tmp/a.wav")) == "t1"
    assert calls[0][0] == "mediakit-cli"
    assert calls[0][1:3] == ["video", "asr-subtitles"]
    assert "MEDIAKIT_API_KEY" not in calls[0]


def test_retry_on_network_error_then_success():
    seq = [subprocess.TimeoutExpired("mediakit-cli", 30),
           FakeProc(out=json.dumps({"task_id": "t2"}))]
    c, calls = client(seq)
    assert c.submit_asr(Path("/tmp/a.wav")) == "t2"
    assert len(calls) == 2


def test_business_error_not_retried():
    seq = [FakeProc(code=1, out="", err="invalid audio format")]
    c, calls = client(seq)
    with pytest.raises(cloud.CloudError):
        c.submit_asr(Path("/tmp/a.wav"))
    assert len(calls) == 1


def test_client_token_reused_across_retries():
    seq = [FakeProc(code=503, err="503 service unavailable"),
           FakeProc(out=json.dumps({"task_id": "t3"}))]
    c, calls = client(seq)
    c.submit_asr(Path("/tmp/a.wav"))
    tokens = [args[args.index("--client-token") + 1] for args in calls]
    assert len(set(tokens)) == 1


def test_transcribe_writes_raw_and_failure_record(tmp_path):
    ok = FakeProc(out=json.dumps({"task_id": "t4"}))
    done = FakeProc(out=json.dumps({"status": "completed", "subtitles": []}))
    c, _ = client([ok, done])
    c.transcribe(tmp_path / "a.wav", tmp_path)
    assert (tmp_path / "transcript_raw.json").exists()

    bad = FakeProc(code=1, err="bad request")
    c2, _ = client([bad])
    with pytest.raises(cloud.CloudError):
        c2.transcribe(tmp_path / "b.wav", tmp_path)
    failed = json.loads((tmp_path / "failed.json").read_text(encoding="utf-8"))
    assert failed[-1]["stage"] == "asr"


def test_missing_cli_raises_helpful_error():
    c, _ = client([FileNotFoundError()])
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(Path("/tmp/a.wav"))
    assert "mediakit-cli" in str(ei.value)


def test_wait_polls_until_completed():
    seq = [FakeProc(out=json.dumps({"status": "running"})),
           FakeProc(out=json.dumps({"status": "running"})),
           FakeProc(out=json.dumps({"status": "completed", "subtitles": []}))]
    c, calls = client(seq)
    data = c.wait_task("t1", total_timeout=60)
    assert data["status"] == "completed"
    assert len(calls) == 3
    assert "--poll-complete" not in calls[0]      # 不能再用阻塞轮询
    assert "--max-poll-attempts" in calls[0]


def test_wait_raises_on_failed_task():
    c, _ = client([FakeProc(out=json.dumps({"status": "failed", "message": "boom"}))])
    with pytest.raises(cloud.CloudError) as ei:
        c.wait_task("t1", total_timeout=10)
    assert "boom" in str(ei.value)


def test_wait_times_out_with_actionable_message(monkeypatch):
    c, _ = client([FakeProc(out=json.dumps({"status": "running"}))])
    t = [0.0]

    def fake_mono():
        t[0] += 30
        return t[0]

    monkeypatch.setattr(cloud.time, "monotonic", fake_mono)
    with pytest.raises(cloud.CloudError) as ei:
        c.wait_task("t1", total_timeout=5, interval=0)
    msg = str(ei.value)
    assert "不会重新提交" in msg


def test_transcribe_resumes_from_saved_task(tmp_path):
    (tmp_path / "asr_task.json").write_text(
        json.dumps({"task_id": "saved-task", "at": 9e9}), encoding="utf-8")
    c, calls = client([FakeProc(out=json.dumps({"status": "completed"}))])
    c.transcribe(tmp_path / "a.wav", tmp_path)
    # 只查了一次，没有重新提交
    assert len(calls) == 1
    assert "--task-id" in calls[0] and "saved-task" in calls[0]

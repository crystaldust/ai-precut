"""MediaKit 云端 ASR：HTTP 直连客户端（GL-01）。全部 mock，不发真实请求。"""
import json
from pathlib import Path

import pytest

from pipeline import asr_state, cloud

KEY = "AKLTsecretkey123456"
SIG = "SECRETSIG"
UP_TARGET = {"success": True, "result": {
    "file_id": "mediakit://F1", "method": "PUT",
    "upload_url": f"https://tos.example.com/obj?X-Tos-Signature={SIG}",
    "upload_headers": [{"key": "Content-Type", "value": "audio/wav"}]}}
UPLOAD = ("POST", "/api/v1/tools-sync/request-media-upload-url")
SUBMIT = ("POST", "/api/v1/tools/asr-subtitles")


def TASK(tid):
    return ("GET", f"/api/v1/tasks/{tid}")


def ok_task(tid="t1"):
    return 200, {"success": True, "task_id": tid, "task_type": "asr-subtitles"}


DONE = (200, {"task_id": "t1", "status": "completed",
              "result": {"duration": 3.0, "subtitles": []}})


class FakeHttp:
    """按 (method, path) 顺序返回预设响应（最后一个重复）；记录每次请求。"""

    def __init__(self, routes):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.calls = []

    def transport(self, method, url, headers, body, timeout):
        assert url.startswith(cloud.DEFAULT_ENDPOINT)
        path = url[len(cloud.DEFAULT_ENDPOINT):]
        self.calls.append({"method": method, "path": path, "headers": headers,
                           "body": json.loads(body) if body else None})
        seq = self.routes[(method, path)]
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, Exception):
            raise item
        status, payload = item
        return status, payload if isinstance(payload, str) else json.dumps(payload)

    def count(self, key):
        return sum(1 for c in self.calls if (c["method"], c["path"]) == key)

    def bodies(self, key):
        return [c["body"] for c in self.calls if (c["method"], c["path"]) == key]


def make(routes, uploads=None, **kw):
    http = FakeHttp(routes)
    up_calls = []
    queue = list(uploads or [])

    def uploader(method, url, headers, path, timeout):
        up_calls.append({"method": method, "url": url, "headers": headers, "path": path})
        item = (queue.pop(0) if len(queue) > 1 else queue[0]) if queue else (200, "")
        if isinstance(item, Exception):
            raise item
        return item

    kw.setdefault("api_key", KEY)
    c = cloud.CloudClient(sleep=lambda _: None, transport=http.transport,
                          uploader=uploader, **kw)
    return c, http, up_calls


def _wav(tmp_path, name="a.wav", body=b"RIFF-audio"):
    wav = tmp_path / name
    wav.write_bytes(body)
    return wav


ROUTES = {UPLOAD: [(200, UP_TARGET)], SUBMIT: [ok_task()], TASK("t1"): [DONE]}


# ---------------------------------------------------------------- 上传 + 提交
def test_submit_uploads_local_audio_then_submits_file_id(tmp_path):
    wav = _wav(tmp_path)
    c, http, ups = make(ROUTES)
    assert c.submit_asr(wav) == "t1"
    assert http.bodies(UPLOAD) == [{"tool_name": "asr-subtitles"}]
    assert len(ups) == 1
    assert ups[0]["method"] == "PUT" and ups[0]["path"] == wav
    assert ups[0]["headers"] == {"Content-Type": "audio/wav"}
    assert "Authorization" not in ups[0]["headers"]
    body = http.bodies(SUBMIT)[0]
    assert body["audio_url"] == "mediakit://F1"
    assert body["language"] == "cmn-Hans-CN"
    assert body["enable_speaker_info"] is True and body["enable_confidence"] is True
    assert isinstance(body["client_token"], str) and 0 < len(body["client_token"]) <= 64


def test_remote_url_is_submitted_without_upload():
    c, http, ups = make(ROUTES)
    c.submit_asr("https://cdn.example.com/a.wav")
    assert ups == [] and http.count(UPLOAD) == 0
    assert http.bodies(SUBMIT)[0]["audio_url"] == "https://cdn.example.com/a.wav"


def test_upload_method_defaults_to_put_and_string_headers(tmp_path):
    target = {"success": True, "result": {
        "file_id": "mediakit://F2", "upload_url": "https://tos.example.com/o?sig=1",
        "upload_headers": ["Content-Type: audio/wav", "x-tos-meta: a:b"]}}
    c, http, ups = make({**ROUTES, UPLOAD: [(200, target)]})
    c.submit_asr(_wav(tmp_path))
    assert ups[0]["method"] == "PUT"
    assert ups[0]["headers"] == {"Content-Type": "audio/wav", "x-tos-meta": "a:b"}
    assert http.bodies(SUBMIT)[0]["audio_url"] == "mediakit://F2"


def test_upload_target_missing_fields_raises(tmp_path):
    bad = {"success": True, "result": {"file_id": "mediakit://F"}}
    c, _, _ = make({**ROUTES, UPLOAD: [(200, bad)]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert "上传地址" in str(ei.value)


def test_upload_failure_reissues_upload_url_then_succeeds(tmp_path):
    c, http, ups = make(ROUTES, uploads=[(403, "<Error>expired</Error>"), (200, "")])
    assert c.submit_asr(_wav(tmp_path)) == "t1"
    assert http.count(UPLOAD) == 2 and len(ups) == 2


def test_upload_network_error_retried(tmp_path):
    c, _, ups = make(ROUTES, uploads=[cloud.CloudError("上传网络错误：timed out", retryable=True),
                                      (200, "")])
    assert c.submit_asr(_wav(tmp_path)) == "t1"
    assert len(ups) == 2


def test_upload_bad_request_not_retried(tmp_path):
    c, _, ups = make(ROUTES, uploads=[(400, "bad")])
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert len(ups) == 1 and ei.value.retryable is False


# ---------------------------------------------------------------- 鉴权与脱敏
def test_auth_header_is_bearer_with_client_headers(tmp_path):
    c, http, _ = make(ROUTES)
    c.submit_asr(_wav(tmp_path))
    for call in http.calls:
        h = call["headers"]
        assert h["Authorization"] == f"Bearer {KEY}"
        assert h["Accept"] == "application/json"
        assert h["X-Amk-Cli-Runtime"] == cloud.CLIENT_RUNTIME == "aicut"
        assert h["X-Amk-Task-Source"] == cloud.CLIENT_TASK_SOURCE == "cli/aicut"


def test_401_is_helpful_never_contains_key_and_not_retried(tmp_path):
    c, http, _ = make({**ROUTES, UPLOAD: [(401, {"error": {"message": f"bad key {KEY}"}})]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    msg = str(ei.value)
    assert "MediaKit API Key 无效" in msg
    assert KEY not in msg and "AKLT****3456" in msg
    assert http.count(UPLOAD) == 1
    assert ei.value.retryable is False and ei.value.terminal is False


def test_client_repr_and_errors_do_not_leak_key():
    c, _, _ = make(ROUTES)
    assert KEY not in repr(c)


def test_missing_key_raises_helpful_error(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud.secrets, "get", lambda name: None)
    c, http, _ = make(ROUTES, api_key=None)
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert "config set mediakit" in str(ei.value)
    assert http.calls == []


def test_key_is_read_from_secrets_when_not_given(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud.secrets, "get", lambda name: KEY if name == "mediakit" else None)
    c, http, _ = make(ROUTES, api_key=None)
    c.submit_asr(_wav(tmp_path))
    assert http.calls[0]["headers"]["Authorization"] == f"Bearer {KEY}"


# ---------------------------------------------------------------- 重试语义
def test_retry_on_503_then_success_reuses_client_token(tmp_path):
    c, http, _ = make({**ROUTES, SUBMIT: [(503, "busy"), ok_task("t3")]})
    assert c.submit_asr(_wav(tmp_path)) == "t3"
    tokens = [b["client_token"] for b in http.bodies(SUBMIT)]
    assert len(tokens) == 2 and len(set(tokens)) == 1


def test_network_error_retried(tmp_path):
    c, http, _ = make({**ROUTES, SUBMIT: [cloud.CloudError("网络错误：timed out", retryable=True),
                                          ok_task("t2")]})
    assert c.submit_asr(_wav(tmp_path)) == "t2"
    assert http.count(SUBMIT) == 2


def test_network_exhaustion_is_retryable(tmp_path):
    c, http, _ = make({**ROUTES, SUBMIT: [(502, "bad gateway")]}, retries=2)
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert ei.value.retryable is True and http.count(SUBMIT) == 3


def test_business_failure_not_retried(tmp_path):
    c, http, _ = make({**ROUTES, SUBMIT: [(200, {"success": False,
                                                 "error": {"message": "invalid audio"}})]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert "invalid audio" in str(ei.value)
    assert http.count(SUBMIT) == 1 and ei.value.retryable is False


def test_400_not_retried(tmp_path):
    c, http, _ = make({**ROUTES, SUBMIT: [(400, {"error": {"message": "bad param"}})]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert "bad param" in str(ei.value) and http.count(SUBMIT) == 1


@pytest.mark.parametrize("payload,expected", [
    ({"error": {"error": "e1"}}, "e1"), ({"error": {"msg": "e2"}}, "e2"),
    ({"message": "e3"}, "e3"), ({"msg": "e4"}, "e4"), ({"error": "e5"}, "e5"),
])
def test_error_message_shapes(tmp_path, payload, expected):
    c, _, _ = make({**ROUTES, SUBMIT: [(400, payload)]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert expected in str(ei.value)


def test_non_json_success_raises(tmp_path):
    c, _, _ = make({**ROUTES, SUBMIT: [(200, "<html>gateway</html>")]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert "不是 JSON" in str(ei.value)


def test_missing_task_id_raises(tmp_path):
    c, _, _ = make({**ROUTES, SUBMIT: [(200, {"success": True})]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert "task_id" in str(ei.value)


# ---------------------------------------------------------------- 轮询
def test_wait_polls_until_completed_and_flattens_result():
    done = (200, {"status": "completed", "task_id": "t1", "result": {
        "duration": 3.0, "subtitles": [{"start_time": 0, "end_time": 1, "subtitle_text": "你好"}]}})
    c, http, _ = make({TASK("t1"): [(200, {"status": "running"}), (200, {"status": "queued"}),
                                    done]})
    data = c.wait_task("t1", total_timeout=60)
    assert data["status"] == "completed" and data["task_id"] == "t1"
    assert data["duration"] == 3.0 and data["subtitles"][0]["subtitle_text"] == "你好"
    assert http.count(TASK("t1")) == 3


@pytest.mark.parametrize("status", ["failed", "error", "canceled", "cancelled"])
def test_terminal_task_status_is_marked_terminal(status):
    c, _, _ = make({TASK("t1"): [(200, {"status": status, "error": {"message": "boom"}})]})
    with pytest.raises(cloud.CloudError) as ei:
        c.wait_task("t1", total_timeout=10)
    assert ei.value.terminal is True and "boom" in str(ei.value)


def test_wait_times_out_with_actionable_message(monkeypatch):
    c, _, _ = make({TASK("t1"): [(200, {"status": "running"})]})
    t = [0.0]

    def fake_mono():
        t[0] += 30
        return t[0]

    monkeypatch.setattr(cloud.time, "monotonic", fake_mono)
    with pytest.raises(cloud.CloudError) as ei:
        c.wait_task("t1", total_timeout=5, interval=0)
    assert "不会重新提交" in str(ei.value) and ei.value.retryable is True


def test_task_id_is_url_quoted():
    c, http, _ = make({TASK("a%2Fb"): [DONE]})
    c.wait_task("a/b", total_timeout=10)
    assert http.calls[0]["path"].endswith("/api/v1/tasks/a%2Fb")


# ---------------------------------------------------------------- transcribe：落盘与续查（GL-15/16）
def test_backend_is_http_so_old_cli_state_is_invalidated():
    assert cloud.BACKEND != "mediakit-cli"


def test_old_cli_backend_state_is_not_resumed(tmp_path):
    wav = _wav(tmp_path)
    asr_state.save(tmp_path, wav, "mediakit-cli", "old-cli-task")
    c, http, _ = make(ROUTES)
    c.transcribe(wav, tmp_path)
    assert http.count(SUBMIT) == 1
    assert not any("old-cli-task" in call["path"] for call in http.calls)


def test_transcribe_writes_raw_and_clears_state(tmp_path):
    wav = _wav(tmp_path)
    c, _, _ = make(ROUTES)
    c.transcribe(wav, tmp_path)
    raw = json.loads((tmp_path / "transcript_raw.json").read_text(encoding="utf-8"))
    assert raw["status"] == "completed" and raw["subtitles"] == []
    assert not (tmp_path / "asr_task.json").exists()


def test_transcribe_failure_recorded_without_secrets(tmp_path):
    wav = _wav(tmp_path)
    leak = f"<Error>SignatureDoesNotMatch https://tos.x/o?X-Tos-Signature={SIG} {KEY}</Error>"
    c, _, _ = make(ROUTES, uploads=[(403, leak)], retries=1)
    with pytest.raises(cloud.CloudError) as ei:
        c.transcribe(wav, tmp_path)
    assert SIG not in str(ei.value) and KEY not in str(ei.value)
    text = (tmp_path / "failed.json").read_text(encoding="utf-8")
    assert json.loads(text)[-1]["stage"] == "asr"
    assert SIG not in text and KEY not in text


def test_transcribe_resumes_from_saved_task(tmp_path):
    wav = _wav(tmp_path)
    asr_state.save(tmp_path, wav, cloud.BACKEND, "saved-task")
    c, http, ups = make({TASK("saved-task"): [(200, {"status": "completed"})]})
    c.transcribe(wav, tmp_path)
    assert [(x["method"], x["path"]) for x in http.calls] == [TASK("saved-task")]
    assert ups == []
    assert not (tmp_path / "asr_task.json").exists()


def test_legacy_state_without_fingerprint_resubmits(tmp_path):
    wav = _wav(tmp_path)
    (tmp_path / "asr_task.json").write_text(
        json.dumps({"task_id": "saved-task", "at": 9e9}), encoding="utf-8")
    c, http, _ = make(ROUTES)
    c.transcribe(wav, tmp_path)
    assert http.count(SUBMIT) == 1


def test_failed_task_clears_state_then_resubmits(tmp_path):
    wav = _wav(tmp_path)
    failed = (200, {"status": "failed", "error": {"message": "boom"}})
    c, _, _ = make({**ROUTES, TASK("t1"): [failed]})
    with pytest.raises(cloud.CloudError) as ei:
        c.transcribe(wav, tmp_path)
    assert ei.value.retryable is False
    assert not (tmp_path / "asr_task.json").exists()  # 终态失败：下次重新提交
    c2, http2, _ = make({**ROUTES, SUBMIT: [ok_task("t2")], TASK("t2"): [DONE]})
    c2.transcribe(wav, tmp_path)
    assert http2.count(SUBMIT) == 1


def test_timeout_keeps_state_for_resume(tmp_path, monkeypatch):
    wav = _wav(tmp_path)
    c, _, _ = make({**ROUTES, TASK("t1"): [(200, {"status": "running"})]})
    t = [0.0]

    def fake_mono():
        t[0] += 10_000
        return t[0]

    monkeypatch.setattr(cloud.time, "monotonic", fake_mono)
    with pytest.raises(cloud.CloudError) as ei:
        c.transcribe(wav, tmp_path)
    assert ei.value.retryable is True
    assert asr_state.load(tmp_path, wav, cloud.BACKEND) == "t1"


def test_network_exhaustion_while_polling_keeps_state(tmp_path):
    wav = _wav(tmp_path)
    net = cloud.CloudError("网络错误：connection reset by peer", retryable=True)
    c, _, _ = make({**ROUTES, TASK("t1"): [net]}, retries=1)
    with pytest.raises(cloud.CloudError) as ei:
        c.transcribe(wav, tmp_path)
    assert ei.value.retryable is True
    assert asr_state.load(tmp_path, wav, cloud.BACKEND) == "t1"


def test_changed_audio_resubmits(tmp_path):
    wav = _wav(tmp_path)
    asr_state.save(tmp_path, wav, cloud.BACKEND, "old-task")
    wav.write_bytes(b"RIFF-other")
    c, http, _ = make(ROUTES)
    c.transcribe(wav, tmp_path)
    assert http.count(SUBMIT) == 1
    assert not any("old-task" in x["path"] for x in http.calls)


def test_transcript_raw_written_atomically(tmp_path, monkeypatch):
    # GL-15：aicut 以 transcript_raw.json「存在」判转写完成，写到一半被杀不能留下半截文件
    import os
    wav = _wav(tmp_path)
    c, _, _ = make(ROUTES)
    monkeypatch.setattr(c, "wait_task", lambda *a, **k: {"subtitles": []})
    real_replace = os.replace

    def killed(src, dst, *a, **k):
        if "transcript_raw" in str(dst):
            raise OSError("killed")
        return real_replace(src, dst, *a, **k)
    monkeypatch.setattr(os, "replace", killed)
    with pytest.raises(OSError):
        c.transcribe(wav, tmp_path)
    assert [p.name for p in tmp_path.iterdir() if "transcript_raw" in p.name] == []


def _saved(tmp_path):
    wav = _wav(tmp_path)
    asr_state.save(tmp_path, wav, cloud.BACKEND, "saved-task")
    return wav


def test_auth_failure_while_polling_keeps_state(tmp_path):
    wav = _saved(tmp_path)
    c, _, _ = make({TASK("saved-task"): [(401, "Unauthorized")]})
    with pytest.raises(cloud.CloudError) as ei:
        c.transcribe(wav, tmp_path)
    assert ei.value.terminal is False
    assert asr_state.load(tmp_path, wav, cloud.BACKEND) == "saved-task"


def test_non_json_response_keeps_state(tmp_path):
    wav = _saved(tmp_path)
    c, _, _ = make({TASK("saved-task"): [(200, "<html>gateway</html>")]})
    with pytest.raises(cloud.CloudError):
        c.transcribe(wav, tmp_path)
    assert asr_state.load(tmp_path, wav, cloud.BACKEND) == "saved-task"


# ---------------------------------------------------------------- 上传缓存（work/asr_upload.json）
def test_upload_reused_within_ttl(tmp_path):
    wav = _wav(tmp_path)
    c, http, ups = make({**ROUTES, SUBMIT: [(500, "x"), (400, {"message": "nope"})]}, retries=0)
    with pytest.raises(cloud.CloudError):
        c.transcribe(wav, tmp_path)          # 上传成功、提交失败
    assert (tmp_path / cloud.UPLOAD_CACHE).exists()
    c2, http2, ups2 = make(ROUTES)
    c2.transcribe(wav, tmp_path)
    assert ups2 == [] and http2.count(UPLOAD) == 0
    assert http2.bodies(SUBMIT)[0]["audio_url"] == "mediakit://F1"


def test_upload_cache_ignored_when_audio_changes(tmp_path):
    wav = _wav(tmp_path)
    c, _, _ = make({**ROUTES, SUBMIT: [(400, {"message": "nope"})]})
    with pytest.raises(cloud.CloudError):
        c.transcribe(wav, tmp_path)
    wav.write_bytes(b"RIFF-different-audio")
    c2, http2, ups2 = make(ROUTES)
    c2.transcribe(wav, tmp_path)
    assert len(ups2) == 1 and http2.count(UPLOAD) == 1


def test_upload_cache_ignored_when_expired_or_other_key(tmp_path, monkeypatch):
    wav = _wav(tmp_path)
    c, _, _ = make({**ROUTES, SUBMIT: [(400, {"message": "nope"})]})
    with pytest.raises(cloud.CloudError):
        c.transcribe(wav, tmp_path)
    c2, _, ups2 = make(ROUTES, api_key="AKLTanotherkey99999")
    c2.submit_asr(wav, workdir=tmp_path)
    assert len(ups2) == 1                    # 换了 Key：别人的 file_id 不能用
    real = cloud.time.time
    monkeypatch.setattr(cloud.time, "time", lambda: real() + cloud.UPLOAD_TTL_S + 60)
    c3, _, ups3 = make(ROUTES, api_key="AKLTanotherkey99999")
    c3.submit_asr(wav, workdir=tmp_path)
    assert len(ups3) == 1                    # 过期：重新上传


def test_upload_cache_never_stores_key_or_signed_url(tmp_path):
    wav = _wav(tmp_path)
    c, _, _ = make({**ROUTES, SUBMIT: [(400, {"message": "nope"})]})
    with pytest.raises(cloud.CloudError):
        c.transcribe(wav, tmp_path)
    text = (tmp_path / cloud.UPLOAD_CACHE).read_text(encoding="utf-8")
    assert KEY not in text and SIG not in text and "upload_url" not in text


def test_upload_cache_cleared_after_success(tmp_path):
    wav = _wav(tmp_path)
    c, _, _ = make(ROUTES)
    c.transcribe(wav, tmp_path)
    assert not (tmp_path / cloud.UPLOAD_CACHE).exists()


def test_corrupt_upload_cache_is_ignored(tmp_path):
    wav = _wav(tmp_path)
    (tmp_path / cloud.UPLOAD_CACHE).write_text("{not json", encoding="utf-8")
    c, _, ups = make(ROUTES)
    c.transcribe(wav, tmp_path)
    assert len(ups) == 1


# ---------------------------------------------------------------- 默认传输层：不出网
def test_default_upload_sets_content_length(tmp_path, monkeypatch):
    wav = _wav(tmp_path, body=b"x" * 1234)
    seen = {}

    class Resp:
        status = 200

        def read(self, n=-1):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen["len"] = req.get_header("Content-length")
        seen["auth"] = req.get_header("Authorization")
        seen["method"] = req.get_method()
        return Resp()

    monkeypatch.setattr(cloud, "_open", fake_urlopen)
    assert cloud.default_upload("PUT", "https://tos.x/o?s=1", {"Content-Type": "audio/wav"},
                                wav, 5) == (200, "")
    assert seen == {"len": "1234", "auth": None, "method": "PUT"}


def test_default_transport_network_error_is_retryable_and_redacted(monkeypatch):
    import urllib.error

    def boom(req, timeout):
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(cloud, "_open", boom)
    with pytest.raises(cloud.CloudError) as ei:
        cloud.default_transport("GET", "https://x/api", {"Authorization": f"Bearer {KEY}"},
                                None, 5)
    assert ei.value.retryable is True and KEY not in str(ei.value)


def test_no_subprocess_in_cloud_module():
    src = Path(cloud.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in src


# ---------------------------------------------------------------- 审查修复（HIGH）
def test_lost_submit_response_resubmits_with_same_client_token(tmp_path):
    # 提交其实成功、响应丢了：重跑必须用同一个 client_token，云端去重，不重复计费
    wav = _wav(tmp_path)
    c, http, _ = make({**ROUTES, SUBMIT: [(503, "lost")]}, retries=1)
    with pytest.raises(cloud.CloudError) as ei:
        c.transcribe(wav, tmp_path)
    assert ei.value.retryable is True
    c2, http2, _ = make(ROUTES)
    c2.transcribe(wav, tmp_path)
    first = {b["client_token"] for b in http.bodies(SUBMIT)}
    assert {b["client_token"] for b in http2.bodies(SUBMIT)} == first and len(first) == 1
    assert not (tmp_path / cloud.SUBMIT_TOKEN_FILE).exists()  # 成功后用完即弃


def test_terminal_failure_gets_fresh_client_token(tmp_path):
    wav = _wav(tmp_path)
    c, http, _ = make({**ROUTES, TASK("t1"): [(200, {"status": "failed"})]})
    with pytest.raises(cloud.CloudError):
        c.transcribe(wav, tmp_path)
    c2, http2, _ = make(ROUTES)
    c2.transcribe(wav, tmp_path)
    assert http.bodies(SUBMIT)[0]["client_token"] != http2.bodies(SUBMIT)[0]["client_token"]


def test_http_client_exceptions_become_retryable_cloud_errors(monkeypatch):
    import http.client

    def boom(req, timeout):
        raise http.client.IncompleteRead(b"x")
    monkeypatch.setattr(cloud, "_open", boom)
    with pytest.raises(cloud.CloudError) as ei:
        cloud.default_transport("GET", "https://x/api", {}, None, 5)
    assert ei.value.retryable is True


def test_redirect_is_not_followed_and_is_an_error(tmp_path):
    c, http, _ = make({**ROUTES, SUBMIT: [(302, "")]})
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert "302" in str(ei.value) and http.count(SUBMIT) == 1


def test_default_opener_refuses_redirects():
    import urllib.request
    handlers = [h for h in cloud._OPENER.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert handlers and all(h.redirect_request(None, None, 302, "", {}, "https://evil/") is None
                            for h in handlers)


def test_task_not_found_is_terminal(tmp_path):
    wav = _saved(tmp_path)
    c, _, _ = make({TASK("saved-task"): [(404, {"message": "task not found"})]})
    with pytest.raises(cloud.CloudError) as ei:
        c.transcribe(wav, tmp_path)
    assert ei.value.terminal is True
    assert asr_state.load(tmp_path, wav, cloud.BACKEND) is None


def test_key_with_control_chars_rejected_without_leaking(tmp_path):
    c, http, _ = make(ROUTES, api_key="AKLTsecret\nkey123456")
    with pytest.raises(cloud.CloudError) as ei:
        c.submit_asr(_wav(tmp_path))
    assert "secret" not in str(ei.value) and http.calls == []


def test_upload_without_content_type_gets_octet_stream(tmp_path, monkeypatch):
    seen = {}

    class Resp:
        status = 200

        def read(self, n=-1):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(req, timeout):
        seen["ctype"] = req.get_header("Content-type")
        return Resp()
    monkeypatch.setattr(cloud, "_open", fake_open)
    cloud.default_upload("PUT", "https://tos.x/o", {}, _wav(tmp_path), 5)
    assert seen["ctype"] == "application/octet-stream"

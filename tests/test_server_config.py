"""M4 · GL-02：剪辑台的 Key 设置、数据外发告知、处理素材前置拦截；Key 绝不外泄。"""
import json
import sys

import pytest

from conftest import call, make_project

MK = "AKLTabcdefghij9f2a"
DS = "sk-deepseek-secret-123"


@pytest.fixture
def gs(gui_server, no_keys):
    return gui_server


def get_cfg(gs):
    status, body, _ = call(gs, "GET", "/api/config")
    assert status == 200
    return json.loads(body)


def post(gs, path, body):
    status, raw, _ = call(gs, "POST", path, body)
    return status, raw.decode("utf-8"), json.loads(raw)


def test_config_initially_unconsented_and_unconfigured(gs):
    cfg = get_cfg(gs)
    assert cfg["consent"] is False
    assert [p["key"] for p in cfg["providers"]] == ["mediakit", "deepseek"]
    for p in cfg["providers"]:
        assert p["configured"] is False and p["label"] and p["hint"]


def test_consent_endpoint_records_acceptance(gs):
    status, _, data = post(gs, "/api/config/consent", {})
    assert status == 200 and data["consent"] is True
    assert get_cfg(gs)["consent"] is True


def test_set_key_returns_masked_only(gs, no_keys):
    status, text, data = post(gs, "/api/config/key", {"provider": "mediakit", "value": f"  {MK} "})
    assert status == 200
    assert MK not in text and "****9f2a" in text  # KI-67 新掩码
    assert no_keys.get("mediakit") == MK  # 首尾空白去掉后保存


@pytest.mark.parametrize("body", [
    {"provider": "mediakit", "value": "has space inside"},
    {"provider": "mediakit", "value": "short"},
    {"provider": "mediakit", "value": ""},
    {"provider": "mediakit", "value": "x" * 513},
    {"provider": "mediakit", "value": 12345678},
    {"provider": "mediakit", "value": "密钥密钥密钥密钥"},
    {"provider": "openai", "value": MK},
    {"provider": ["mediakit"], "value": MK},
])
def test_reject_bad_key(gs, no_keys, body):
    status, text, _ = post(gs, "/api/config/key", body)
    assert status == 400
    assert no_keys.get("mediakit") is None
    if isinstance(body.get("value"), str) and len(body["value"]) > 3:
        assert body["value"] not in text  # 错误信息也不回显输入


def test_keychain_failure_is_500_without_echo(gs, monkeypatch):
    from pipeline import secrets

    def boom(provider, value):
        raise RuntimeError(f"keychain refused {value}")

    monkeypatch.setattr(secrets, "set", boom)
    status, text, _ = post(gs, "/api/config/key", {"provider": "deepseek", "value": DS})
    assert status == 500 and DS not in text


def test_delete_key(gs, no_keys):
    post(gs, "/api/config/key", {"provider": "deepseek", "value": DS})
    status, _, data = post(gs, "/api/config/key/delete", {"provider": "deepseek"})
    assert status == 200
    assert no_keys.get("deepseek") is None
    assert {p["key"]: p["configured"] for p in data["providers"]}["deepseek"] is False
    assert post(gs, "/api/config/key/delete", {"provider": "nope"})[0] == 400


def test_env_key_reported_as_env_source(gs, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", DS)
    cfg = get_cfg(gs)
    ds = next(p for p in cfg["providers"] if p["key"] == "deepseek")
    assert ds["configured"] and ds["source"] == "env" and DS not in json.dumps(cfg)


def _fake_job(gs, monkeypatch):
    from gui import jobs
    monkeypatch.setattr(jobs, "job_command",
                        lambda *a: [sys.executable, "-c", f"print('running with {MK[:4]}')"])


def test_prepare_blocked_until_consent_and_keys(gs, monkeypatch):
    make_project(gs.root)
    _fake_job(gs, monkeypatch)
    status, _, data = post(gs, "/api/job", {"project": "p1", "task": "prepare"})
    assert status == 409 and data["need"] == "consent"
    post(gs, "/api/config/consent", {})
    status, _, data = post(gs, "/api/job", {"project": "p1", "task": "prepare"})
    assert status == 409 and data["need"] == "keys"
    assert data["missing"] == ["mediakit", "deepseek"]
    assert "语音转写" in data["error"] and "文本分析" in data["error"]
    post(gs, "/api/config/key", {"provider": "mediakit", "value": MK})
    status, _, data = post(gs, "/api/job", {"project": "p1", "task": "prepare"})
    assert status == 409 and data["missing"] == ["deepseek"]  # 不许跳过文本分析
    post(gs, "/api/config/key", {"provider": "deepseek", "value": DS})
    status, _, data = post(gs, "/api/job", {"project": "p1", "task": "prepare"})
    assert status == 200 and data["job_id"]
    assert not gs.module.JOBS or all(j["task"] == "prepare" for j in gs.module.JOBS.values())


def test_blocked_prepare_leaves_no_job(gs, monkeypatch):
    make_project(gs.root)
    _fake_job(gs, monkeypatch)
    post(gs, "/api/job", {"project": "p1", "task": "prepare"})
    assert gs.module.JOBS == {}


def test_transcribed_project_needs_only_deepseek(gs, monkeypatch):
    make_project(gs.root, **{"work/transcript_raw.json": "{}"})
    _fake_job(gs, monkeypatch)
    post(gs, "/api/config/consent", {})
    post(gs, "/api/config/key", {"provider": "deepseek", "value": DS})
    status, _, _ = post(gs, "/api/job", {"project": "p1", "task": "prepare"})
    assert status == 200


def test_other_tasks_not_blocked_by_consent(gs, monkeypatch):
    make_project(gs.root)
    _fake_job(gs, monkeypatch)
    status, _, _ = post(gs, "/api/job", {"project": "p1", "task": "build"})
    assert status == 200


def test_key_never_written_to_project_or_log(gs, monkeypatch):
    from gui import jobs
    pdir = make_project(gs.root)
    _fake_job(gs, monkeypatch)
    post(gs, "/api/config/consent", {})
    post(gs, "/api/config/key", {"provider": "mediakit", "value": MK})
    post(gs, "/api/config/key", {"provider": "deepseek", "value": DS})
    status, _, data = post(gs, "/api/job", {"project": "p1", "task": "prepare"})
    import time
    deadline = time.time() + 10
    while jobs.active_job() and time.time() < deadline:
        time.sleep(0.05)
    for f in pdir.rglob("*"):
        if f.is_file():
            text = f.read_text(encoding="utf-8", errors="replace")
            assert MK not in text and DS not in text
    blob = json.dumps(jobs.JOBS, default=str, ensure_ascii=False)
    assert MK not in blob and DS not in blob
    state = call(gs, "GET", "/api/state?project=p1")[1].decode("utf-8")
    assert MK not in state and DS not in state


def test_delete_failure_is_500_with_clear_message(gs, monkeypatch):
    from pipeline import secrets

    def boom(provider):
        raise secrets.SecretDeleteError("钥匙串里的 Key 没删掉")

    monkeypatch.setattr(secrets, "delete", boom)
    status, text, data = post(gs, "/api/config/key/delete", {"provider": "deepseek"})
    assert status == 500 and "清除失败" in data["error"]

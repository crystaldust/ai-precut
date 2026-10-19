"""M4 · GL-16：ASR 断点续查状态绑定 schema 版本 + backend + 音频指纹，过期/损坏即作废。"""
import json

import pytest

from pipeline import asr_state


@pytest.fixture
def audio(tmp_path):
    wav = tmp_path / "asr.wav"
    wav.write_bytes(b"RIFF" + b"\x01" * 100)
    return wav


def state_file(tmp_path):
    return tmp_path / "work" / asr_state.FILENAME


def test_save_then_load_roundtrip(tmp_path, audio):
    asr_state.save(tmp_path / "work", audio, "cli", "t1")
    assert asr_state.load(tmp_path / "work", audio, "cli") == "t1"
    data = json.loads(state_file(tmp_path).read_text(encoding="utf-8"))
    assert data["schema"] == asr_state.SCHEMA_VERSION and data["audio"]["size"] == 104


def test_changed_audio_invalidates_and_deletes(tmp_path, audio):
    asr_state.save(tmp_path / "work", audio, "cli", "t1")
    audio.write_bytes(b"RIFF" + b"\x02" * 100)  # 同样大小、不同内容
    assert asr_state.load(tmp_path / "work", audio, "cli") is None
    assert not state_file(tmp_path).exists()


def test_other_backend_invalidates(tmp_path, audio):
    asr_state.save(tmp_path / "work", audio, "cli", "t1")
    assert asr_state.load(tmp_path / "work", audio, "http") is None
    assert not state_file(tmp_path).exists()


def test_expired_state_invalidates(tmp_path, audio):
    asr_state.save(tmp_path / "work", audio, "cli", "t1", now=lambda: 1000.0)
    later = 1000.0 + asr_state.MAX_AGE_S + 1
    assert asr_state.load(tmp_path / "work", audio, "cli", now=lambda: later) is None
    assert not state_file(tmp_path).exists()


@pytest.mark.parametrize("content", ["{oops", "[]", json.dumps({"task_id": "t1", "at": 9e9}),
                                     json.dumps({"schema": 1, "backend": "cli", "task_id": "",
                                                 "audio": {}, "at": 9e9}),
                                     json.dumps({"schema": 1, "backend": "cli", "task_id": "t",
                                                 "audio": {}, "at": "nan?"})])
def test_corrupt_or_legacy_state_invalidates(tmp_path, audio, content):
    state_file(tmp_path).parent.mkdir(parents=True)
    state_file(tmp_path).write_text(content, encoding="utf-8")
    assert asr_state.load(tmp_path / "work", audio, "cli") is None
    assert not state_file(tmp_path).exists()


def test_missing_audio_invalidates(tmp_path, audio):
    asr_state.save(tmp_path / "work", audio, "cli", "t1")
    audio.unlink()
    assert asr_state.load(tmp_path / "work", audio, "cli") is None


def test_load_without_state_is_none(tmp_path, audio):
    assert asr_state.load(tmp_path / "work", audio, "cli") is None


def test_clear_is_idempotent(tmp_path):
    asr_state.clear(tmp_path / "nowhere")

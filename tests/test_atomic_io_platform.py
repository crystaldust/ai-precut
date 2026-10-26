# -*- coding: utf-8 -*-
"""原子写 / 目录 fsync 的 Windows 适配（M16 Task 4 / CI 修复）：
  * Windows 不能 os.open 一个目录再 fsync（EBADF / EACCES）→ 尽力而为的空操作；文件 fsync 要写句柄；
  * Windows 上 os.replace 遇到别的线程 / 进程正打开目标会 PermissionError → 有界重试，POSIX 路径不变。
Windows 分支在 Mac 上 monkeypatch plat.IS_WIN + 伪造 os.replace / os.open。"""
import os
import threading

import pytest

from pipeline import outputs, plat, schema, shots_store
from platform_marks import WIN_ONLY


@pytest.fixture
def as_windows(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", True)
    monkeypatch.setattr(schema.time, "sleep", lambda s: None)


def test_fsync_dir_is_a_noop_on_windows(as_windows, monkeypatch, tmp_path):
    monkeypatch.setattr(schema.os, "open", lambda *a, **k: pytest.fail("Windows 上不该打开目录"))
    schema.fsync_dir(tmp_path)


def test_fsync_dir_still_syncs_on_posix(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "IS_WIN", False)
    synced = []
    real = os.fsync
    monkeypatch.setattr(schema.os, "fsync", lambda fd: synced.append(fd) or real(fd))
    schema.fsync_dir(tmp_path)
    assert len(synced) == 1


def test_fsync_file_opens_for_write_on_windows(as_windows, monkeypatch, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    flags = []
    real = os.open
    monkeypatch.setattr(schema.os, "open", lambda p, fl, *a: flags.append(fl) or real(p, fl, *a))
    schema.fsync_file(f)
    assert flags == [os.O_RDWR]


def test_fsync_file_stays_readonly_on_posix(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "IS_WIN", False)
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    flags = []
    real = os.open
    monkeypatch.setattr(schema.os, "open", lambda p, fl, *a: flags.append(fl) or real(p, fl, *a))
    schema.fsync_file(f)
    assert flags == [os.O_RDONLY]


def test_shots_backup_survives_windows_directory_fsync_failure(as_windows, monkeypatch, tmp_path):
    pdir = tmp_path / "p"
    (pdir / "work").mkdir(parents=True)
    (pdir / shots_store.SHOTS_FILE).parent.mkdir(parents=True, exist_ok=True)
    (pdir / shots_store.SHOTS_FILE).write_text("{}", encoding="utf-8")
    real = os.open

    def picky(path, flags, *a):
        if os.path.isdir(path):
            raise PermissionError(13, "Access is denied")  # Windows 对目录 os.open 的真实表现
        return real(path, flags, *a)
    monkeypatch.setattr(schema.os, "open", picky)
    assert shots_store.backup(pdir, "t").is_file()


def test_shots_backup_on_posix_still_raises_when_directory_fsync_fails(monkeypatch, tmp_path):
    """只有 Windows 把目录 fsync 当空操作；POSIX 上失败照常抛（备份没落盘不能假装成功）。"""
    monkeypatch.setattr(plat, "IS_WIN", False)
    pdir = tmp_path / "p"
    (pdir / shots_store.SHOTS_FILE).parent.mkdir(parents=True)
    (pdir / shots_store.SHOTS_FILE).write_text("{}", encoding="utf-8")
    real = os.open

    def picky(path, flags, *a):
        if os.path.isdir(path):
            raise PermissionError(13, "Access is denied")
        return real(path, flags, *a)
    monkeypatch.setattr(schema.os, "open", picky)
    with pytest.raises(OSError):
        shots_store.backup(pdir, "t")


def test_outputs_uses_the_shared_helper():
    assert outputs.schema.fsync_dir is schema.fsync_dir


# ---------------------------------------------------------------- os.replace 重试
def _flaky_replace(monkeypatch, failures):
    real, calls = os.replace, []

    def fake(src, dst):
        calls.append(1)
        if len(calls) <= failures:
            raise PermissionError(13, "Access is denied")
        return real(src, dst)
    monkeypatch.setattr(schema.os, "replace", fake)
    return calls


def test_windows_replace_retries_permission_error(as_windows, monkeypatch, tmp_path):
    calls = _flaky_replace(monkeypatch, 3)
    schema.write_json(tmp_path / "a.json", {"k": 1})
    assert schema.read_json(tmp_path / "a.json") == {"k": 1} and len(calls) == 4
    assert not list(tmp_path.glob("*.tmp"))


def test_windows_replace_gives_up_after_bounded_retries(as_windows, monkeypatch, tmp_path):
    calls = _flaky_replace(monkeypatch, 10_000)
    with pytest.raises(PermissionError):
        schema.write_json(tmp_path / "a.json", {"k": 1})
    assert len(calls) == schema.REPLACE_ATTEMPTS
    assert not list(tmp_path.glob(".*.tmp"))  # 失败不留残渣


def test_posix_replace_does_not_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "IS_WIN", False)
    calls = _flaky_replace(monkeypatch, 10_000)
    with pytest.raises(PermissionError):
        schema.write_json(tmp_path / "a.json", {"k": 1})
    assert len(calls) == 1


def test_replace_only_retries_permission_errors(as_windows, monkeypatch, tmp_path):
    calls = []

    def fake(src, dst):
        calls.append(1)
        raise FileNotFoundError("gone")
    monkeypatch.setattr(schema.os, "replace", fake)
    with pytest.raises(FileNotFoundError):
        schema.write_json(tmp_path / "a.json", {})
    assert len(calls) == 1


@WIN_ONLY
def test_windows_concurrent_writers_and_readers_never_fail(tmp_path):
    """真实 Windows：读者打开目标时写者的 os.replace 会被拒，重试后必须全部成功。"""
    target, errors = tmp_path / "c.json", []
    schema.write_json(target, {"n": 0})

    def writer(i):
        try:
            for j in range(30):
                schema.write_json(target, {"n": i * 100 + j})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def reader():
        try:
            for _ in range(60):
                target.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)] + [threading.Thread(target=reader)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []

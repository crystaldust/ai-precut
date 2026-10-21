"""手动分镜表存储（M14 E7 / E9 / E11）：线程锁 + 跨进程文件锁、基线、覆盖前备份。"""
import json
import os
import stat
import threading
import time

import pytest

from pipeline import filelock, schema, shots_store


def _sh(i, a, b, sub="字幕"):
    return {"id": f"s{i}", "in": a, "out": b, "sub": sub}


AI = [_sh(1, 0, 10), _sh(2, 20, 30), _sh(3, 40, 50)]


def _project(tmp_path, *, ai=None, manual=None):
    pdir = tmp_path / "p"
    (pdir / "work").mkdir(parents=True)
    if ai is not None:
        (pdir / "work" / "shots-selected.json").write_text(json.dumps({"shots": ai}), encoding="utf-8")
    if manual is not None:
        (pdir / "shots.json").write_text(json.dumps({"shots": manual}), encoding="utf-8")
    return pdir


# ---------------------------------------------------------------- locked
def test_locked_creates_private_lock_file_and_serializes_threads(tmp_path):
    pdir = _project(tmp_path)
    order = []

    def worker(tag):
        with shots_store.locked(pdir):
            order.append(f"{tag}-in")
            time.sleep(0.05)
            order.append(f"{tag}-out")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert len(order) == 8
    assert all(order[i].split("-")[0] == order[i + 1].split("-")[0] for i in range(0, 8, 2))
    mode = stat.S_IMODE(os.stat(pdir / shots_store.FILE_LOCK).st_mode)
    assert mode == 0o600


def test_locked_blocks_while_another_open_file_holds_flock(tmp_path):
    """跨进程的等价物：flock 按打开的文件描述符算，另一个 fd 持锁时 locked() 必须等。"""
    pdir = _project(tmp_path)
    holder = os.open(pdir / shots_store.FILE_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    filelock.flock(holder, filelock.LOCK_EX)
    got = threading.Event()

    def worker():
        with shots_store.locked(pdir):
            got.set()

    t = threading.Thread(target=worker)
    t.start()
    assert not got.wait(0.3)
    filelock.flock(holder, filelock.LOCK_UN)
    os.close(holder)
    assert got.wait(5)
    t.join(5)


def test_locked_warns_and_proceeds_when_flock_unsupported(tmp_path, monkeypatch, caplog):
    pdir = _project(tmp_path)

    def boom(fd, op):
        raise OSError("not supported")
    monkeypatch.setattr(shots_store.filelock, "flock", boom)
    with caplog.at_level("WARNING"):
        with shots_store.locked(pdir):
            ran = True
    assert ran and any("不加锁" in r.getMessage() for r in caplog.records)
    assert not shots_store.thread_lock(pdir).locked()


# ---------------------------------------------------------------- current
def test_current_prefers_manual_then_selection_then_none(tmp_path):
    pdir = _project(tmp_path, ai=AI)
    assert shots_store.current(pdir) == (schema.clean_shots(AI), "selection")
    (pdir / "shots.json").write_text(json.dumps({"shots": AI[:1]}), encoding="utf-8")
    shots, source = shots_store.current(pdir)
    assert source == "manual" and [s["id"] for s in shots] == ["s1"]
    assert shots_store.current(_project(tmp_path / "x")) == ([], None)


def test_current_raises_on_corrupt_instead_of_treating_as_missing(tmp_path):
    pdir = _project(tmp_path, ai=AI)
    (pdir / "shots.json").write_text("{坏", encoding="utf-8")
    with pytest.raises(schema.CorruptJSON):
        shots_store.current(pdir)


# ---------------------------------------------------------------- write_manual / 基线
def test_first_write_saves_ai_selection_as_baseline_later_writes_keep_it(tmp_path):
    pdir = _project(tmp_path, ai=AI)
    shots_store.write_manual(pdir, schema.clean_shots(AI[:2]), {"project": "t"})
    base = json.loads((pdir / shots_store.BASE_FILE).read_text(encoding="utf-8"))
    assert [s["id"] for s in base["shots"]] == ["s1", "s2", "s3"] and base["at"]
    # AI 选段变了之后再存：基线不动（⚑Q5 / E7）
    (pdir / "work" / "shots-selected.json").write_text(json.dumps({"shots": [_sh(9, 0, 1)]}), encoding="utf-8")
    shots_store.write_manual(pdir, schema.clean_shots(AI[:1]), {"project": "t"})
    again = json.loads((pdir / shots_store.BASE_FILE).read_text(encoding="utf-8"))
    assert [s["id"] for s in again["shots"]] == ["s1", "s2", "s3"]
    assert json.loads((pdir / "shots.json").read_text(encoding="utf-8"))["project"] == "t"


def test_first_write_without_ai_selection_uses_empty_baseline(tmp_path):
    pdir = _project(tmp_path)
    shots_store.write_manual(pdir, schema.clean_shots(AI[:1]), {})
    assert json.loads((pdir / shots_store.BASE_FILE).read_text(encoding="utf-8"))["shots"] == []


# ---------------------------------------------------------------- backup / drop
def test_drop_manual_backs_up_then_deletes_shots_and_baseline(tmp_path):
    pdir = _project(tmp_path, ai=AI)
    shots_store.write_manual(pdir, schema.clean_shots(AI[:2]), {})
    original = (pdir / "shots.json").read_bytes()
    backup = shots_store.drop_manual(pdir, "replace")
    assert backup is not None and backup.read_bytes() == original
    assert backup.parent == pdir / shots_store.BACKUP_DIR and backup.name.endswith("-replace.json")
    assert not (pdir / "shots.json").exists() and not (pdir / shots_store.BASE_FILE).exists()


def test_drop_manual_without_shots_json_does_nothing(tmp_path):
    pdir = _project(tmp_path, ai=AI)
    assert shots_store.drop_manual(pdir, "replace") is None
    assert not (pdir / shots_store.BACKUP_DIR).exists()


def test_backup_keeps_only_latest_ten(tmp_path, monkeypatch):
    pdir = _project(tmp_path, manual=AI)
    ticks = iter(range(100))
    monkeypatch.setattr(shots_store, "_utc_stamp", lambda: f"20260101T0000{next(ticks):02d}Z")
    for _ in range(12):
        shots_store.backup(pdir, "restore-ai")
    names = sorted(p.name for p in (pdir / shots_store.BACKUP_DIR).iterdir())
    assert len(names) == shots_store.BACKUP_KEEP == 10
    assert names[0].startswith("000003-") and names[-1].startswith("000012-")


def test_backup_same_second_does_not_overwrite(tmp_path, monkeypatch):
    pdir = _project(tmp_path, manual=AI)
    monkeypatch.setattr(shots_store, "_utc_stamp", lambda: "20260101T000000Z")
    a = shots_store.backup(pdir, "replace")
    b = shots_store.backup(pdir, "replace")
    assert a != b and a.exists() and b.exists()


def test_backup_preserves_corrupt_file_bytes(tmp_path):
    pdir = _project(tmp_path)
    (pdir / "shots.json").write_text("{坏", encoding="utf-8")
    assert shots_store.backup(pdir, "replace").read_text(encoding="utf-8") == "{坏"


# ---------------------------------------------------------------- manual_changes
def test_manual_changes_none_when_no_manual_table(tmp_path):
    pdir = _project(tmp_path, ai=AI)
    assert shots_store.manual_changes(pdir) == {"edited": False, "count": 0, "changes": [], "more": 0}


def test_manual_changes_identical_to_ai_is_not_edited(tmp_path):
    pdir = _project(tmp_path, ai=AI)
    shots_store.write_manual(pdir, schema.clean_shots(AI), {})
    assert shots_store.manual_changes(pdir)["edited"] is False


def test_manual_changes_counts_against_baseline_not_new_ai_selection(tmp_path):
    pdir = _project(tmp_path, ai=AI)
    edited = schema.clean_shots([AI[0], {**AI[1], "sub": "改了"}, AI[2]])
    shots_store.write_manual(pdir, edited, {})
    (pdir / "work" / "shots-selected.json").write_text(json.dumps({"shots": [_sh(7, 500, 510)]}), encoding="utf-8")
    res = shots_store.manual_changes(pdir)
    assert res["edited"] is True and res["count"] == 1
    assert res["changes"] == ["第 2 镜改了字幕"] and res["more"] == 0


def test_manual_changes_without_baseline_compares_to_current_ai(tmp_path):
    pdir = _project(tmp_path, ai=AI, manual=[AI[0]])  # 旧项目：没有基线文件
    res = shots_store.manual_changes(pdir)
    assert res["count"] == 2 and res["edited"] is True


def test_manual_changes_limit_and_more(tmp_path):
    pdir = _project(tmp_path, ai=AI, manual=[])
    res = shots_store.manual_changes(pdir, limit=2)
    assert len(res["changes"]) == 2 and res["more"] == 1 and res["count"] == 3


def test_manual_changes_never_raises_on_corrupt(tmp_path):
    pdir = _project(tmp_path, ai=AI)
    (pdir / "shots.json").write_text("{坏", encoding="utf-8")
    res = shots_store.manual_changes(pdir)
    assert res["edited"] is False and res["error"]


# ---------------------------------------------------------------- 不丢编辑（并发）
def test_concurrent_save_and_replace_never_lose_an_edit(tmp_path):
    """保存（GUI）与覆盖（aicut select --manual=replace）竞争：保存的内容要么还在 shots.json，要么在备份里。"""
    for round_no in range(20):
        pdir = _project(tmp_path / f"r{round_no}", ai=AI, manual=AI[:2])
        mark = f"编辑{round_no}"
        edit = schema.clean_shots([{**AI[0], "sub": mark}])

        def save():
            with shots_store.locked(pdir):
                shots_store.write_manual(pdir, edit, {})

        def replace():
            with shots_store.locked(pdir):
                shots_store.drop_manual(pdir, "replace")

        t1, t2 = threading.Thread(target=save), threading.Thread(target=replace)
        t1.start(); t2.start(); t1.join(5); t2.join(5)  # noqa: E702
        kept = (pdir / "shots.json").exists() and mark in (pdir / "shots.json").read_text(encoding="utf-8")
        backed = any(mark in p.read_text(encoding="utf-8")
                     for p in (pdir / shots_store.BACKUP_DIR).glob("*.json"))
        assert kept or backed, round_no


# ---------------------------------------------------------------- MEDIUM-6/7：每项目一把线程锁、有限等待、备份顺序与落盘
def _hold_flock_in_subprocess(pdir):
    import subprocess
    import sys
    root = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    code = ("import os, sys; sys.path.insert(0, %r)\n"
            "from pipeline import filelock\n"
            "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
            "filelock.flock(fd, filelock.LOCK_EX)\n"
            "print('ready', flush=True)\n"
            "sys.stdin.readline()\n" % root)
    p = subprocess.Popen([sys.executable, "-c", code, str(pdir / shots_store.FILE_LOCK)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ready"
    return p


def _release(p):
    p.stdin.write("\n")
    p.stdin.flush()
    p.wait(10)


def test_thread_lock_is_per_project(tmp_path):
    a, b = _project(tmp_path / "a"), _project(tmp_path / "b")
    assert shots_store.thread_lock(a) is shots_store.thread_lock(a / ".." / "p")
    assert shots_store.thread_lock(a) is not shots_store.thread_lock(b)
    with shots_store.locked(a):
        got = threading.Event()

        def other():
            with shots_store.locked(b):
                got.set()
        t = threading.Thread(target=other)
        t.start()
        assert got.wait(2)                                 # 别的项目不被挡
        t.join(5)


def test_locked_waits_for_another_process_then_proceeds(tmp_path):
    pdir = _project(tmp_path)
    holder = _hold_flock_in_subprocess(pdir)
    got = threading.Event()

    def worker():
        with shots_store.locked(pdir):
            got.set()
    t = threading.Thread(target=worker)
    t.start()
    try:
        assert not got.wait(0.5)                           # 另一个进程持锁：等
    finally:
        _release(holder)
    assert got.wait(5)
    t.join(5)


def test_locked_raises_busy_after_bounded_wait(tmp_path, monkeypatch):
    pdir = _project(tmp_path)
    monkeypatch.setattr(shots_store, "BUSY_TIMEOUT_S", 0.3)
    holder = _hold_flock_in_subprocess(pdir)
    try:
        with pytest.raises(shots_store.Busy):
            with shots_store.locked(pdir):
                pytest.fail("不该拿到锁")
        assert not shots_store.thread_lock(pdir).locked()   # 线程锁已释放
    finally:
        _release(holder)
    with shots_store.locked(pdir):                          # 对方放开后恢复正常
        pass


def test_locked_raises_busy_when_thread_lock_held_too_long(tmp_path, monkeypatch):
    pdir = _project(tmp_path)
    monkeypatch.setattr(shots_store, "BUSY_TIMEOUT_S", 0.2)
    with shots_store.locked(pdir):
        result = []

        def other():
            try:
                with shots_store.locked(pdir):
                    result.append("got")
            except shots_store.Busy:
                result.append("busy")
        t = threading.Thread(target=other)
        t.start()
        t.join(5)
    assert result == ["busy"]


def test_backup_is_fsynced(tmp_path, monkeypatch):
    pdir = _project(tmp_path, manual=AI)
    synced = []
    real = os.fsync
    monkeypatch.setattr(shots_store.os, "fsync", lambda fd: synced.append(fd) or real(fd))
    shots_store.backup(pdir, "replace")
    assert len(synced) >= 2                                 # 备份文件 + 目录


def test_backup_prune_uses_sequence_not_string_order(tmp_path, monkeypatch):
    """时钟回拨 / 同秒多份：按单调序号裁剪，永远留下最新的 10 份。"""
    pdir = _project(tmp_path, manual=AI)
    stamps = iter(["29990101T000000Z"] + ["20260101T000000Z"] * 14)   # 第一份时间戳「最大」
    monkeypatch.setattr(shots_store, "_utc_stamp", lambda: next(stamps))
    for _ in range(12):
        shots_store.backup(pdir, "restore-ai")
    seqs = sorted(int(p.name.split("-", 1)[0]) for p in (pdir / shots_store.BACKUP_DIR).iterdir())
    assert seqs == list(range(3, 13))


def test_drop_manual_does_not_delete_when_backup_fails(tmp_path, monkeypatch):
    pdir = _project(tmp_path, ai=AI, manual=AI[:2])

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(shots_store.shutil, "copyfile", boom)
    with pytest.raises(OSError):
        shots_store.drop_manual(pdir, "replace")
    assert (pdir / "shots.json").exists()

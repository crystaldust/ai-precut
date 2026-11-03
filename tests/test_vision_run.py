"""画面理解第 3 阶段：编排（pipeline/vision_run.py）。假 ffmpeg、假云端，不发真实请求。"""
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import cloud, media_io, usage, vision, vision_run, vision_timeline

ON = {"vision": {"enabled": True, "tier": "economy"}}


def answer(*spans):
    return json.dumps({"events": [{"start": a, "end": b, "action": "x"} for a, b in spans]})


class FakeClient:
    """按段（由 file_id 推回）给结果；记录每次调用。"""

    def __init__(self, contents=None, *, wait_error=None, submit_error=None):
        self.key_id = lambda: "acct"
        self.api_key = "AKLTkey"
        self.contents = contents or {}
        self.wait_error = wait_error or {}
        self.submit_error = submit_error or {}
        self.uploads, self.submits, self.waits = [], [], []
        self._lock = threading.Lock()
        self._n = 0

    def upload(self, path, *, tool, label):
        with self._lock:
            self.uploads.append((Path(path).name, tool, label))
        return f"mediakit://{Path(path).stem}"

    def submit_tool(self, tool, payload):
        idx = int(payload["video_urls"][0].rsplit("_", 1)[1])
        with self._lock:
            self.submits.append((tool, payload))
            self._n += 1
            if (err := self.submit_error.get(idx)) and err:
                raise self.submit_error[idx].pop(0) if isinstance(err, list) else err
            return f"task{idx}-{self._n}"

    def wait_task(self, task_id, total_timeout, interval=10.0):
        idx = int(task_id[4:].split("-")[0])
        with self._lock:
            self.waits.append(task_id)
            if idx in self.wait_error:
                raise self.wait_error[idx]
            seq = self.contents.get(idx) or [answer((0, 100), (100, 300))]
            text = seq.pop(0) if len(seq) > 1 else seq[0]
        return {"status": "completed", "contents": [text],
                "token_usage": {"input_tokens": 90, "output_tokens": 10, "total_tokens": 100}}


def runner(cmd, **kw):
    Path(cmd[-1]).write_bytes(b"clip")
    return SimpleNamespace(returncode=0, stderr="")


@pytest.fixture
def work(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    (w / "proxy.mp4").write_bytes(b"proxy")
    monkeypatch.setattr(vision_run.media_io, "duration_or_zero", lambda p, **k: 610.0)
    monkeypatch.setattr(vision_run.vision_proxy.encode, "encoder", lambda: "h264_videotoolbox")
    return w


def go(work, client, cfg=ON, **kw):
    return vision_run.run(work, cfg, work / "proxy.mp4", client_factory=lambda: client,
                          runner=runner, **kw)


def timeline(work):
    return json.loads((work / vision_run.TIMELINE_FILE).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 主流程
def test_off_does_nothing(work):
    made = []
    out = vision_run.run(work, {}, work / "proxy.mp4", client_factory=lambda: made.append(1),
                         runner=runner)
    assert out == {"skipped": True} and made == []
    assert not (work / "vision").exists() and not (work / vision_run.TIMELINE_FILE).exists()


def test_full_run_writes_timeline_ledger_and_cleans_clips(work):
    c = FakeClient()
    out = go(work, c)
    assert sorted(u[0] for u in c.uploads) == ["chunk_000.mp4", "chunk_001.mp4"]
    assert {u[1] for u in c.uploads} == {"video-understand-router"} and c.uploads[0][2] == "画面"
    assert len(c.submits) == 2
    tool, payload = c.submits[0]
    assert tool == "video-understand-router"
    assert payload["prompt"] == vision_timeline.PROMPT
    assert payload["manual_option"] == {"fps": 2.0, "need_audio": False}
    assert "level" not in payload and "client_token" not in payload
    tl = timeline(work)
    assert out["events"] == tl["events"]
    assert tl["setting"] == {"enabled": True, "tier": "economy"} and tl["duration"] == 610.0
    assert [(e["start"], e["end"]) for e in tl["events"]] == \
        [(0.0, 100.0), (100.0, 300.0), (300.0, 400.0), (400.0, 600.0)]
    assert tl["usage"] == {"total_tokens": 200}
    assert usage.vision_tokens(work) == 200
    assert not list((work / "vision").glob("*.mp4")) and not list((work / "vision").glob("*.done"))
    assert (work / "vision" / "chunk_000.json").exists()
    assert vision_run.timeline_current(work, ON)
    assert not (work / cloud.UPLOAD_CACHE).exists() and not (work / "asr_task.json").exists()


def test_current_timeline_is_not_redone(work):
    go(work, FakeClient())
    made = []
    out = vision_run.run(work, ON, work / "proxy.mp4", client_factory=lambda: made.append(1),
                         runner=runner)
    assert made == [] and out["events"]


def test_resume_skips_finished_chunks(work):
    c = FakeClient(wait_error={1: cloud.CloudError("超时", retryable=True)})
    with pytest.raises(cloud.CloudError):
        go(work, c)
    assert (work / "vision" / "chunk_000.json").exists()
    state = json.loads((work / "vision" / "state.json").read_text(encoding="utf-8"))
    assert state["chunks"]["1"]["task_id"]          # 可重试错误：任务号留着
    c2 = FakeClient()
    go(work, c2)
    assert c2.uploads == [] and c2.submits == []    # 段 0 已完成、段 1 续查
    assert c2.waits == [state["chunks"]["1"]["task_id"]]
    assert len(timeline(work)["events"]) == 4


def test_key_change_discards_old_results(work):
    go(work, FakeClient())
    cfg = {"vision": {"enabled": True, "tier": "quality"}}
    assert not vision_run.timeline_current(work, cfg)
    c = FakeClient()
    go(work, c, cfg)
    assert len(c.submits) == 2 and c.submits[0][1]["manual_option"]["fps"] == 3.0
    assert timeline(work)["setting"]["tier"] == "quality"


def test_copied_project_with_lost_mtime_keeps_timeline(work):
    """rsync / 备份恢复会丢掉亚秒或整个修改时间：内容没变，不能整条重传、再花一遍钱。"""
    go(work, FakeClient())
    proxy = work / "proxy.mp4"
    st = proxy.stat()
    os.utime(proxy, ns=(st.st_atime_ns, st.st_mtime_ns // 10**9 * 10**9 - 3600 * 10**9))
    assert vision_run.timeline_current(work, ON)
    c = FakeClient()
    go(work, c)
    assert c.uploads == [] and c.submits == []


def test_reencoded_proxy_of_same_size_invalidates_timeline(work):
    go(work, FakeClient())
    proxy = work / "proxy.mp4"
    st = proxy.stat()
    assert len(b"PROXY") == st.st_size
    proxy.write_bytes(b"PROXY")                      # 大小相同、内容不同（素材换过后重新转码）
    os.utime(proxy, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert not vision_run.timeline_current(work, ON)


def test_run_key_ignores_bytes_outside_samples_of_large_proxy(tmp_path):
    big = tmp_path / "proxy.mp4"
    with open(big, "wb") as f:
        f.truncate(vision_run.KEY_SAMPLE_BYTES * 10)
    key = vision_run.run_key(big, ON["vision"])
    with open(big, "r+b") as f:                      # 改动落在抽样区之外 → 不影响（只读三处）
        f.seek(vision_run.KEY_SAMPLE_BYTES * 2)
        f.write(b"x")
    assert vision_run.run_key(big, ON["vision"]) == key
    with open(big, "r+b") as f:                      # 改动落在中间抽样区 → key 变
        f.seek(vision_run.KEY_SAMPLE_BYTES * 5)
        f.write(b"x")
    assert vision_run.run_key(big, ON["vision"]) != key


MIB = 1 << 20


@pytest.mark.parametrize("size", [1, MIB - 1, MIB, 2 * MIB + 1, 3 * MIB])
def test_run_key_covers_every_byte_of_small_proxy(tmp_path, size):
    """3 个抽样窗口在 ≤ 3 MiB 时覆盖整个文件：任何一个字节变了 key 都变。"""
    assert vision_run.KEY_SAMPLE_BYTES == MIB
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(bytes(size))
    key = vision_run.run_key(proxy, ON["vision"])
    for pos in sorted({0, size // 3, size // 2, 2 * size // 3, size - 1}):
        data = bytearray(size)
        data[pos] = 1
        proxy.write_bytes(bytes(data))
        assert vision_run.run_key(proxy, ON["vision"]) != key, pos


def test_run_key_sees_first_and_last_byte_of_large_proxy(tmp_path):
    proxy = tmp_path / "proxy.mp4"
    size = 10 * MIB
    with open(proxy, "wb") as f:
        f.truncate(size)
    key = vision_run.run_key(proxy, ON["vision"])
    for pos in (0, size - 1):
        with open(proxy, "r+b") as f:
            f.seek(pos)
            f.write(b"x")
        assert vision_run.run_key(proxy, ON["vision"]) != key, pos
        with open(proxy, "r+b") as f:
            f.seek(pos)
            f.write(b"\0")


def test_run_key_of_empty_proxy_is_stable(tmp_path):
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"")
    assert vision_run.run_key(proxy, ON["vision"]) == vision_run.run_key(proxy, ON["vision"]) is not None


def test_unparseable_once_resubmits(work):
    c = FakeClient({0: ["我看不懂", answer((0, 300))]})
    go(work, c)
    assert len(c.submits) == 3 and usage.vision_tokens(work) == 300


def test_unparseable_twice_raises_with_chunk_and_time(work):
    c = FakeClient({1: ["乱码"]})
    with pytest.raises(vision_run.VisionError, match=r"第 2 段（05:00–10:10）"):
        go(work, c)
    assert (work / "vision" / "chunk_000.json").exists()   # 另一段已落盘
    failed = json.loads((work / "failed.json").read_text(encoding="utf-8"))
    assert failed[-1]["stage"] == "vision" and failed[-1]["context"] == {"chunk": 1}
    assert "work" not in failed[-1]["error"]


def test_terminal_failure_clears_task_and_upload(work):
    c = FakeClient(wait_error={0: cloud.CloudError("任务失败：x", terminal=True)})
    with pytest.raises(cloud.CloudError):
        go(work, c)
    state = json.loads((work / "vision" / "state.json").read_text(encoding="utf-8"))
    assert not state["chunks"]["0"].get("task_id") and not state["chunks"]["0"].get("file_id")
    assert json.loads((work / "failed.json").read_text(encoding="utf-8"))[-1]["stage"] == "vision"


def test_stale_cached_upload_is_reuploaded(work):
    c = FakeClient(wait_error={1: cloud.CloudError("超时", retryable=True)})
    with pytest.raises(cloud.CloudError):
        go(work, c)
    path = work / "vision" / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["chunks"]["1"]["task_id"] = None             # 有上传、没任务号：下次会续用上传
    path.write_text(json.dumps(state), encoding="utf-8")
    c2 = FakeClient(submit_error={1: [cloud.CloudError("云端拒绝：文件不存在")]})
    go(work, c2)
    assert len(c2.uploads) == 1 and len(c2.submits) == 2


def test_expired_upload_is_not_reused(work, monkeypatch):
    c = FakeClient(wait_error={1: cloud.CloudError("超时", retryable=True)})
    with pytest.raises(cloud.CloudError):
        go(work, c)
    path = work / "vision" / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["chunks"]["1"].update(task_id=None, upload_expires=0)
    path.write_text(json.dumps(state), encoding="utf-8")
    c2 = FakeClient()
    go(work, c2)
    assert [u[0] for u in c2.uploads] == ["chunk_001.mp4"]


def test_unreadable_duration_raises(work, monkeypatch):
    monkeypatch.setattr(vision_run.media_io, "duration_or_zero", lambda p, **k: 0.0)
    with pytest.raises(vision_run.VisionError, match="时长"):
        go(work, FakeClient())


def test_encode_failure_becomes_vision_error(work):
    def bad(cmd, **kw):
        return SimpleNamespace(returncode=1, stderr="boom")
    with pytest.raises(vision_run.VisionError, match="第 1 段"):
        vision_run.run(work, ON, work / "proxy.mp4", client_factory=FakeClient, runner=bad)


# ---------------------------------------------------------------- 给进度用的事实
def test_timeline_current_false_on_corrupt_or_missing(work):
    assert not vision_run.timeline_current(work, ON)
    (work / vision_run.TIMELINE_FILE).write_text("{bad", encoding="utf-8")
    assert not vision_run.timeline_current(work, ON)
    assert not vision_run.timeline_current(work, {})


def test_chunks_ready(work):
    assert not vision_run.chunks_ready(work, ON)
    c = FakeClient(wait_error={0: cloud.CloudError("超时", retryable=True),
                               1: cloud.CloudError("超时", retryable=True)})
    with pytest.raises(cloud.CloudError):
        go(work, c)
    assert vision_run.chunks_ready(work, ON)           # 两段都已编码
    go(work, FakeClient())
    assert vision_run.chunks_ready(work, ON)           # 段视频删了，但时间轴已是当前的


def test_ledger_write_failure_does_not_lose_paid_result(work, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(vision_run.usage, "record_vision", boom)
    go(work, FakeClient())
    assert len(timeline(work)["events"]) == 4
    assert "画面理解用量没记上" in capsys.readouterr().out


# ---------------------------------------------------------------- 审查修复：被杀窗口、中止、本地读写
class Killed(BaseException):
    """模拟进程在某一步之后被杀。"""


def test_killed_after_result_arrived_does_not_resubmit_or_double_count(work, monkeypatch):
    real = usage.record_vision
    calls = []

    def record_then_die(w, tu):
        calls.append(tu)
        if len(calls) == 1:
            raise Killed
        return real(w, tu)

    monkeypatch.setattr(vision_run.usage, "record_vision", record_then_die)
    with pytest.raises(Killed):
        go(work, FakeClient(), parallel=1)
    raw = work / "vision" / "chunk_000.raw.json"
    assert raw.exists()                                 # 原始输出已落盘
    monkeypatch.setattr(vision_run.usage, "record_vision", real)
    c2 = FakeClient()
    go(work, c2, parallel=1)
    assert c2.submits == [] and c2.waits == [] and c2.uploads == []  # 段 1 上一轮已完成；段 0 用原始输出
    assert usage.vision_tokens(work) == 100             # 段 0 被杀前没记上，只少记、不多记
    assert timeline(work)["usage"] == {"total_tokens": 200} and not raw.exists()


def test_killed_before_task_cleared_resumes_from_raw(work, monkeypatch):
    real_set = vision_run._State.set

    def die_on_clear(self, index, **fields):
        if fields == {"task_id": None} and index == 0 and not getattr(self, "_died", False):
            self._died = True
            raise Killed
        return real_set(self, index, **fields)

    monkeypatch.setattr(vision_run._State, "set", die_on_clear)
    with pytest.raises(Killed):
        go(work, FakeClient(), parallel=1)
    monkeypatch.setattr(vision_run._State, "set", real_set)
    c2 = FakeClient()
    go(work, c2, parallel=1)
    assert c2.submits == [] and c2.waits == []         # 没有重新提交，也没有再查一次
    assert usage.vision_tokens(work) == 100             # 段 0 记账在清任务号之后，被杀前没记上：只少记


def test_auth_failure_stops_other_chunks(work):
    c = FakeClient(wait_error={0: cloud.CloudError("Key 无效", status=401)})
    with pytest.raises(cloud.CloudError, match="Key 无效"):
        go(work, c, parallel=1)
    assert [u[0] for u in c.uploads] == ["chunk_000.mp4"]
    failed = json.loads((work / "failed.json").read_text(encoding="utf-8"))
    assert [f["context"] for f in failed] == [{"chunk": 0}]


def test_local_io_error_becomes_vision_error_without_path(work):
    c = FakeClient()

    def boom(path, **kw):
        raise PermissionError(13, "denied", str(path))

    c.upload = boom
    with pytest.raises(vision_run.VisionError, match="本地文件读写失败（PermissionError）") as ei:
        go(work, c, parallel=1)
    assert "chunk_" not in str(ei.value) and str(work) not in str(ei.value)


def test_timeline_not_current_without_proxy(work):
    go(work, FakeClient())
    (work / "proxy.mp4").unlink()
    assert not vision_run.timeline_current(work, ON)


# ---------------------------------------------------------------- 认回旧版指纹（43bc555 之前：大小 + 修改时间）
def old_key(proxy, tier="economy"):
    """43bc555 之前的 run_key，原样复刻（不调被测代码）。"""
    import hashlib
    st = Path(proxy).stat()
    raw = json.dumps({"size": st.st_size, "mtime_ns": st.st_mtime_ns, "tier": tier,
                      "prompt": vision.PROMPT_VERSION, "chunk_s": vision.CHUNK_S}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def rekey(path, key):
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "key": key}, ensure_ascii=False), encoding="utf-8")


def as_old_project(work):
    """把一次完整结果的所有指纹改回旧版公式，模拟改版前付过费的项目。"""
    legacy = old_key(work / "proxy.mp4")
    for p in [work / vision_run.TIMELINE_FILE, *(work / "vision").glob("*.json")]:
        if p.exists():
            rekey(p, legacy)
    return legacy


def test_old_timeline_is_adopted_without_upload(work, capsys):
    go(work, FakeClient())
    new = timeline(work)["key"]
    as_old_project(work)
    assert not vision_run.timeline_current(work, ON)   # 只读判断不改盘：② 先显示需要更新
    capsys.readouterr()
    c = FakeClient()
    go(work, c)
    assert c.uploads == [] and c.submits == [] and c.waits == []
    assert vision_run.ADOPTED in capsys.readouterr().out
    assert timeline(work)["key"] == new and vision_run.timeline_current(work, ON)
    state = json.loads((work / "vision" / "state.json").read_text(encoding="utf-8"))
    assert state["key"] == new


def test_old_timeline_with_changed_mtime_is_not_adopted(work):
    go(work, FakeClient())
    as_old_project(work)
    proxy = work / "proxy.mp4"
    st = proxy.stat()
    os.utime(proxy, ns=(st.st_atime_ns, st.st_mtime_ns - 10**9))
    assert not vision_run.current_or_adopt(work, ON)
    c = FakeClient()
    go(work, c)
    assert len(c.submits) == 2


def test_half_done_old_run_resumes_only_missing_chunks(work):
    c = FakeClient(wait_error={1: cloud.CloudError("超时", retryable=True)})
    with pytest.raises(cloud.CloudError):
        go(work, c)
    task = json.loads((work / "vision" / "state.json").read_text(encoding="utf-8"))["chunks"]["1"]["task_id"]
    as_old_project(work)
    c2 = FakeClient()
    go(work, c2)
    assert c2.uploads == [] and c2.submits == [] and c2.waits == [task]


def test_adoption_leaves_files_with_other_keys_alone(work):
    go(work, FakeClient())
    as_old_project(work)
    (work / vision_run.TIMELINE_FILE).unlink()         # 没跑完：只剩段结果
    rekey(work / "vision" / "chunk_001.json", "someotherkey0000")
    c = FakeClient()
    go(work, c)
    assert len(c.submits) == 1                         # 段 1 不是旧版指纹：照常重做


def test_current_or_adopt_adopts_before_cli_asks_for_key(work):
    go(work, FakeClient())
    as_old_project(work)
    assert vision_run.current_or_adopt(work, ON) is True
    assert vision_run.timeline_current(work, ON)


def test_current_or_adopt_off_or_without_proxy_is_false(work):
    assert vision_run.current_or_adopt(work, {}) is False
    (work / "proxy.mp4").unlink()
    assert vision_run.current_or_adopt(work, ON) is False


def test_reusable_is_read_only_and_sees_old_timeline(work):
    go(work, FakeClient())
    as_old_project(work)
    before = (work / vision_run.TIMELINE_FILE).read_text(encoding="utf-8")
    assert vision_run.reusable(work, ON) is True and not vision_run.timeline_current(work, ON)
    assert (work / vision_run.TIMELINE_FILE).read_text(encoding="utf-8") == before
    assert vision_run.reusable(work, {}) is False
    proxy = work / "proxy.mp4"
    st = proxy.stat()
    os.utime(proxy, ns=(st.st_atime_ns, st.st_mtime_ns - 10**9))
    assert vision_run.reusable(work, ON) is False


def test_readiness_does_not_ask_for_mediakit_key_for_adoptable_project(work):
    from pipeline import readiness
    go(work, FakeClient())
    as_old_project(work)
    (work / readiness.TRANSCRIPT_RAW).parent.mkdir(parents=True, exist_ok=True)
    (work / readiness.TRANSCRIPT_RAW).write_text("{}", encoding="utf-8")
    assert readiness.needed_keys(work, ON) == ["deepseek"]

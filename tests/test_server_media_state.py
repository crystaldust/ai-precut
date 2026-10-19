"""审查修复 7：GUI 的阶段/代理/预览状态与 CLI 用同一判定（完成标记，旧产物可认领）。"""
from conftest import make_project
from pipeline import media_io


def _state(gs, name="p1"):
    return gs.module.project_state(name)


def test_half_written_media_not_reported_done(gui_server, monkeypatch):
    monkeypatch.setattr(media_io, "_probe_duration", lambda *a: 0.0)
    make_project(gui_server.root, "p1", **{"work/proxy.mp4": b"half", "work/audio/asr.wav": b"half",
                                           "output/v1/preview.mp4": b"half",
                                           "output/v1/timeline.json": "{}"})
    st = _state(gui_server)
    assert st["has_proxy"] is False
    assert {s["key"]: s["done"] for s in st["stages"]}["audio"] is False
    assert st["versions"][0]["preview"] is False


def test_marked_media_reported_done(gui_server, monkeypatch):
    pdir = make_project(gui_server.root, "p1", **{"output/v1/timeline.json": "{}"})
    for rel in ("work/proxy.mp4", "work/audio/asr.wav", "output/v1/preview.mp4"):
        with media_io.atomic_output(pdir / rel) as tmp:
            tmp.write_bytes(b"full")
    st = _state(gui_server)
    assert st["has_proxy"] is True
    assert {s["key"]: s["done"] for s in st["stages"]}["audio"] is True
    assert st["versions"][0]["preview"] is True


def test_legacy_media_adopted_like_cli(gui_server, monkeypatch):
    monkeypatch.setattr(media_io, "_probe_duration", lambda *a: 9.0)
    make_project(gui_server.root, "p1", **{"work/proxy.mp4": b"legacy"})
    assert _state(gui_server)["has_proxy"] is True


def test_state_reports_llm_usage(gui_server, monkeypatch):  # KI-32
    from pipeline import usage
    monkeypatch.setenv(usage.BUDGET_ENV, "0")
    pdir = make_project(gui_server.root)
    usage.record(pdir / "work", "text", {"total_tokens": 777})
    assert _state(gui_server)["llm_usage"] == {"total_tokens": 777, "budget": None}

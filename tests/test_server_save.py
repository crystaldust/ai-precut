"""GL-18（保存不丢）与 GL-23（镜头 id 唯一）：服务端。"""
import json
import threading

from conftest import call, make_project

SHOTS = [{"id": "sh01", "in": 0, "out": 1, "sub": "", "note": ""}]
SCORED = {"segments": [{"id": "S001", "start": 0, "end": 1, "level": 2, "text": "x"}],
          "topics": []}


def test_jdump_concurrent_same_path(tmp_path):
    from gui import server
    p = tmp_path / "x.json"
    errors = []

    def worker(n):
        try:
            for _ in range(25):
                server.jdump(p, {"i": n})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert "i" in json.loads(p.read_text(encoding="utf-8"))
    assert list(tmp_path.glob("*.tmp")) == [] and list(tmp_path.glob(".*.tmp")) == []


def _shots_post(gs, **kw):
    return call(gs, "POST", "/api/shots?project=p1", **kw)


def test_shots_invalid_json_does_not_overwrite(gui_server):
    pdir = make_project(gui_server.root, shots=SHOTS)
    before = (pdir / "shots.json").read_bytes()
    status, _, _ = _shots_post(gui_server, raw=b"{bad")
    assert status == 400
    assert (pdir / "shots.json").read_bytes() == before


def test_shots_non_object_body_rejected(gui_server):
    pdir = make_project(gui_server.root, shots=SHOTS)
    before = (pdir / "shots.json").read_bytes()
    status, _, _ = _shots_post(gui_server, raw=b"[1]")
    assert status == 400
    assert (pdir / "shots.json").read_bytes() == before


def test_shots_non_utf8_body_rejected(gui_server):
    make_project(gui_server.root, shots=SHOTS)
    status, _, _ = _shots_post(gui_server, raw=b"\xff\xfe")
    assert status == 400


def test_shots_missing_key_does_not_overwrite(gui_server):
    pdir = make_project(gui_server.root, shots=SHOTS)
    before = (pdir / "shots.json").read_bytes()
    status, _, _ = _shots_post(gui_server, body={})
    assert status == 400
    assert (pdir / "shots.json").read_bytes() == before


def test_shots_explicit_empty_list_allowed(gui_server):
    pdir = make_project(gui_server.root, shots=SHOTS)
    status, body, _ = _shots_post(gui_server, body={"shots": []})
    assert status == 200
    assert json.loads(body)["count"] == 0
    assert json.loads((pdir / "shots.json").read_text(encoding="utf-8"))["shots"] == []


def test_shots_duplicate_ids_rejected(gui_server):
    pdir = make_project(gui_server.root, shots=SHOTS)
    before = (pdir / "shots.json").read_bytes()
    dup = [{"id": "sh03", "in": 0, "out": 1}, {"id": "sh03", "in": 1, "out": 2}]
    status, body, _ = _shots_post(gui_server, body={"shots": dup})
    assert status == 400
    assert "sh03" in json.loads(body)["error"]
    assert (pdir / "shots.json").read_bytes() == before


def test_shots_missing_id_rejected(gui_server):
    make_project(gui_server.root, shots=SHOTS)
    status, _, _ = _shots_post(gui_server, body={"shots": [{"in": 0, "out": 1}]})
    assert status == 400


def test_shots_valid_save(gui_server):
    pdir = make_project(gui_server.root, shots=SHOTS)
    shots = [{"id": "sh01", "in": 0, "out": 1.23456, "sub": "a", "note": ""},
             {"id": "sel02", "in": 2, "out": 3}]
    status, _, _ = _shots_post(gui_server, body={"shots": shots})
    assert status == 200
    saved = json.loads((pdir / "shots.json").read_text(encoding="utf-8"))["shots"]
    assert [s["id"] for s in saved] == ["sh01", "sel02"]
    assert saved[0]["out"] == 1.235


def test_concurrent_shots_saves_all_ok(gui_server):
    pdir = make_project(gui_server.root, shots=SHOTS)
    statuses = []
    lock = threading.Lock()

    def worker(n):
        st, _, _ = _shots_post(gui_server, body={"shots": [
            {"id": f"sh{n:02d}", "in": 0, "out": 1}]})
        with lock:
            statuses.append(st)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses == [200] * 20
    json.loads((pdir / "shots.json").read_text(encoding="utf-8"))


def test_browse_level_on_corrupt_overrides_409(gui_server):
    pdir = make_project(gui_server.root, **{"work/overrides.json": "{bad"})
    status, body, _ = call(gui_server, "POST", "/api/browse/level",
                           {"project": "p1", "id": "S001", "level": 3})
    assert status == 409
    assert "overrides.json" in json.loads(body)["error"]
    assert (pdir / "work/overrides.json").read_text(encoding="utf-8") == "{bad"


def test_browse_must_on_corrupt_overrides_409(gui_server):
    pdir = make_project(gui_server.root, **{"work/overrides.json": "{bad"})
    status, _, _ = call(gui_server, "POST", "/api/browse/must",
                        {"project": "p1", "id": "S001", "must": True})
    assert status == 409
    assert (pdir / "work/overrides.json").read_text(encoding="utf-8") == "{bad"


def test_browse_get_on_corrupt_overrides_409(gui_server):
    make_project(gui_server.root, **{"work/overrides.json": "{bad",
                                     "work/segments_scored.json": json.dumps(SCORED)})
    status, body, _ = call(gui_server, "GET", "/api/browse?project=p1")
    assert status == 409
    assert "overrides.json" in json.loads(body)["error"]


def test_browse_get_ok_without_overrides(gui_server):
    make_project(gui_server.root, **{"work/segments_scored.json": json.dumps(SCORED)})
    status, body, _ = call(gui_server, "GET", "/api/browse?project=p1")
    assert status == 200
    assert json.loads(body)["segments"][0]["id"] == "S001"

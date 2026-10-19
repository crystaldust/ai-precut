"""GL-06 / GL-18 / GL-23：aicut 侧的路径与镜头 id 守卫。"""
import json
import threading
from argparse import Namespace

import pytest

import aicut


def _fail(*_a, **_k):
    raise AssertionError("不应该被调用")


def _make_project(root, name="p", shots=None):
    pdir = root / name
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"name": name, "material": "/tmp/a.mp4", "schema_version": 2}), encoding="utf-8")
    shots = shots if shots is not None else [{"id": "sh01", "in": 0, "out": 1}]
    (pdir / "shots.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")
    return pdir


def test_project_dir_rejects_option_like_name(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _make_project(tmp_path, "-h")  # 即使目录真的存在也必须拒绝
    with pytest.raises(SystemExit):
        aicut.project_dir("-h")


def test_project_dir_rejects_traversal(monkeypatch, tmp_path):
    (tmp_path / "projects").mkdir()
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    _make_project(tmp_path, "outside")
    with pytest.raises(SystemExit):
        aicut.project_dir("../outside")


def test_new_rejects_traversal_name(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    args = Namespace(name="../evil", material=str(tmp_path), preset="纪实3min",
                     title=None, tone=None, audience=None, must_lines=None)
    with pytest.raises(SystemExit):
        aicut.cmd_new(args)
    assert not (tmp_path / "evil").exists()


def test_build_rejects_traversal_version(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", _fail)
    _make_project(tmp_path)
    with pytest.raises(SystemExit):
        aicut.cmd_build(Namespace(name="p", version="../../evil", no_draft=True))
    assert not (tmp_path / "evil").exists()


def test_ensure_clips_rejects_traversal_id(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut.media_io, "run_ffmpeg", _fail)
    pdir = _make_project(tmp_path)
    with pytest.raises(SystemExit):
        aicut.ensure_clips(pdir, {"material": "/tmp/a.mp4"},
                           [{"id": "../../x", "in": 0, "out": 1}])
    assert not (pdir / "work/clips").exists()


def test_ensure_clips_rejects_duplicate_ids(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut.media_io, "run_ffmpeg", _fail)
    pdir = _make_project(tmp_path)
    shots = [{"id": "sh03", "in": 0, "out": 1}, {"id": "sh03", "in": 1, "out": 2}]
    with pytest.raises(SystemExit):
        aicut.ensure_clips(pdir, {"material": "/tmp/a.mp4"}, shots)
    assert "重复" in capsys.readouterr().out


def test_save_json_uses_atomic_helper(tmp_path):
    p = tmp_path / "x.json"
    errors = []

    def worker(n):
        try:
            for _ in range(25):
                aicut.save_json(p, {"i": n})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert "i" in json.loads(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", [" p", "p ", "九" * 86])
def test_project_dir_rejects_edge_whitespace_and_byte_overflow(monkeypatch, tmp_path, name):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    with pytest.raises(SystemExit):
        aicut.project_dir(name)


def test_new_rejects_edge_whitespace_name(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    args = Namespace(name="p ", material=str(tmp_path), preset="纪实3min",
                     title=None, tone=None, audience=None, must_lines=None)
    with pytest.raises(SystemExit):
        aicut.cmd_new(args)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- KI-69：并发新建同名项目
def test_cmd_new_loses_race_without_clobbering(monkeypatch, tmp_path):
    from pipeline import schema
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    material = tmp_path / "a.mp4"
    material.write_bytes(b"x")
    theirs = {"name": "race", "material": "/their.mp4", "schema_version": 2}

    def lose(path, obj):
        path.write_text(json.dumps(theirs), encoding="utf-8")  # 对方抢先写好
        raise FileExistsError(path)

    monkeypatch.setattr(schema, "create_json_exclusive", lose)
    args = Namespace(name="race", material=str(material), preset="纪实3min", title=None,
                     tone=None, audience=None, must_lines=None, target=60, no_input=True)
    with pytest.raises(SystemExit) as ei:
        aicut.cmd_new(args)
    assert ei.value.code == 1
    pj = tmp_path / "projects/race/project.json"
    assert json.loads(pj.read_text()) == theirs  # 对方的文件不变，目录也还在


# ---------------------------------------------------------------- KI-51：读改写走加锁的 update_project
def test_cmd_select_target_saved_through_locked_update(monkeypatch, tmp_path):
    from pipeline import schema
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _make_project(tmp_path, "p")
    (pdir / "work").mkdir()
    (pdir / "work/segments_scored.json").write_text("{}")
    res = {"stats": {"shots": 1}, "total": 60, "target": 60, "missing_must_topics": []}
    monkeypatch.setattr(aicut.select, "run", lambda *a, **k: res)
    seen = []
    real = schema.update_project

    def spy(path, mutate):
        def mutate_with_rival(c):  # 锁内模拟另一个写者先改了 calibration
            return mutate({**c, "calibration": {"tone": "emotion"}})
        seen.append(path)
        return real(path, mutate_with_rival)

    monkeypatch.setattr(schema, "update_project", spy)
    aicut.cmd_select(Namespace(name="p", target=60))
    cfg = json.loads((pdir / "project.json").read_text())
    assert seen == [pdir / "project.json"]
    assert cfg["target_duration"] == 60 and cfg["calibration"] == {"tone": "emotion"}

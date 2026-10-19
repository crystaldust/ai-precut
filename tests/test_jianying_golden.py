"""剪映草稿黄金回归（KI-17）：固定 pyJianYingDraft 0.3.1 + 11.0 骨架生成结果的结构。

只比「结构」（键路径 + 值类型 + 关键版本字段 + 轨道/素材计数），不比 id、时间戳、路径、时长数值。
有意升级 pyJianYingDraft 或模板时：AICUT_UPDATE_GOLDEN=1 uv run pytest tests/test_jianying_golden.py，
然后人工审阅 git diff，并在剪映 Mac / Windows 实机打开一次再提交。
"""
import importlib.metadata
import json
import os
import tomllib
from pathlib import Path

import pytest

from pipeline import jy_version, proc
from tests.test_to_jianying import CARD, SUB, clip, full_timeline  # noqa: F401  复用夹具

GOLDEN = Path(__file__).parent / "golden" / "jianying_draft_shape.json"
ROOT = Path(__file__).resolve().parent.parent
UPDATE_ENV = "AICUT_UPDATE_GOLDEN"   # 已核对：VideoToolbox 与 mpeg4 素材生成的快照一致


def shape(obj, path="$") -> set[str]:
    if isinstance(obj, dict):
        return {f"{path}:dict"}.union(*(shape(v, f"{path}.{k}") for k, v in obj.items()))
    if isinstance(obj, list):
        return {f"{path}:list"}.union(*(shape(v, f"{path}[]") for v in obj))
    return {f"{path}:{type(obj).__name__}"}


def snapshot(d: Path) -> dict:
    content = json.loads((d / "draft_content.json").read_text(encoding="utf-8"))
    meta = json.loads((d / "draft_meta_info.json").read_text(encoding="utf-8"))
    return {"pyjianyingdraft": importlib.metadata.version("pyJianYingDraft"),
            "version": content["version"], "new_version": content["new_version"],
            "app_version": content["platform"]["app_version"],
            "tracks": [[t["type"], t.get("name", ""), len(t["segments"])]
                       for t in content["tracks"]],
            "materials_nonempty": {k: len(v) for k, v in sorted(content["materials"].items())
                                   if isinstance(v, list) and v},
            "content_shape": sorted(shape(content)), "meta_shape": sorted(shape(meta))}


def test_draft_matches_golden(tmp_path, clip):  # noqa: F811
    tl = tmp_path / "timeline.json"
    tl.write_text(json.dumps(full_timeline(clip, [
        {"text": "他说'好'，100%", "start": 0.0, "end": 0.6, **SUB},
        {"text": "卡", "start": 0.0, "end": 0.8, **CARD}]), ensure_ascii=False), encoding="utf-8")
    code, out = proc.run_inprocess("pipeline.to_jianying", [str(tl), "--name", "G",
                                   "--staging", str(tmp_path / "stg"), "--dry-run"])
    assert code == 0, out
    got = snapshot(tmp_path / "stg" / "G")
    if os.environ.get(UPDATE_ENV) == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        pytest.skip("已重写黄金快照，请人工审阅 diff")
    assert got == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_records_the_verified_jianying_version():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert golden["app_version"] == jy_version.VERIFIED_VERSION


def test_lockfile_pins_the_golden_library_version():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    pinned = next(p["version"] for p in lock["package"] if p["name"] == "pyjianyingdraft")
    assert pinned == json.loads(GOLDEN.read_text(encoding="utf-8"))["pyjianyingdraft"]

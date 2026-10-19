"""结构守卫（KI-54 / KI-55）：入口文件不能再长回去；新模块必须进打包清单。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AICUT_MAX_LINES = 800
SERVER_MAX_LINES = 650


def _lines(rel: str) -> int:
    return len((ROOT / rel).read_text(encoding="utf-8").splitlines())


def test_entry_files_under_soft_ceiling():
    assert _lines("aicut.py") <= AICUT_MAX_LINES
    assert _lines("gui/server.py") <= SERVER_MAX_LINES


def test_new_pipeline_modules_in_spec_hiddenimports():
    spec = (ROOT / "packaging/ai-cut.spec").read_text(encoding="utf-8")
    hidden = set(re.findall(r'"((?:pipeline|gui)\.[a-z_]+)"', spec))
    modules = {f"{pkg}.{p.stem}" for pkg in ("pipeline", "gui")
               for p in (ROOT / pkg).glob("*.py") if p.stem != "__init__"}
    assert sorted(modules - hidden) == []


def test_aicut_reexports_split_helpers():
    import aicut
    from pipeline import prompts, timeline
    assert aicut.compose_timeline is timeline.compose_timeline
    assert aicut.ask_target is prompts.ask_target
    assert aicut.ask_calibration is prompts.ask_calibration


def test_main_dispatches_through_current_globals(monkeypatch):
    import aicut
    seen = []
    monkeypatch.setattr(aicut, "cmd_status", lambda args: seen.append(args.name))
    aicut.main(["status", "p1"])
    assert seen == ["p1"]

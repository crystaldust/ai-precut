"""从 aicut.py 拆出的命令辅助（KI-55）：策划分派单、`aicut config`、终端问答（KI-38 补覆盖）。"""
import io
from types import SimpleNamespace

import pytest

from pipeline import brief, config_cli, consent, prompts, secrets, style

CFG = {"title": "合同", "material": "/v/a.mov", "platform": "douyin"}
PRESET = {"name": "纪实", "duration": 180, "structure": ["开场", "冲突"], "subtitle": {"max_chars": 12}}
SEGS = [{"id": "S001", "start": 1.0, "end": 2.5, "text": "学费九千八"}]


# ---------------------------------------------------------------- brief
def test_render_brief_lists_preset_segments_and_junk():
    junk = [{"start_tc": "00:00:01.000", "end_tc": "00:00:02.000", "reason": "黑场", "suggest": "删"}]
    md = brief.render_brief(CFG, PRESET, SEGS, junk)
    assert md.startswith("# 策划分派单 · 合同")
    assert "- 原片：`/v/a.mov`" in md
    assert "- 预设：纪实（180s，douyin）" in md
    assert "- 结构建议：开场 → 冲突" in md and "≤12 字/行" in md
    assert "## 分段文稿（1 段）" in md and "**[S001] 1.0–2.5s** 学费九千八" in md
    assert "## 规则层废片候选" in md and "- 00:00:01.000–00:00:02.000 黑场（删）" in md


def test_render_brief_without_junk_uses_default_subtitle_width():
    md = brief.render_brief(CFG, {"name": "空"}, [], [])
    assert "废片候选" not in md
    assert f"≤{brief.DEFAULT_MAX_CHARS} 字/行" in md
    assert "## 分段文稿（0 段）" in md and md.rstrip().endswith("出片。")


# ---------------------------------------------------------------- config_cli
class Out:
    def __init__(self):
        self.ok, self.info, self.die = [], [], []

    def kw(self):
        def die(msg):
            self.die.append(msg)
            raise SystemExit(1)
        return {"ok": self.ok.append, "info": self.info.append, "die": die}


def _args(action=None, provider="mediakit"):
    return SimpleNamespace(action=action, provider=provider)


def _stdin(monkeypatch, text, tty=False):
    stream = io.StringIO(text)
    stream.isatty = lambda: tty
    monkeypatch.setattr(config_cli.sys, "stdin", stream)


def test_config_show_masks_and_hints_when_unconfigured(no_keys, capsys):
    out = Out()
    config_cli.run(_args(), **out.kw())
    printed = capsys.readouterr().out
    assert "[·] mediakit" in printed and "未配置" in printed
    assert out.info == ["设置：uv run python aicut.py config set mediakit"]


def test_config_set_reads_stdin_saves_masked_then_show(no_keys, monkeypatch, capsys):
    _stdin(monkeypatch, "AK-1234567890abcdef\n")
    out = Out()
    config_cli.run(_args("set"), **out.kw())
    assert secrets.get("mediakit") == "AK-1234567890abcdef"
    assert out.ok == [f"已保存到 file：{secrets.mask('AK-1234567890abcdef')}"]
    assert "AK-1234567890abcdef" not in out.ok[0]  # 只回显掩码
    config_cli.run(_args(), **out.kw())
    shown = capsys.readouterr().out
    assert "[✓] mediakit" in shown and "AK-1234567890abcdef" not in shown
    assert out.info == []  # 已配置：不再提示怎么设置


def test_config_set_uses_getpass_on_tty(no_keys, monkeypatch):
    _stdin(monkeypatch, "", tty=True)
    import getpass
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "  sk-from-tty  ")
    config_cli.run(_args("set", "deepseek"), **Out().kw())
    assert secrets.get("deepseek") == "sk-from-tty"


def test_config_set_empty_key_is_refused(no_keys, monkeypatch):
    _stdin(monkeypatch, "\n")
    out = Out()
    with pytest.raises(SystemExit):
        config_cli.run(_args("set"), **out.kw())
    assert out.die == [config_cli.KEY_EMPTY] and secrets.get("mediakit") is None


def test_config_unset_deletes_key(no_keys):
    secrets.set("mediakit", "AK-x")
    out = Out()
    config_cli.run(_args("unset"), **out.kw())
    assert secrets.get("mediakit") is None and out.ok == ["已删除 mediakit"]


def test_config_consent_prints_notice_and_records(capsys):
    assert not consent.accepted()
    out = Out()
    config_cli.run(_args("consent"), **out.kw())
    printed = capsys.readouterr().out
    assert consent.NOTICE_TITLE in printed and consent.NOTICE_LINES[0] in printed
    assert consent.accepted() and out.ok


def test_config_unknown_action_dies():
    out = Out()
    with pytest.raises(SystemExit):
        config_cli.run(_args("rotate"), **out.kw())
    assert out.die == ["未知操作：rotate"]


# ---------------------------------------------------------------- prompts
def _tty(monkeypatch, answers):
    stream = io.StringIO()
    stream.isatty = lambda: True
    monkeypatch.setattr(prompts.sys, "stdin", stream)
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def test_ask_target_non_interactive_returns_default(monkeypatch):
    stream = io.StringIO()
    stream.isatty = lambda: False
    monkeypatch.setattr(prompts.sys, "stdin", stream)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("GUI 任务里绝不 input()"))
    assert prompts.ask_target(175) == 175
    assert prompts.ask_calibration({"tone": "info"}) == style.normalize({"tone": "info"})


def test_ask_target_retries_until_valid(monkeypatch, capsys):
    _tty(monkeypatch, ["abc", "90"])
    assert prompts.ask_target(175) == 90
    assert "abc" in capsys.readouterr().out  # 非法输入说出原因再问


def test_ask_target_blank_uses_default(monkeypatch):
    _tty(monkeypatch, [""])
    assert prompts.ask_target(120) == 120


def test_ask_calibration_keeps_defaults_on_blank_and_reports(monkeypatch, capsys):
    _tty(monkeypatch, ["emotion", "", "就这句"])
    cur = prompts.ask_calibration({"audience": "家长"})
    assert cur == {"tone": "emotion", "audience": "家长", "must_lines": "就这句"}
    printed = capsys.readouterr().out
    assert "已记录：情绪优先 · 观众 家长 · 含指定原话" in printed

# -*- coding: utf-8 -*-
"""KI-96：界面名词统一。后端会显示到界面的提示文案不能再指向旧入口（M13 T10）。"""
import re

import pytest

import aicut
from gui import jobs, server, settings
from pipeline import cache, classify, clips, encode, exclusions, notices, select, understand_text

# 旧入口 / 旧叫法：这些在新界面里都不存在
OLD_ENTRY_NAMES = ("「浏览素材」", "「确认与提问」", "「改目标时长」", "① 处理素材", "「处理素材」",
                   "② 生成成片", "「生成成片」", "⚙ 设置 · API Key", "左下角", "★")
# 「必留」只能以「必留话题」出现；单个片段叫「剪辑列表里的片段」
MUST_KEEP_BARE = re.compile(r"必留(?!话题)")


def _strings(module, *, prefixes=(), names=()):
    for name, value in vars(module).items():
        if isinstance(value, str) and (name in names or name.startswith(tuple(prefixes))):
            yield f"{module.__name__}.{name}", value


def _all_copy():
    yield from _strings(notices, prefixes=("REMEDY_",), names=(
        "TEXT_INCOMPLETE_NOTICE", "SUMMARY_FALLBACK_NOTICE", "QUESTIONS_FALLBACK_NOTICE",
        "MISSING_TOPICS_NOTICE", "CORRUPT_SHOTS_NOTICE", "CORRUPT_FILE_NOTICE"))
    yield from _strings(classify, names=("TEXT_INCOMPLETE_ERROR", "LEGACY_FAILED_WARNING",
                                         "AUDIO_MISSING_WARNING", "PENDING_OVER_WARNING"))
    yield from _strings(select, prefixes=("MUST_KEEP_",), names=(
        "ANSWER_UNMATCHED", "OVERRIDES_STALE_WARNING", "BUDGET_LEGACY_WARNING",
        "MUST_TOPIC_UNMATCHED"))
    yield from _strings(settings, names=("NEED_KEYS_MSG",))
    yield from _strings(server, names=("INTERNAL_ERROR_MSG",))
    yield from _strings(jobs, names=("NO_TIMELINE_MSG",))
    yield from _strings(clips, names=("NEED_REBUILD", "KEY_MISMATCH"))
    yield from _strings(cache, names=("CLIPS_LABEL",))
    yield from _strings(understand_text, names=("ANNOTATION_RETRY_HINT",))
    yield from _strings(encode, names=("ENCODER_UNAVAILABLE",))
    yield from _strings(exclusions, names=("MUST_KEEP_LOST", "EXPORT_NO_SNAPSHOT", "EXPORT_BAD_SNAPSHOT"))
    yield from _strings(aicut, names=("TEXT_PARTIAL_WARNING", "PREPARE_KEYS_MISSING",
                                      "MUST_KEEP_OVER_HINT"))


COPY = sorted(_all_copy())


def test_copy_collection_is_not_empty():
    names = {n.rsplit(".", 1)[1] for n, _ in COPY}
    assert {"TEXT_INCOMPLETE_NOTICE", "REMEDY_REBUILD", "REMEDY_REBUILD_VERSION", "NEED_KEYS_MSG",
            "INTERNAL_ERROR_MSG", "MUST_KEEP_REASON", "MUST_KEEP_REMEDY_SELECTED", "NEED_REBUILD",
            "ENCODER_UNAVAILABLE", "PREPARE_KEYS_MISSING", "CLIPS_LABEL"} <= names


@pytest.mark.parametrize("name,text", COPY, ids=[n for n, _ in COPY])
def test_backend_copy_points_to_new_ui(name, text):
    for old in OLD_ENTRY_NAMES:
        assert old not in text, f"{name} 还在用旧入口「{old}」：{text}"
    assert not MUST_KEEP_BARE.search(text), f"{name} 里的「必留」要改成「剪辑列表里的片段」：{text}"


def test_notice_remedies_name_the_new_steps():
    assert "② 分析" in notices.REMEDY_REBUILD and "重新分析" in notices.REMEDY_REBUILD
    assert "⑤ 看结果" in notices.REMEDY_RESELECT
    assert "④ 定标准" in notices.REMEDY_REANSWER
    assert "⑥ 导出" in notices.REMEDY_REBUILD_VERSION


def test_key_hints_point_to_more_menu():
    assert "更多 → 设置 · API Key" in settings.NEED_KEYS_MSG
    assert "更多 → 设置 · API Key" in aicut.PREPARE_KEYS_MISSING
    assert "更多 → 导出诊断包" in server.INTERNAL_ERROR_MSG


def test_must_keep_copy_uses_clip_list_wording():
    assert select.MUST_KEEP_REASON == "剪辑列表里的片段"
    assert "③ 看素材" in select.MUST_KEEP_EMPTY_WARNING
    assert "③ 看素材" in select.MUST_KEEP_REMEDY_MANUAL and "③ 看素材" in select.MUST_KEEP_REMEDY_SELECTED
    assert "③ 看素材" in select.OVERRIDES_STALE_WARNING
    assert "④ 定标准" in select.ANSWER_UNMATCHED


def test_rebuild_hints_point_to_export_step():
    assert "⑥ 导出" in clips.NEED_REBUILD
    assert "② 分析" in aicut.TEXT_PARTIAL_WARNING
    assert "② 分析" in classify.AUDIO_MISSING_WARNING


def test_selection_error_wording():
    segs = [{"id": "S001", "start": 0, "end": 5, "must_keep": True, "text": "x"}]
    with pytest.raises(select.SelectionError) as exc:
        select._must_keep_report(segs, [], [], 60, 0)
    assert "剪辑列表里的片段未进片：S001" in str(exc.value)

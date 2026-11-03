# Plan: ④ 定标准 · 决策问题「自定义」

**Source**: 用户请求 2026-10-29（/ecc:orch-add-feature）；Gate 1 已批准
**Size**: standard（偏大，约 10 个文件；用户输入 + 外部 API → 加 security-reviewer）

## 决定

- 自定义文字由 AI（DeepSeek）换算成现有 6 种选段规则（must_topics / exclude / ending / focus / pacing / must_lines）
- 单选题：选「自定义」= 替换选项；多选题：「自定义」可与其他选项同时勾
- 所有题之后另有一个「其他想法（自定义）」（`_extra`），可换算成任意种类
- 换算在确认后的选段任务里做（不在点选时实时调用）；按文字 + 话题 + 题目摘要缓存在 `work/custom_rules.json`
- 换算不出来：选段照常，warnings 说明「未生效」；LLM 失败 / 超预算：选段任务失败、中文原因、答案已保存（不静默降级，同 GL-09）

## 数据

`work/brief_answers.json` 新增 `custom: {"q1": "…", "_extra": "…"}`，每条 ≤200 字、去首尾空白、空串丢弃、题 id 必须存在。
单选题有自定义时 `answers[qid]` 去掉。`fingerprints.answers_digest` 计入 `custom`。

## Tasks

1. 答案里的自定义：`questions.normalize_custom()`；`confirm.save_answers` 存；`answers_digest` 计入
2. 抽出 `questions.validate_rule(rule, topic_names)`，出题与换算共用（纯重构）
3. `pipeline/custom_rules.py`：提示词、按题限制种类、校验、未生效说明、按摘要缓存
4. 接入选段：`cmd_select` 有自定义时外发确认 + 计量 client 换算，失败非零退出；`select.run` 合并（单值规则以自定义为准）并写 warnings
5. `payloads.confirm` 返回 `custom` 与匹配当前文字的上次换算结果
6. ④ 界面：每题「自定义」+ 输入框、题后「其他想法（自定义）」、目录计为已答、草稿自动保存、显示上次换算、转义（GL-07）；node 行为测试
7. 文档：PRD FR-5、PROGRESS、放行检查 #31、GUI.md

## Validation

- 每个任务先写失败测试；`uv run pytest --cov` ≥ 80%
- 审查：python-reviewer、typescript-reviewer、security-reviewer；CRITICAL/HIGH 修完再提交

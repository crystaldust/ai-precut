# Plan: ⑤ 看结果 ·「查看 AI 提示词」按钮 + 弹窗

**Source**: 用户请求 2026-10-29（/ecc:orch-add-feature）：④ 完成后，在 ⑤ 显示最终发送给 AI 的提示词，按钮 + 弹窗，不常驻
**Size**: standard（约 6 个文件，新增一个只读 GET 接口）

## 事实与决定

- 选段本身是规则计算，不调用 AI；④ 之后唯一的 AI 调用是「自定义」换算（`pipeline/custom_rules.py`）
- 用户选定：弹窗显示 **提示词 + AI 回复 + 最终规则**
  - 填了自定义：系统提示词、用户提示词、AI 原始回复、换算时间、每条自定义换算出的规则 / 未生效说明
  - 没填自定义：说明「本次选段没有调用 AI」
  - 两种情况都列出本次选段实际用到的规则（选项 + 自定义合并后，`selection.json` 的 `rules`），用人话
- 记录的是**实际发出**的内容，不在显示时重新拼：换算时把 `system` / `user` / `reply` / `at` 一起写进 `work/custom_rules.json`；
  选段把这份记录抄进 `selection.json`（`custom_prompt`），⑤ 看到的永远是生成当前选段时用的那一份
- 旧缓存没有这几项（本功能之前换算的）：不为此重新调用 AI（不重复计费），弹窗说明「当时没有记录原始提示词」，规则照常显示
- 数据按需拉取：点按钮才请求 `GET /api/result/prompt?project=`，不进 `/api/result`

## Tasks

1. `custom_rules.interpret` 返回并缓存 `prompt: {system, user}`、`reply`、`at`；`load_current` 保留这些字段（不参与校验）
2. `select.run` 把 `custom_prompt`（无自定义时 None）写进结果；`select_rules.describe_rules(rules)` 把合并后的规则字典转成人话列表
3. `result_payload.ai_prompt(pdir)` + 路由 `GET /api/result/prompt`：读 `selection.json`（没有 → 404「还没有选段」，坏了 → 409）
4. ⑤ 前端：顶栏加「查看 AI 提示词」按钮 → `showModal`，提示词放可滚动的 `<pre>`，全部转义；node 行为测试
5. 文档：GUI.md（⑤、API 表）、PROGRESS、放行检查 #32

## Validation

- 每个任务先写失败测试；`uv run pytest --cov` ≥ 80%
- 审查：python-reviewer、typescript-reviewer；弹窗显示剪辑师文字和模型回复 → 加 security-reviewer（XSS）

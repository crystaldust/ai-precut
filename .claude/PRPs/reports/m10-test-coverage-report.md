# Implementation Report: M10 测试达标（KI-38 / KI-39）

## Summary
引入 `pytest-cov` 并在 `pyproject.toml` 固定统计范围与 `fail_under = 80`，`uv run pytest --cov` 现在可以跑，跌破 80% 就以非 0 退出。
新增「素材 → 剪映草稿 / Windows 导出包」端到端测试（同进程打包路径 + 子进程开发路径 + 未确认外发告知的拦截），
修掉 `tests/test_proc.py` 两条恒真断言，并按**当前**实测覆盖率给最低的几个文件补了行为测试。产品代码零改动。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Medium | Medium |
| 基线 | 987 passed，TOTAL 82% | 1702 passed，TOTAL **92%**（M6–M9 之后） |
| 完成后 | ≈1030 passed，≈90% | 1756 passed（全量，含 M11 文档测试），TOTAL **93.87%** |
| Files Changed | 12 | 10（见下） |

## Coverage before / after（`uv run pytest --cov`，coverage 7.16.2）

| File | Before | After |
|---|---|---|
| **TOTAL** | 92%（7019 stmts，553 miss） | **93.87%**（430 miss） |
| `app/main.py` | 0% | 97% |
| `pipeline/brief.py` | 25% | 100% |
| `pipeline/config_cli.py` | 38% | 100% |
| `pipeline/prompts.py` | 57% | 100% |
| `gui/views.py` | 78% | 98% |
| `pipeline/proc.py` | 80% | 83% |
| `aicut.py` | 85% | 90% |

当前最低：`pipeline/proc.py` 83%（剩余是看门狗 / 冻结自启分支，已由子进程测试覆盖但不计入统计）、`research/validate_draft.py` 83%、`pipeline/timeline.py` 86%、`pipeline/secrets.py` 88%、`pipeline/project_lock.py` 88%、`pipeline/build_documentary.py` 88%。
不含 E2E（无 VideoToolbox 的机器会 skip）时 TOTAL 93.42%，门槛余量充足。门槛自检：`--cov-fail-under=99` → 退出码 1（`FAIL Required test coverage of 99% not reached`）。

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | 覆盖率工具与门槛 | done | 先写守卫测试（RED：KeyError/AssertionError）→ `uv add --dev "pytest-cov>=6"`（用户已批准）+ `[tool.coverage.*]` + `.gitignore` → GREEN |
| 2 | test_proc 恒真断言 | done | 变异自检：把 `"AI粗剪"` 改掉 → `test_user_data_root_frozen_default_is_documents` 变红，已还原 |
| 3 | E2E 素材 → 草稿 / 包 | done | 3 个用例，约 5.5 s；变异自检：去掉★标记 → 两条「九千八进片」断言都变红，已还原 |
| 4–7 | format_transcript / junk_detect / render_preview / build_documentary | skipped（已由 M6–M8 完成） | 当前 95% / 95% / 98% / 88%，对应测试文件已存在 |
| 8 | app/main 入口 | done | 4 个用例；变异自检：删 `finally` 里的 `jobs.shutdown_all()` → 2 个用例变红，已还原 |
| 9 | 全量验证 + CLAUDE.md | done | 只改「命令」节新增覆盖率一行；`docs/known-issues.md` 未动（按指示不改登记状态） |
| + | 重新定位的低覆盖文件 | done | `tests/test_cli_helpers.py`（brief / config_cli / prompts）、`tests/test_views.py` |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | Pass | `uv run python -m compileall -q tests`（仓库未配置 lint / typecheck） |
| Unit + E2E | Pass | `uv run pytest` → 1756 passed，约 34 s（基线约 30 s） |
| Coverage gate | Pass | `uv run pytest --cov` → `Required test coverage of 80.0% reached. Total coverage: 93.87%`，约 35–37 s |
| 隔离 | Pass | 跑完后 `~/.aicut`、`~/Movies/JianyingPro`、`~/Library/Logs/剪辑台` 无新文件；钥匙串由 conftest `AI_CUT_SECRETS=file` 隔离；云端全部打桩 |

## Files Changed

| File | Action |
|---|---|
| `pyproject.toml` | UPDATE（dev 组 `pytest-cov>=6`；`[tool.coverage.run]` / `[tool.coverage.report]`） |
| `uv.lock` | UPDATE（`uv add` 生成：coverage 7.16.2、pytest-cov 7.1.0） |
| `.gitignore` | UPDATE（`.coverage`、`.coverage.*`、`htmlcov/`） |
| `tests/test_packaging.py` | UPDATE（门槛 / 统计范围 / 不进 addopts / gitignore 守卫） |
| `tests/test_proc.py` | UPDATE（两条恒真断言 → 5 条精确断言 + MEIPASS / PATH 幂等） |
| `tests/test_e2e_draft.py` | CREATE |
| `tests/test_app_main.py` | CREATE |
| `tests/test_cli_helpers.py` | CREATE |
| `tests/test_views.py` | CREATE |
| `CLAUDE.md` | UPDATE（命令节加覆盖率一行） |

## Deviations from Plan
1. **基线已变**：TOTAL 已是 92%；plan 列出的 4 个 0% 脚本中 3 个（format_transcript / junk_detect / render_preview）及 build_documentary 已在 M6–M8 补测，Task 4–7 不再重做；改为重新定位当前最低的 `brief` / `config_cli` / `prompts` / `gui/views`（KI-55 / KI-54 拆出的新模块）。
2. **KI-77 已修**（`ef3c020`），plan 中的 strict-xfail 钉住用例不再需要。
3. **E2E 适配新预检**：LLM 打桩点从 `understand_text/summarize/questions.DeepSeekClient` 改为 `aicut.DeepSeekClient`（现在经 `aicut.metered` → `usage.MeteredClient` 计量并查预算）；断言用量账本按成功调用记账；E2E 里把 `encode._PREFLIGHT` 置空，真跑一次 VideoToolbox 预检（conftest 默认直接放行）；磁盘余量检查真跑。
4. **E2E 加强**：新增「未确认外发告知 → prepare 退出 1、零云端请求、未抽音轨」用例；打包路径用例里先用漏掉★段的手写 `shots.json` 证明 build 在切片前拒绝（GL-25），再删掉它正常出片。
5. **开发路径仍用 `--no-draft`**：原因变了——`ensure_jy_python()` 在 uv 环境里已直接用当前解释器（KI-34，不再联网 pip），但子进程里的 `jianying_running`（真实 pgrep）仍无法打桩。
6. **提交归属异常（需知悉）**：本里程碑的 `.gitignore`、`pyproject.toml`、`uv.lock`、`tests/test_packaging.py`、`tests/test_proc.py` 改动被并行的 M11 agent 一并提交进了 `68fc214 docs: resolve KI-41 open question`。本 agent 未执行任何 git add / commit，也未改写历史；其余 M10 文件（4 个新测试文件 + `CLAUDE.md`）仍未提交。

## Product Bugs Found / Fixed
无。所有新测试在现有产品代码上直接通过（均做过变异自检，确认不是恒真断言）。

## Next Steps
- [ ] 主流程提交剩余文件（`tests/test_e2e_draft.py`、`tests/test_app_main.py`、`tests/test_cli_helpers.py`、`tests/test_views.py`、`CLAUDE.md`），并在登记册更新 KI-38 / KI-39

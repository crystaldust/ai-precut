# ai-cut

AI 粗剪工具：素材 → 三路分析 → 片段浏览 → 覆盖式选段 → 剪映工程。脚本式 Python 仓库（`[tool.uv] package = false`）。

## 命令

- 环境：`uv python install 3.12 && uv sync --group dev`（Python 3.11–3.12）
- 测试：`uv run pytest`
- CLI：`uv run python aicut.py list|new|run|status|build`
- 桌面壳（开发）：`uv run python app/main.py`
- 浏览器版剪辑台：`python3 gui/server.py --open`
- 打包 macOS App：`./packaging/build_app.sh` → `dist/AI粗剪.app`（spec 为 `packaging/ai-cut.spec`）
- Lint / 类型检查：未配置

## 工作流：优先用 ECC 插件命令

日常工程任务尽量通过 ECC 插件（`ecc@ecc`）提供的命令完成，不要绕开它们直接手写。下表只是常用对照，不限于这些：

| 任务 | 命令 |
|---|---|
| 修 bug | `/ecc:orch-fix-defect` |
| 新功能 | `/ecc:orch-add-feature` |
| 改既有功能的行为 | `/ecc:orch-change-feature` |
| 重构（行为不变） | `/ecc:orch-refine-code` |
| 代码审查 | `/ecc:code-review`、`/ecc:python-review` |
| 构建 / 打包报错 | `/ecc:build-fix` |
| 补测试覆盖 | `/ecc:test-coverage` |
| 计划 | `/ecc:plan` |

没有合适的命令时，再用对应的 ECC agent（如 `ecc:python-reviewer`、`ecc:tdd-guide`）。
命令流程走完（测试通过、审查无 CRITICAL/HIGH）之后，才提交代码。

## 备注

- `projects/`、`dist/`、`demo/`、`vendor/`、`build/` 是可重建产物，不入库
- `vendor/bin/ffmpeg` 由 `build_app.sh` 首次运行时下载

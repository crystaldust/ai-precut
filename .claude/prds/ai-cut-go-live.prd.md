# AI 粗剪工具 · 首批上线

> 由 `/ecc:plan-prd` 从 [docs/PRD-AI粗剪工具.md](../../docs/PRD-AI粗剪工具.md) v1.1 转换。完整需求以原 PRD 为准；本文件只承载**问题、范围与交付里程碑**，实现细节交给 `/ecc:prp-plan`。
> 范围来源：[go-live-blockers.md](../../docs/go-live-blockers.md)（GL）与 [known-issues.md](../../docs/known-issues.md)（KI）。不在这两份登记册里的东西不做。

## Problem

剪辑师处理一条 60 分钟现场素材、产出 3 分钟成片要 4 小时；上一版自动流程「把重要的对话删掉了」。ai-cut 的核心功能已在开发机跑通，但 2026-10-19 全面审查判定**不能交付**（生产就绪 30/100）：用户机器上转写必失败、本地服务可被任意网页调用、必留内容会被静默丢弃、坏草稿会被当成功交付。

## Evidence

- 《九月一号》复盘：130/140 段被丢弃，其中 24 段含钱/合同/退费/就业/年龄信息（PRD §1.2）。
- 剪辑师 2026-10-18 实测：macOS 与 Windows 剪映均能打开程序生成的草稿（PRD §9）。
- 全面审查报告 2026-10-19：23 个上线阻断项、44 个已知问题，均有代码位置。

## Users

- **Primary**：1–2 人工作室的剪辑师，非技术背景，会用剪映，不懂命令行，用 Apple Silicon Mac；成片要在 Mac 或 Windows 剪映里精剪。
- **Not for**：Intel Mac 用户；需要全自动成片的人；需要签名公证安装包的企业分发场景。

## Hypothesis

我们相信**一个能在干净 Mac 上独立跑通、且保证必留内容进片的粗剪 App**，能把剪辑师的人工时间从 4 小时压到 20 分钟。
当首批剪辑师用真实素材走完全流程、「重要内容是否丢失」满意度 ≥ 80%、剪映工程打开成功率 ≥ 95% 时，我们就是对的。

## Success Metrics

| Metric | Target | How measured |
|---|---|---|
| 放行检查 | 通过 | 干净 Mac（新账户、无 brew/Node）+ 54 分钟素材：首次打开 → 填 Key → 分析 → 导出 Mac + Windows → 剪映打开并播放 |
| 必留进片率 | 100% | 选段单测 + 真实项目校验（FR-7） |
| 单条成片人工时间 | ≤ 20 分钟 | 上线后 4 周计时（PRD §10） |
| 剪映工程打开成功率 | ≥ 95% | 上线后 4 周统计（PRD §10） |
| 测试覆盖率 | ≥ 80% | `uv run pytest --cov`（KI-38） |

## Scope

**MVP** — 关闭全部 GL-01..GL-23，通过放行检查。

**Out of scope**
- Intel / universal2 构建、Developer ID 签名与公证 — PRD §13 已决定不做
- 自动更新 — PRD §8 列为 P2
- 登记册以外的新功能 — 不自行扩大范围
- App 本身在 Windows 上运行（安装包、WebView2、路径编码）— 待确认，见 Open Questions

## Delivery Milestones
<!-- Status: pending | in-progress | complete -->

| # | Milestone | Outcome | Items | Status | Plan |
|---|---|---|---|---|---|
| 1 | 本地服务安全，编辑不丢 | 任意网页无法调用剪辑台 API；路径穿越与 XSS 被拦截；保存不会被并发或坏请求覆盖；中文项目名可播放 | GL-05 GL-06 GL-07 GL-18 GL-21 GL-23 | complete | [plan](../PRPs/plans/m1-local-server-hardening.plan.md) · [report](../PRPs/reports/m1-local-server-hardening-report.md) · `624e979` |
| 2 | 必留内容不丢 | 必留段 100% 进片；LLM 失败或待定超限时明确报错，不静默降级 | GL-08 GL-09 GL-24 GL-25 | complete | [plan](../PRPs/plans/m2-must-keep-guarantee.plan.md) · [report](../PRPs/reports/m2-must-keep-guarantee-report.md) · `ebabfcc` |
| 3 | 交付物可信 | 草稿导出不崩；校验 FAIL 不交付；注册原子；中断后不复用半成品 | GL-10 GL-11 GL-12 GL-13 GL-15 | complete | [plan](../PRPs/plans/m3-trustworthy-output.plan.md) · [report](../PRPs/reports/m3-trustworthy-output-report.md) · `ef3899f` |
| 4 | GUI 独立完成全流程 | 剪辑师在 GUI 内配置 Key（含外发告知）、导出 Mac + Windows 草稿；任务互斥；失败可关闭、可重试 | GL-02 GL-14 GL-16 GL-17 GL-20 GL-22 | complete | [plan](../PRPs/plans/m4-gui-full-flow.plan.md) · [report](../PRPs/reports/m4-gui-full-flow-report.md) · `6f8ba02` |
| 5 | 干净 Mac 可装可用 | 转写不依赖 Node；ffmpeg 为 LGPL + VideoToolbox 并校验哈希、附许可声明；日志落盘可导诊断包；交付说明适配 macOS 15 | GL-01 GL-03 GL-04 GL-19 | complete（待放行检查） | [plan](../PRPs/plans/m5-clean-mac-ready.plan.md) · [report](../PRPs/reports/m5-clean-mac-ready-report.md) · `ac3f15c` |
| 6 | 成片质量 | 字幕、hook、必留原话、答题规则、情绪权重等按设计生效 | KI-01..KI-12 KI-58 KI-73 | complete | [plan](../PRPs/plans/m6-cut-quality.plan.md) · [report](../PRPs/reports/m6-cut-quality-report.md) · `bc3c705` |
| 7 | 渲染与导出健壮 | 特殊字幕、无音轨、模板缺失等情况不崩且如实报错 | KI-13..KI-18 KI-59 KI-64 KI-76 KI-78 | complete | [plan](../PRPs/plans/m7-render-export-robust.plan.md) · [report](../PRPs/reports/m7-render-export-robust-report.md) · `71e44e7` |
| 8 | 失败可见 | ffmpeg/LLM/JSON 失败不再伪装成成功 | KI-19..KI-27 KI-48 KI-49 KI-56 KI-66 KI-77 | complete | [plan](../PRPs/plans/m8-visible-failures.plan.md) · [report](../PRPs/reports/m8-visible-failures-report.md) · `ef3c020` |
| 9 | 密钥与运维 | 密钥文件权限与脱敏正确；HTTP 边界校验；费用、进程、启动脚本、版本号可控 | KI-28..KI-37 KI-50..KI-55 KI-57 KI-61..KI-63 KI-65 KI-67..KI-72 KI-74 KI-75 KI-83 KI-84 KI-86 KI-87 | complete | [plan](../PRPs/plans/m9-secrets-ops.plan.md) · [report](../PRPs/reports/m9-secrets-ops-report.md) · `9017287` |
| 10 | 测试达标 | 覆盖率 ≥ 80%；有素材 → 剪映草稿的端到端测试 | KI-38 KI-39 | complete | [plan](../PRPs/plans/m10-test-coverage.plan.md) · [report](../PRPs/reports/m10-test-coverage-report.md) · `25c76fc` |
| 11 | 文档一致 | 指标可检验、PLAN 与 PRD 对齐、术语统一 | KI-40..KI-44 | complete | [plan](../PRPs/plans/m11-docs-consistency.plan.md) · [report](../PRPs/reports/m11-docs-consistency-report.md) · `83d2a1a` |
| 12 | 收尾 | 相对 staging 路径可用；同机其他用户拿不到 token；旧版本切片不被新版本改动 | KI-80 KI-88 KI-89 | complete | [plan](../PRPs/plans/m12-wrapup.plan.md) · [report](../PRPs/reports/m12-wrapup-report.md) |

## Open Questions

- [ ] App 本身是否需要在 Windows 上运行？当前理解：只需导出的草稿能在 Windows 剪映打开（GL-14 覆盖）；若需要，另增 Windows 打包类阻断项。
- [x] KI-41：已决定降为 P2，将来本地实现（PRD v1.2）。
- [x] KI-40：样本与测量方法、FR-5 验收已在 PRD v1.2 修订。

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 火山引擎 HTTP API 与 mediakit-cli 行为不一致（GL-01） | 中 | 高 | 用现有 asr 产物做回归对比；保留断点续查 |
| LGPL ffmpeg 无 libx264，VideoToolbox 画质/参数差异 | 中 | 中 | 对预览片与切片做前后对比；码率显式设置 |
| 剪映升级改格式 | 中 | 高 | 黄金草稿回归（KI-17） |
| 改动面大、覆盖率仅 51%，回归风险高 | 高 | 高 | 每个里程碑先补回归测试（TDD），再改代码 |

---
*Status: ALL MILESTONES COMPLETE (code) — 待人工放行检查见 docs/PROGRESS.md。原 APPROVED SCOPE — 里程碑 1–5 为上线阻断，6–11 为排期修复。实现计划见 `.claude/PRPs/plans/`。*

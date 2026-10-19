# Implementation Report: 里程碑 6「成片质量」（KI-01..KI-12 / KI-58 / KI-73）

## Summary
选段与理解里「设计上该生效」的规则现在真的生效了：
- **字幕**：镜头字幕不再一律截前 28 字；按最终出入点生成——整句，截短的镜头只留大半落在镜头里的分句（`work/segments.json` 的 `lines` 时间码），没有分句时按时长比例截（`pipeline/shot_sub.py`，KI-01）。
- **开场 / 结尾**：hook 永不被挪到片尾；结尾取时间上**最后**一个命中；关键词收窄（D4）；`emotion` 只看音量（≥ 中位 +1dB 的最响非 hook 镜头）；支持 `info`；`silence` 与「找不到合适镜头」都进警告（KI-02）。旧版存下的中文 ending / pacing（如「微信缴费完成」「紧凑快剪」）在选段时也会归一。
- **必留原话**：按换行 /「；」切成原话，整句（去标点）匹配；找不到才退回逗号碎片（≥4 字，短碎片给警告）；每条原话 / 碎片只强制时间上最早的 1 段（KI-03）。
- **确认页答案**：规则按「题 id → label」查（跨题同名 label 不再互相覆盖）；`pacing` 看 value（tight → 单镜 12s，必留不受限）；`focus` main/narrator → 说话总时长最多的人每段 +2 分，群像不加分，其他值警告「无法对应到说话人」；兜底题的关键信息选项改绑 `must_lines`；同题截断后重名的 label 去重（KI-04）。
- **确认页入口与重新选段**：主界面新增「确认与提问」；「保存并确认」后服务端自动起 `select` 任务，确认页轮询显示进度 / 完成 / 失败原因（最后一行 `[x]`/`[!]`）/ 冲突原因（答案已保存）（KI-05，`gui/confirm.py`）。
- **情绪信号**：scored 段带 `signals`；旧项目在 select 时从 `segments_audio.json` 回填（只补缺的段）（KI-06）。
- **必留话题口径**：词表 / 占比 / 最少关键句数外置到预设 `must_topic`，代码兜底收窄；先算 `must_names` 再判档，档位与 `topics[].must` 同一口径（KI-07 / KI-58）。
- **抢话**：真重叠 → 可用；「换人且停顿 <0.25s」代理信号还要求本句 <30s 且音量 ≥ 中位 +1dB（KI-08）。
- **话题分段**：每 120 句一窗、`max_tokens=4000`、逐窗形状校验 + 重试 2 次（不可重试错误立即停），仍失败抛 `LLMError`（含「第 k/n 段」）；`key_info:"false"` 判 False；`info_type` 不在枚举 → 事实陈述；合并输出形状不对走 `_cap_topics`（KI-09）。
- **`--model`**：`understand_text.run` / `summarize.run` 用 `DeepSeekClient(model=model)`（KI-10）。
- **缓存绑定入出点**：预览指纹 = timeline + 每镜 `clip_key`；`build_documentary.py` 切片也走 manifest（KI-11）。
- **人工裁决锚点**：写入记「原文哈希 + 起点」；读取时锚点对不上按原文重定位（同文取起点最近），找不到不套用并在选段警告里列出；写入时把已有裁决挪到当前 id，重新标某句不会继承别的句子的旧字段（KI-12）。
- **预览字体**：首选 `Hiragino Sans GB.ttc`（简体 W3），一次 build 只选一次字体（KI-73）。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | — | 高（全部自动化覆盖 + 真实项目离线对比；GUI / 渲染手动清单待做） |
| Files Changed | 31 | 33（源：新建 3、修改 13 + 1 预设 + 3 静态页；测试：新建 3、修改 12） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | `select_rules`：答案 → 规则、结尾归一 | done | 保留 M8 的 `ignored_answers`（偏差 2） |
| 2 | classify：信号 / 口径 / 词表外置 / 抢话 | done | `aicut.cmd_score` 净行数不增 |
| 3 | 字幕整句 + 随镜头裁剪 | done | 计划用例 1 处算术有误，已改（偏差 6） |
| 4 | hook 与结尾 | done | 另加「找不到候选」警告（偏差 4） |
| 5 | 必留原话精确命中 | done | 文案常量名调整（偏差 3） |
| 6 | focus / pacing 生效 | done | select.run 规则来源保持 M8 语义（偏差 1） |
| 7 | 旧项目信号回填 + 失效裁决警告 | done | |
| 8 | 话题分段分窗 + 脏输出 | done | 漏掉的句子并入本窗最后一个话题（偏差 7） |
| 9 | `--model` 生效 | done | |
| 10 | 人工裁决锚点 | done | 写入时整体重定位（偏差 5） |
| 11 | 预览 / 切片缓存绑定入出点 | done | |
| 12 | 预览字幕字体 | done | |
| 13 | 确认页入口 + 确认后重新选段 | done | 保存逻辑搬到 `gui/confirm.py`（payload 已在 M8 的 `gui/payloads.py`） |
| 14 | 收尾 | done | `calibrate.html` 文案（D5）；登记册状态按指示未改 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | Pass | 无 lint/typecheck 配置；`python -m compileall -q aicut.py pipeline gui` 无输出；页面内联脚本 `node --check` 通过 |
| Unit Tests | Pass | 每个 KI 均先 RED 后 GREEN |
| Full Suite | Pass | `uv run pytest`：1288 → **1406 passed** |
| Build | N/A | 未打包 |
| Integration | Pass | 真实 ffmpeg 渲染用例（Hiragino Sans GB，路径含空格）通过；真实项目离线对比见下 |
| Edge Cases | Pass | 空文本 / 零长段 / 无 segments.json / 无音频文件 / 300 句分窗 / `"false"` / answers 非对象 / 并发冲突 / 失效裁决 |

行数约束：`aicut.py` 924 → 915；`gui/server.py` 751 → 740；`pipeline/select.py` 602 → 591。

## 真实项目离线对比（`projects/2026-09-01_活动`，副本在 scratchpad，只跑 score + select，不调云接口）

| 指标 | 修前（HEAD 4afa5e2） | 修后 |
|---|---|---|
| 三档 废片/待定/可用 | 36 / 39 / 65 | 40 / 40 / 60 |
| 必留话题 | 14 / 19 | **12 / 19** |
| 「出现抢话/被打断」理由 | 5 句（全是 30s+ 假边界） | **0** |
| 选段镜数 / 总时长 | 17 镜 / 177.1s（目标 175） | 20 镜 / 175.1s |
| 最长单镜（答案 pacing=紧凑） | 25.0s（tight 没生效） | **12.0s** |
| 字幕平均 / 最长字数 | 28.0 / 28（一律截断） | 43.0 / 70（整句或镜头内分句） |
| 字幕 = 整句原文 | 0 / 17 | 6 / 20（其余 14 镜是被截短的镜头，只含镜头内分句） |
| 强制原话（「找不到工作不白学吗」） | S039 | S039 |
| 首镜 | S024（无 role） | S130（role=hook） |
| 末镜（存的 ending=「微信缴费完成」） | S139（ending 没生效） | **S094「…甲方签字日期…」** |
| 新警告 | 无 | 「主角『学员与家长』无法对应到说话人，这条偏好没有生效」 |

必留保证（GL-08）抽查：同一副本里给 S005 / S032 / S077 / S120 打★（S120 还人工判废片），修前修后 4 段都**整段**进片（S077 34.9s 不受 tight 12s 限制）。

## Files Changed

| File | Action | 说明 |
|---|---|---|
| `pipeline/select_rules.py` | CREATED | 答案 → 规则、ending/pacing 归一、必留原话解析与命中、max_shot、focus 映射 |
| `pipeline/shot_sub.py` | CREATED | 镜头字幕 |
| `gui/confirm.py` | CREATED | 保存答案 + 确认后起 select 任务 |
| `pipeline/select.py` | UPDATED | 接入以上；`_rules`/`_norm_ending` 改为别名；hook / 结尾重写；回填 signals、分句、失效裁决警告 |
| `pipeline/classify.py` | UPDATED | `attach_signals` / `load_audio_signals` / `must_topic_config` / `_is_interrupt`；口径先定 |
| `pipeline/questions.py` | UPDATED | `must_lines` kind、label 去重、兜底绑原话、提示词限定 focus/ending/pacing |
| `pipeline/understand_text.py` | UPDATED | 分窗 + 重试、`_as_bool`、`INFO_TYPES`、合并校验、`model` |
| `pipeline/summarize.py` | UPDATED | `model` |
| `pipeline/review.py` | UPDATED | 锚点、`resolve` / `stale_ids`、写入时重定位 |
| `pipeline/build_documentary.py` | UPDATED | `clip_key` / `preview_fingerprint` / 切片 manifest |
| `pipeline/render_preview.py` | UPDATED | 字体候选与只选一次 |
| `aicut.py` | UPDATED | score 传预设 `must_topic`；build 用指纹；删本地 `clip_key` 与 `hashlib` |
| `gui/server.py` | UPDATED | `/api/confirm/answers` 委托 `gui/confirm.py`；去掉不再用的 `questions` 导入 |
| `gui/static/index.html` / `confirm.html` / `calibrate.html` | UPDATED | 入口按钮、任务轮询、原话提示 |
| `presets/纪实3min.json` | UPDATED | `must_topic` |
| `tests/test_select_rules.py` / `test_shot_sub.py` / `test_confirm_flow.py` | CREATED | |
| `tests/test_select.py` / `test_classify.py` / `test_questions.py` / `test_understand_text.py` / `test_summarize.py` / `test_review.py` / `test_build_documentary.py` / `test_aicut_build.py` / `test_aicut_must_keep.py` / `test_render_preview.py` | UPDATED | 追加用例 |
| `tests/test_server_corrupt.py` | UPDATED | 既有 `test_confirm_answers_post_normalized` 发 `confirmed:true`，现在会起选段任务 → 打桩 `jobs.job_command`，免得测试里跑真实子进程 |

## Deviations from Plan

1. **select.run 规则来源保持 M8 语义**：计划要求「有 questions 就一律按答案重算」，但 M8 已落地 `_current_rules`（答案都对得上 → 用已存规则；有对不上的 → 重算 + 警告），且 `test_m8_review.py::test_fresh_stored_rules_still_used` 断言已存规则优先。两者不能共存，保留 M8 行为，未写计划里的 `test_run_recomputes_rules_when_questions_exist`。补偿：`select()` 入口把 ending / pacing 归一（旧版存下的「微信缴费完成」「紧凑快剪」现在生效，真实项目已验证）；确认页每次保存都用新的 `rules_from_answers` 重算。残留：旧版按全局 label 算出的跨题串规则要等剪辑师再保存一次才更正。
2. **`rules_from_answers` 保留 `ignored_answers`**（M8 KI-23）；对不上题 id 的答案也记为 ignored（计划写的是「忽略」）。
3. **原话文案常量**：M8 已有 `MUST_LINE_TOO_SHORT`（句子不足 1.5 秒），计划里的同名常量改名为 `select_rules.MUST_LINE_FRAGMENT_SHORT`（碎片 <4 字）；「找不到」用 `select_rules.MUST_LINE_NOT_FOUND`（保留「找不到」字样，M8 用例不变），删去 `select.MUST_LINE_UNMATCHED`。整句匹配不设字数下限（「退费」这类短原话照样能找）。
4. **结尾找不到候选给警告**（`ENDING_NOT_FOUND_WARNING`）：计划未要求，属「不静默降级」；hook 已在首位时也标 `role=hook`（以前不标，结尾挪动时无法识别它）。
5. **裁决写入时整体重定位**：计划只在 `set_*` 里记锚点；实测发现两个错配场景（重新标 S001 会继承旧句子的档位；改重定位后的 S003 会留下一条失效的 S001），所以 `_write` 先把已有裁决挪到当前 id、同 id 的失效裁决不被继承。没有锚点且 id 已不存在的旧裁决现在也算失效（以前静默不套用）。
6. **计划用例算术**：`test_line_counted_when_mostly_inside` 镜头 `[0,4.6]` 下第二句覆盖 1.6/3=53%（计划写 <50%），改为 `[0,4.4]`；`test_max_shot_clipped_sub_trimmed` 避开恰好 50% 的边界。
7. **话题分窗兜底**：漏掉的句子并入**本窗**最后一个话题（保持时间局部性）；一窗里没有任何有效话题 → 当形状错误重试。
8. **KI-10 范围**：CLI 只有 `text` 子命令有 `--model`，`summary` 没有该参数（未新增 CLI 参数，见新发现缺陷）。
9. **登记册**：按指示未改 `docs/known-issues.md` 状态，未提交。

## Issues Encountered
- GateGuard 拦了一次 scratchpad 里的 `rm -rf`（重建对比目录），改为新目录名避免删除。
- 最初写的 `test_scored_segments_carry_audio_signals` 等 classify 用例在实现前 RED；`test_must_keep_invariant_randomized_with_m6_rules` 在实现前就是绿的（新规则字段旧代码直接忽略），实现后仍绿，作为 GL-08 回归护栏保留。

## 新发现缺陷（未修，登记候选）
- `aicut.py:880` `summary` 子命令没有 `--model`（`aicut.py:360` 调 `summarize.run` 不传 model）：KI-10 修好的是函数层，CLI 只能对 `text` 指定模型。
- `pipeline/select.py:519` `_current_rules`：答案都对得上时直接用已存规则，旧版 `_rules` 算出的跨题同名 label 串规则会一直沿用到剪辑师重新保存（见偏差 1）。
- `pipeline/review.py:114` `clear()`：按存储键删除；裁决被重定位后浏览页显示的是新 id，`clear(新 id)` 删不到（目前 GUI / CLI 无调用方，只有测试用）。
- 真实项目 `projects/2026-09-01_活动/work/questions.json` 是旧提示词生成的：focus 选项值是「学员与家长」等自由文本，M6 后只会给警告不生效；需要重新生成决策问题（已作答的不会自动重生成，见 `questions.reusable`）。

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `tests/test_select_rules.py` | 22 | KI-02/03/04 规则层 |
| `tests/test_shot_sub.py` | 7 | KI-01 |
| `tests/test_confirm_flow.py` | 8 | KI-05、D5 文案 |
| `tests/test_select.py` | +25 | KI-01/02/03/04/06/12 接线、GL-08 随机不变量（含 M6 规则） |
| `tests/test_classify.py` | +11 | KI-06/07/08/58 |
| `tests/test_understand_text.py` | +19（含参数化） | KI-09/10 |
| `tests/test_review.py` | +13 | KI-12 |
| 其它（questions / summarize / build_documentary / aicut_build / aicut_must_keep / render_preview） | +12 | KI-04/07/10/11/73 |

## 待手动验证
- [ ] GUI：主界面「确认与提问」打开确认页；「保存并确认」→ 状态栏「正在按你的答案重新选段…」→「选段完成」；另一任务在跑时显示「答案已保存，但没能开始重新选段：…」；回到主界面分镜表已更新（主界面靠下一次刷新显示，不会自动推送）。
- [ ] 预览片字幕为冬青黑体简体（`build <项目> --no-draft`）；整句字幕拆卡后的观感（卡更多）。
- [ ] `build --version vN` 两次，中间在 `shots.json` 平移某镜入出点 → 第二次重渲染（不是「预览片无变化」）。
- [ ] 剪辑偏好填「嗯，对，就九千八」/ 不存在的话 → 只多 1 个强制镜头 / 黄条提示找不到。
- [ ] 浏览页标几条裁决后重新处理素材 → 黄条「N 条人工裁决…已不套用」，没有套到别的句子上。
- [ ] `aicut.py text <项目> --model deepseek-reasoner`（需真实 Key，可选）。
- [ ] 真实项目重新生成决策问题后，focus 选项应只出现 main / ensemble。

## Next Steps
- [ ] 代码审查（python-reviewer）后提交；`docs/known-issues.md` 各 KI 由负责人填提交号。

## 审查修复（代码审查 1 HIGH + 1 MEDIUM + LOW + KI-85）

全部按 TDD 修复：先写失败用例，确认 RED 后再改实现。`uv run pytest`：1406 → **1426 passed**。行数：`aicut.py` 915（未动）、`pipeline/select.py` 629、`gui/server.py` 740。

| # | 级别 | 问题 | 修复 |
|---|---|---|---|
| 1 | HIGH | 强制原话镜头总从句首截，原话落在长句后半时被截掉且无警告；已入选但被截短的镜头不检查 | `select_rules.resolve_must_lines` 改为返回命中 `[{id, line, start, end}]`：时间范围按分句时间码算（没有时间码时按字数比例）。`select._forced_bounds` 保证镜头覆盖原话：在单镜上限内尽量从更早的分句起头；原话本身超过上限时这一镜不受上限（与必留一致）。已入选但没覆盖到原话的镜头换成强制镜头。最后由 `_uncovered_lines` 再核对一遍，没覆盖到的报 `MUST_LINE_NOT_COVERED`（警告里写出原话）。`MUST_LINE_TOO_SHORT` 也改回写原话 |
| 2 | MEDIUM | 裁决重定位：逐条贪心会抢走别人更近的匹配；没有距离上限；同 id 同文的快速通道不看起点 | `review._resolve_keys` 改为：所有带锚点的裁决按「到锚点的距离」全局排序后分配（同距离优先同 id）；超过 `RELOCATE_MAX_SECONDS = 30` 秒的算失效并给警告；去掉不看起点的快速通道。没有锚点的旧裁决仍按 id 套用（D9） |
| 3 | LOW | `_proportional` 句中截取有误 | 按时间位置截中间对应的那段字 |
| 4 | LOW | 判断「整句」的容差过严 | 改为 `WHOLE_TOLERANCE = 0.01`（与出入点两位小数一致） |
| 5 | LOW | `select._rules` / `_norm_ending` 兼容别名 | 测试迁到 `select_rules` 后删除别名 |
| 6 | LOW | 话题分窗 | 最后一窗不足 `TOPIC_MIN_TAIL = 20` 句时并入前一窗，不单独调用；跨窗口边界的同名相邻话题合并 |
| 7 | LOW | 规则细节 | `norm_pacing` 识别否定说法：「紧/快」前 3 个字内有「不/别/勿/没…」就不算紧凑（如「不要太紧」）；单字原话给警告并忽略；逗号碎片只命中一部分时，没找到的碎片单独给警告 |
| KI-85 | — | `review.clear` 按存储时的 id 删除 | 先按当前 id 找到对应的裁决再删；写入时同 id 的失效裁决（含同文但起点超出上限的）不再被新裁决继承 |

新增 / 调整的测试：
- `test_select.py`：
  - 原话在长句末尾（tight / normal 两种节奏）。
  - 原话所在句子已入选但被截短。
  - 原话比单镜上限还长。
  - 原话没被覆盖时给警告。
  - `test_tight_pacing_caps_forced_line_shot` 改为同时断言原话在字幕里。
- `test_select_rules.py`：命中区间（有分句 / 按比例）、单字原话、部分碎片、否定节奏。
- `test_review.py`：全局分配、距离上限、同 id 远距离、按当前 id 清除（KI-85）、不继承远处同文的失效裁决。
- `test_shot_sub.py`：取两位小数后仍算整句、句中按比例截。
- `test_understand_text.py`：尾窗并入、跨窗同名合并。

审查给的复现脚本 `rv/ml.py`、`ov.py`、`sub.py` 现在输出都符合预期：
- `ml.py`：tight / normal 下都输出镜头 20–30s，字幕为「九千八包含所有耗材」。
- `ov.py`：①「对。」那条裁决归 S010→S011，S003 判失效；② 远在 3000s 外的同文句子判失效；④ 同 id 同文但起点远的，改给起点最近的 S011。

用真实项目副本重跑：选段结果与上表一致（20 镜 / 175.1s / 最长单镜 12s）；强制原话镜头 S039（893.68–905.68s）的字幕包含「找不到工作不白学吗」。

新增观察（未修）：英文分句拼接时没有空格（`pipeline/format_transcript.py:116` 用 `"".join` 拼 `seg["text"]`，字幕会出现 "world.good"）。这是既有行为，中文素材不受影响。

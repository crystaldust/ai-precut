# 上线阻断项（GL）

> 交给第一批剪辑师前必须关闭的问题。来源：2026-10-19 全面审查（PRD/PLAN 双审 + 代码审查 + 静默失败 + 测试覆盖 + 生产就绪审计）。
> 修复走 `/ecc:orch-fix-defect`（带回归测试）；关闭时在「状态」填提交号。
> 放行标准：在一台干净 Mac（新账户、无 brew、无 Node）上，用 54 分钟素材走完「首次打开 → 填 Key → 分析 → 导出（Mac + Windows）→ 剪映打开并播放」。

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| GL-01 | 云端 ASR 依赖开发机上的 Node 版 `mediakit-cli`，App 未打包 → 用户机器转写必失败。改为 Python 直连 HTTP API（同 `llm.py` 写法） | `pipeline/cloud.py:39,72`；`packaging/ai-cut.spec` | fixed `ac3f15c`（待人工验证：真账号转写 / 干净 Mac） |
| GL-02 | GUI 无 API Key 配置入口（只能 CLI `config set`）；首次使用需告知两条外发数据流（PRD §7）；无 DeepSeek Key 时 prepare 静默跳过文本分析 | `aicut.py:591-594, 658-684`；`gui/server.py` | fixed `6f8ba02` |
| GL-03 | 交付说明仍写「右键→打开」，macOS 15+ 已失效。改为「系统设置 → 隐私与安全性 → 仍要打开」（不做签名公证，PRD §13） | `docs/PACKAGING.md:56`；`dist/` 内使用说明 | fixed `ac3f15c`（待人工验证：真账号转写 / 干净 Mac） |
| GL-04 | 内置 ffmpeg 为 GPL 构建（`--enable-gpl --enable-libx264`）。换 LGPL 构建，`libx264` 全部改 `h264_videotoolbox`；下载加 `curl -f` + SHA256 校验；随包附 THIRD-PARTY-NOTICES | `packaging/build_app.sh:13-17`；`aicut.py:287,447`；`pipeline/render_preview.py:97`；`pipeline/build_documentary.py` | fixed `ac3f15c`（待人工验证：真账号转写 / 干净 Mac） |
| GL-05 | 本地服务无 Host/Origin/token 校验、POST 不验 Content-Type → 任意网页可跨站调用全部 API，DNS rebinding 可读数据 | `gui/server.py:323-330, 380-622` | fixed `624e979` |
| GL-06 | 路径穿越：`version` 参数可在任意位置建目录写文件；镜头 `id` 可让 ffmpeg 覆盖任意 .mp4；`project` 未经校验传给 aicut | `gui/server.py:530-556` → `aicut.py:437-443, 543-545` | fixed `624e979` |
| GL-07 | XSS：LLM / 转写内容直接 innerHTML；`confirm.html` 内联 JS 拼接未完整转义 | `gui/static/browse.html:116-175`；`index.html:186,419,429,498`；`confirm.html:92,99` | fixed `624e979` |
| GL-08 | 「必留进片率 100%」无保证：话题预算为 0/用尽、`_trim`、exclude 都会丢 must_keep 段 | `pipeline/select.py:129-133, 173, 183-187` | fixed `ebabfcc` |
| GL-09 | 必留/关键信息被静默丢弃：LLM 标注批次失败或漏 id 时该批句子被判废片且流程显示成功；待定超限时把必留话题段降为废片 | `pipeline/understand_text.py:167-181`；`pipeline/classify.py:56-59, 87-96` | fixed `ebabfcc` |
| GL-10 | 导出剪映草稿崩溃：片头字幕卡与普通字幕同轨重叠抛 `SegmentOverlap`；`card.at` 超总时长产生负时长 | `pipeline/to_jianying.py:99-113`；`pipeline/build_documentary.py:103-108` | fixed `ef3899f` |
| GL-11 | 坏草稿照样交付：校验 FAIL 也打印 `[✓]`；打包版 `run_inprocess` 丢弃 `main()` 返回值 | `aicut.py:131-140`；`pipeline/proc.py:64-69` | fixed `ef3899f` |
| GL-12 | 打包版错误信息丢失：`int(exc.code)` 遇 `sys.exit("文字")` 抛 ValueError | `pipeline/proc.py:69` | fixed `ef3899f` |
| GL-13 | 草稿注册非原子：先 move 后 register，失败留孤儿草稿且重试报「已存在」；剪映未装/改过草稿目录时直接崩 | `pipeline/to_jianying.py:246-247, 299-316` | fixed `ef3899f` |
| GL-14 | GUI 只能导出 Mac 剪映草稿，没有 Windows 导出入口（`/api/job` 只有 prepare/build）；PRD §13 要求两平台都支持 | `gui/server.py:215-251`；`gui/static/index.html` | fixed `6f8ba02` |
| GL-15 | 中断后半成品被当成完成：ffmpeg 直写最终文件，`exists()` 判完成 → 只转写前半段且计费 | `aicut.py:205-209, 284-289, 442-449`；`pipeline/build_documentary.py:80` | fixed `ef3899f` |
| GL-16 | ASR 任务失败后 `asr_task.json` 不清，3 天内重试永远失败；任务未绑定音频指纹 | `pipeline/cloud.py:148-184` | fixed `6f8ba02` |
| GL-17 | 任务无互斥/取消：同项目可并发多个任务（重复计费、互相覆盖）；冻结模式全局 `redirect_stdout`/`sys.argv` 多线程互踩；未知任务留幽灵 running | `gui/server.py:42-57, 215-295`；`pipeline/proc.py:61-67` | fixed `6f8ba02` |
| GL-18 | 保存丢数据：固定 `.tmp` 名并发保存失败（实测 200 次失败 90 次）；请求体解析失败返回 `{}` 后用空列表覆盖分镜；`overrides.json` 损坏时当空并在下次裁决时永久覆盖 | `gui/server.py:81-85, 323-330, 524-543`；`pipeline/review.py:23-67` | fixed `624e979` |
| GL-19 | 无日志落盘、无诊断包：出错后用户和开发者都拿不到信息（PRD FR-13） | 全仓无 logging；`packaging/ai-cut.spec:64`；`gui/server.py:69,302` | fixed `ac3f15c`（待人工验证：真账号转写 / 干净 Mac） |
| GL-20 | GUI 新建项目在 `.command`/开发方式启动时卡在 `input()` 永不返回，并留空目录导致重试失败 | `gui/server.py:58`；`aicut.py:162-165` | fixed `6f8ba02` |
| GL-21 | 中文/空格项目名视频全部 404（服务端未 percent-decode） | `gui/server.py` 路由；`gui/static/index.html:204,230,262,430` | fixed `624e979` |
| GL-22 | 字幕框点不进（点击冒泡触发整表重绘）；任务失败后模态层无法关闭，只能杀 App | `gui/static/index.html:344-370, 435-468` | fixed `6f8ba02` |
| GL-23 | 前端镜头 id 重复（删一个再加一个）→ 切片互相覆盖，成片重复内容 | `gui/static/index.html:388` | fixed `624e979` |
| GL-24 | 画面过暗分支把必留话题段、标注失败的待定段直接判废片（与 GL-09 同类静默丢弃） | `pipeline/classify.py:82-83` | fixed `ebabfcc` |
| GL-25 | build 不检查分镜表是否含全部必留段；GUI 手存的 `shots.json` 优先于 `shots-selected.json`，漏必留照样出片 | `aicut.py:531-536` | fixed `ebabfcc` |
| GL-26 | 界面没有步骤：选中项目后 9 个按钮全亮，未分析就能点生成成片 / 确认与提问；处理素材、生成成片各 3 个入口且效果不同；偏好 / 浏览 / 确认 3 个独立窗口互不联动（浏览页标必留不重选，生成时才被拒；确认后主页不刷新）。改为六步项目向导（PRD §4.1，[界面流程 v2](界面流程-v2.md)） | `gui/static/index.html`、`index.js`、`browse.*`、`confirm.*`、`calibrate.*` | fixed ①–④ 完成（M13，`9a705c3`..`efeb92b`）；⑤ `aa18643`；⑥ `6d812f7` |
| GL-27 | 未采用清单与一键加回（FR-8，P0）后台有数据（`selection.json` 的 `unused`），界面上没有，闸门 B 无从执行 | `gui/static/result-unused.js`；`gui/result_payload.py` | fixed `aa18643` |

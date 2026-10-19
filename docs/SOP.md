# 操作手册 · aicut 视频剪辑流水线

> 一句话：**素材丢进去 → 出一版分镜表 → 你改表 → 重出成片**。
> 机械环节（转写、切片、对齐字幕、生成工程、渲染预览）由脚本做；判断环节（选哪条、怎么排、什么情绪）由你或 AI 做，接口就是一份 `shots.json`。

---

## 一、目录长什么样

```
default-workspace/
├── aicut.py                 ← 唯一入口
├── presets/                 ← 风格预设（纪实3min / 口播60s / 探店45s / 切片30s）
├── pipeline/                ← 底层模块（切、渲染、生成草稿、转写整理、废片检测）
├── research/                ← 调研 + 草稿校验器
├── projects/
│   └── 2026-09-01_活动/
│       ├── project.json     ← 项目配置（平台/时长/预设）
│       ├── shots.json       ← ★ 分镜表：唯一需要你手改的文件
│       ├── work/            ← 中间产物（音轨、文稿、废片表、切片缓存）
│       └── output/v1 v2 …   ← 每次出片一个版本，永不覆盖
└── docs/SOP.md              ← 本文
```

## 二、五条命令

```bash
cd ~/Documents/deepseek-harness/default-workspace

# 1. 新建项目（成片想剪多长由你定：--target 秒；不写会在终端里问，回车用预设时长）
python3 aicut.py new 我的项目 --material ~/Movies/xxx.MOV --title "片名" --preset 纪实3min --target 240

# 2. 跑完整流程（已完成的环节自动跳过，不会重复花钱）
python3 aicut.py run 我的项目

# 3. 看进度
python3 aicut.py status 我的项目

# 4. 改完分镜表后重出（最常用）
python3 aicut.py build 我的项目 --version v2

# 5. 剪映开着的时候，只出预览不出草稿
python3 aicut.py build 我的项目 --no-draft

# 6. 改目标时长：只重跑选段（不转写、不调 LLM）；标了必留的句子总会整段保留，
#    必留合计超过目标时会提示「必留内容共 X，超过目标 Z」并给出建议时长
python3 aicut.py select 我的项目 --target 300
```

嫌长？加个别名：

```bash
echo "alias aicut='python3 ~/Documents/deepseek-harness/default-workspace/aicut.py'" >> ~/.zshrc
source ~/.zshrc
# 之后：aicut status 我的项目
```

## 三、我想改 X，该动哪里？（核心表）

| 你想改 | 改哪个文件 | 跑什么 | 大概耗时 |
|---|---|---|---|
| 换一句字幕 / 改错别字 | `shots.json` 里那条的 `sub` | `build --version vN` | ~1.5 分钟（渲染占大头） |
| 某个镜头长一点 / 短一点 | `shots.json` 的 `in` / `out` | `build --version vN` | ~2 分钟（只重切那一个） |
| 删一个镜头 / 换顺序 | 删/移动 `shots.json` 里的整块 | `build --version vN` | ~2 分钟 |
| 加一个镜头 | 复制一块，改 `id`/`in`/`out`/`sub` | `build --version vN` | ~2 分钟 |
| 改片头/片尾字幕卡 | `presets/<预设>.json` 的 `cards` | `build --version vN` | ~1.5 分钟 |
| 改字幕字号/位置/每行字数 | `presets/<预设>.json` 的 `subtitle` | `build --version vN` | ~1.5 分钟 |
| 换平台（抖音↔快手） | `project.json` 的 `platform` | 改 `shots.json` 后重出 | 看改动量 |
| 换整体风格 | `project.json` 的 `preset` | 改 `shots.json` 后重出 | 看改动量 |
| 重新转写（换素材/加素材） | — | `transcribe` → `brief` → 改表 → `build` | 素材时长 × ~0.1 |
| 换素材 | 新建项目 | `new` → `run` | 全流程 |

**关键理解：`work/clips/` 是镜头缓存。** 只改字幕不会重切任何镜头；改一个镜头的入出点，只重切那一个。所以"微调"很便宜，别怕改。

## 四、分镜表怎么写

`shots.json` 就一个数组，每条四个字段：

```json
{
  "id": "sh13",
  "in": 546.72,          ← 原片里的起点（秒）
  "out": 549.92,         ← 原片里的终点（秒）
  "sub": "我感觉读着文字跟看保险单子似的。",   ← 字幕，留空就是无字幕空镜
  "note": "妈妈的比喻，全片最好的一句"          ← 只给人看，不进片子
}
```

三条经验：

1. **入出点对齐句子边界**。用 `work/transcript.md` 里的时间码，别手算，切半句观众会难受。
2. **一条字幕一行，最多 14 字**。超了脚本自动拆卡，但拆出来的节奏不如你自己切。
3. **空镜要留**。全是说话的镜头会闷，b-roll 是呼吸。

## 五、缓存与花钱

| 环节 | 会不会重复花钱 | 什么时候才重跑 |
|---|---|---|
| 抽音轨 | 不花 | 音轨文件不在时 |
| 云端转写 | **会**（按音频时长计费） | `work/transcript_raw.json` 不在时 |
| 切片 | 不花 | 该镜头的入出点变了 |
| 预览渲染 | 不花 | 时间线内容变了 |
| 剪映草稿 | 不花 | 每次 build 都生成一个带版本号的新草稿 |

所以：**改字幕、改顺序、改结构，都不会再调用云端**。只有换素材才需要重新转写。

## 六、版本规则

- 产物：`output/v1/`、`output/v2/` … 每次 build 一个，**不覆盖**。
- 剪映草稿名：`片名_v1`、`片名_v2` … 按名字就能对上。
- 想回到上一版：直接打开 `output/v1/preview.mp4` 看，或打开剪映里的旧草稿。
- 定稿后建议重命名草稿为 `片名_定稿`，避免和后续版本混。

> ⚠️ **实测：剪映 11.6 会在打开草稿时自动把它迁移成加密新格式**（`Timelines/` 目录 + 密文 `draft_info.json`）。
> 迁移后脚本就改不动它了（这是剪映的自我保护），所以规则是：**每版用新名字，旧版当只读存档**。
> 想继续改，就改 `shots.json` 出 v(N+1)，不要试图改已经迁移过的旧工程。

## 七、常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| `剪映正在运行，请先完全退出` | 剪映占着草稿库 | Cmd+Q 退出剪映再跑；或加 `--no-draft` |
| `缺少 key` | `~/.mediakit/api_key` 没了 | 重新写入（`chmod 600`） |
| 草稿校验 FAIL | 素材路径被移动 | 重新 build（会重新打包 Resources） |
| 预览片字幕溢出 | 单卡超 14 字 | 改 `sub` 或调小 `preset.subtitle.size` |
| 剪映升级后草稿打不开 | 草稿格式随版本变化 | 用 `--no-draft` 出预览，按分镜表手动重组；或降级剪映 |
| 草稿被剪映"加密"了，脚本改不了 | 11.6 打开时自动迁移 | 正常现象，出下一版；不要改已迁移的旧工程 |

## 八、加一个新预设

复制 `presets/纪实3min.json` 改三处：

```json
{
  "name": "我的风格",
  "platform": "douyin",
  "duration": 60,
  "structure": ["钩子", "铺垫", "论证", "收尾"],
  "subtitle": { "max_chars": 12, "size": 7.0, "y": 0.76 },
  "hints": ["这一条给 AI 看的创作要求，写人话就行"]
}
```

然后 `new` 的时候 `--preset 我的风格`，或在 `project.json` 里改 `preset` 字段。

## 八点五、开发环境（维护者）

环境由 **uv** 管理，不要用系统 Python：

```bash
uv sync --group dev        # 首次 / 拉代码后
uv run python aicut.py status <项目>
uv run python gui/server.py --open
```

`uv.lock` 必须提交；改依赖后跑 `uv lock` 并一起提交。

## 九、这套东西的边界

- **它不做创意判断**。分镜表谁写？你写，或让 AI 按 `work/brief.md` 写初稿。脚本只负责"按表施工"。
- **它不碰精修**。调色、音效、转场手感、花字动画，仍然在剪映里做。
- **它不保证草稿跨版本兼容**。剪映升级是最大变量，所以每次都跑 `validate_draft.py` 门禁。

# Plan: M5 干净 Mac 可装可用（GL-01 / GL-03 / GL-04 / GL-19）

## Summary
让 `AI粗剪.app` 在一台没有 brew / Node 的干净 Apple Silicon Mac 上能装、能转写、合规、出错可诊断。
四件事：① 云端 ASR 从 shell 调 Node 版 `mediakit-cli` 改为纯 Python `urllib` 直连火山 MediaKit HTTP API（上传 → 提交 → 轮询 → 续查，语义不变）；
② 内置 ffmpeg 换成**仓库内可复现脚本**从源码构建的 LGPL 静态版（源码包 SHA256 钉死），所有 `libx264` 改 `h264_videotoolbox`，随包附 THIRD-PARTY-NOTICES；
③ 标准库 `logging` 落盘 `~/Library/Logs/剪辑台/`（轮转 + 脱敏）并提供一键诊断包；④ 交付说明改为 macOS 15+ 的「仍要打开」路径。

## User Story
As a 1–2 人工作室的剪辑师（非技术、Apple Silicon Mac、没有命令行环境），
I want 双击装好的 App 就能完成转写和出片，出错时点一下就能导出诊断包发给开发者，
So that 不需要开发者远程帮我装 Node / brew，出了问题也能在 1 分钟内把现场交出去。

## Problem → Solution
- 转写依赖开发机全局 npm 包 `@volcengine/mediakit-cli`（Node 包装 + Go 二进制），App 没打包它 → 用户机器转写必失败
  → `pipeline/cloud.py` 直连 `https://mediakit.cn-beijing.volces.com` 的 3 个 REST 接口，零外部进程。
- 内置 ffmpeg 来自 osxexperts.net 的 GPL 构建（`--enable-gpl --enable-libx264 --enable-libx265`），`curl -sL` 无 `-f`、无校验
  → `packaging/build_ffmpeg.sh` 下载钉死 SHA256 的 ffmpeg 8.1.3 + FreeType 2.14.3 源码，LGPL 配置静态编译；构建后自检（许可证、链接库、编码器/滤镜）；代码里 H.264 统一走 `pipeline/encode.py` 的 VideoToolbox 参数。
- 全仓没有 `logging`，打包后 `console=False` 让 stdout 消失 → 出错后谁都拿不到信息
  → `pipeline/applog.py`（RotatingFileHandler + 脱敏 Filter + 全局异常钩子 + 阶段计时）+ `pipeline/diagnostics.py`（诊断 zip）+ GUI 按钮。
- `docs/PACKAGING.md:56` 写「右键 → 打开」，macOS 15 起已失效
  → 文档与随包说明改为「系统设置 → 隐私与安全性 → 仍要打开」，并保留 macOS 13/14 的右键路径。

## Metadata
- **Complexity**: Large（跨打包 / 网络客户端 / 日志三块，新增 3 个模块与 1 个构建脚本）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 5「干净 Mac 可装可用」（GL-01 GL-03 GL-04 GL-19）
- **Estimated Files**: 约 26 个（11 新建 / 15 修改，含 6 个文档）

---

## UX Design

### Before
```
┌──────────────────────────────────────────────────────────────┐
│ 剪辑师双击 AI粗剪.app                                         │
│  macOS 15：「无法打开」→ 说明书让「右键→打开」→ 无效 → 卡住   │
│  勉强打开 → ① 处理素材 → 日志：[x] 转写失败：找不到 mediakit-cli│
│  关掉 App → 什么都没留下；开发者只能远程/截图猜               │
└──────────────────────────────────────────────────────────────┘
```

### After
```
┌──────────────────────────────────────────────────────────────┐
│ 随包「首次打开说明.txt」：双击一次 → 系统设置 → 隐私与安全性 │
│   → 底部「仍要打开」→ 输入密码 → 以后正常双击                 │
│ ① 处理素材 → [·] 上传音轨… → [·] 获取云端转写结果… → [✓]     │
│ 任意失败 → 弹窗里「导出诊断包」→ Finder 选中                  │
│   ~/Downloads/剪辑台诊断-20261019-153000.zip → 拖进微信发出   │
│ 日志始终在 ~/Library/Logs/剪辑台/（不含 API Key）             │
└──────────────────────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 首次打开 | 右键→打开（15+ 无效） | 系统设置→隐私与安全性→仍要打开 | 13/14 仍可右键；说明两条都写 |
| 转写 | 需本机 Node + mediakit-cli | App 内直连 HTTP | 同一个 MediaKit API Key，不新增凭证 |
| 转写日志行 | `获取云端转写结果…` | 增加 `上传音轨（xx MB）…` / `续用已上传的音轨` | 打印内容不含 upload_url 签名、不含 Key |
| 出错后 | 无记录 | 侧栏底部 + 任务失败弹窗「导出诊断包」 | 生成 zip 并在 Finder 中选中 |
| 预览/切片画质 | libx264 CRF | VideoToolbox 固定码率 | 码率显式设置（PRD 风险缓解） |
| 关于许可 | 无 | App 包内 `licenses/`、dist 下 `THIRD-PARTY-NOTICES.txt` | GUI「关于」入口见 Notes（需用户决策） |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/cloud.py` | 1-203 | 要重写的对象；公开接口（`CloudClient.submit_asr/wait_task/transcribe`、`CloudError`、`record_failure`、`asr_task.json` 续查）必须保持 |
| P0 | `pipeline/llm.py` | 18-83 | HTTP 客户端范式：注入 `transport`、`RETRY_STATUS`、退避、Key 不进异常 |
| P0 | `tests/test_cloud.py` | 1-130 | 现有语义测试（重试 / 幂等 token / 续查 / 超时文案），重写为 HTTP mock 时**逐条保留语义** |
| P0 | `tests/test_llm.py` | 1-80 | transport mock 写法 |
| P0 | `aicut.py` | 143-221, 279-291, 423-455, 588-598, 725-735 | `mediakit_env`、转写入口、两处 libx264、prepare 阶段序列、`run_cli` |
| P0 | `packaging/build_app.sh` | 1-25 | ffmpeg 下载处（GL-04） |
| P0 | `packaging/ai-cut.spec` | 15-41, 56-70 | hiddenimports、datas、binaries、`console=False` |
| P1 | `pipeline/render_preview.py` | 1-105 | filter_complex（含 drawtext）+ libx264；脚本式运行（dev 下 `sys.path[0]=pipeline/`） |
| P1 | `pipeline/build_documentary.py` | 48-57 | `cut_shot` 里的 libx264 |
| P1 | `pipeline/secrets.py` | 77-83, 167-172 | `mask()`；`env_with_secret()` 将删除 |
| P1 | `gui/server.py` | 42-62, 214-295, 302-303, 380-412, 488-623, 625-640 | `run_aicut`、任务日志、静音的 `log_message`、`/api/health`、POST 路由、`serve_in_background` |
| P1 | `app/main.py` | 1-42 | 桌面壳入口，日志初始化位置 |
| P1 | `pipeline/export_draft.py` | 23-24 | pipeline 脚本里 `sys.path` 垫片写法 |
| P1 | `pipeline/format_transcript.py` | 38-45 | 读 `transcript_raw.json`：同时兼容顶层 `subtitles` 与 `result.subtitles` |
| P2 | `docs/PACKAGING.md` | 1-64 | GL-03 文案、GPL 限制说明、性能表 |
| P2 | `docs/TECH-STACK.md` | 17-20, 83-97, 146 | mediakit-cli / ffmpeg 描述需同步 |
| P2 | `docs/PRD-AI粗剪工具.md` | 235-240, 259-284, 331-338 | FR-13、§7 许可/隐私、§8 交付、§13 决策 |
| P2 | `tests/test_understand_visual.py` | 1-26 | 需要 ffmpeg 的测试用 `skipif(shutil.which("ffmpeg") is None)` |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| mediakit-cli 云端协议 | `github.com/volcengine/mediakit-cli` `internal/cloud/{client,request,response,executor,media_upload,media_inputs,upload_cache}.go`、`internal/auth/resolver.go`（MIT，已只读审阅）；本机 `/opt/homebrew/lib/node_modules/@volcengine/mediakit-cli`（v0.2.1）二进制内嵌 schema | 端点、鉴权、上传、轮询全部是普通 HTTPS + JSON，见下方 Research |
| ASR 能力说明 | 本机 `skills/byted-mediakit-video/reference/asr-subtitles.md` | 入参 `audio_url/language/enable_speaker_info/enable_confidence/client_token`；结果 `result.duration`、`result.subtitles[].{start_time,end_time,subtitle_text,speaker,confidence}`；音频 ≤ 3 小时 |
| FFmpeg LGPL 合规清单 | https://ffmpeg.org/legal.html | 不带 `--enable-gpl/--enable-nonfree`；随附源码 + configure 行；写明使用 LGPLv2.1；确认无 GPL 库（libx264） |
| FFmpeg 源码 | https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz（+ `.asc` 签名） | SHA256 `7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3`（2026-10-19 实测流式计算） |
| FreeType 源码 | https://download.savannah.gnu.org/releases/freetype/freetype-2.14.3.tar.xz（+ `.sig`） | SHA256 `36bc4f1cc413335368ee656c42afca65c5a3987e8768cc28cf11ba775e785a5f`；选 FTL（BSD 风格，需文档署名） |
| 预编译 LGPL 方案调研 | ae-ffmpeg（PyPI 1.2.0，LGPLv3，`--enable-videotoolbox`）；ffmpeg.martin-riedl.de；BtbN | ae-ffmpeg **未启用 libfreetype → 没有 drawtext**（预览字幕必需）且 2024-03 后无更新；Martin Riedl 有 sha256 但含 x264/x265（GPL）；BtbN 只有 Win/Linux → **都不可用，改为自建** |
| h264_videotoolbox 参数 | 本机 `ffmpeg -h encoder=h264_videotoolbox`；ffmpeg-devel 2021-03 补丁（Apple Silicon `-q:v`） | 不支持 `-crf/-preset`；用 `-b:v`（或 Apple Silicon 上 `-q:v 0–100`）；有 `-profile high`、`-allow_sw`、`-prio_speed`、`-constant_bit_rate`(macOS13+)；像素格式只收 `nv12/yuv420p` |
| macOS 15 Gatekeeper | Wikipedia「Gatekeeper (macOS)」、Macworld、9to5Mac（2024-08） | Sequoia 起右键打开不再绕过；先尝试打开一次 → 系统设置 → 隐私与安全性 → 底部「仍要打开」→ 输入管理员密码 |
| Python logging | https://docs.python.org/3.12/library/logging.handlers.html | `RotatingFileHandler(maxBytes, backupCount, encoding)`；多进程写同一文件不安全 → CLI 与 GUI 分文件 |

---

## Phase 3 Research（关键结论）

```
KEY_INSIGHT: mediakit-cli 是 Node 包装 + Go 静态二进制（bin/mediakit-cli, Mach-O arm64）。云端默认 endpoint
  https://mediakit.cn-beijing.volces.com（可被 MEDIAKIT_ENDPOINT 覆盖）。所有请求头：
  Accept: application/json / Content-Type: application/json / Authorization: Bearer <MEDIAKIT_API_KEY>
  / X-Amk-Cli-Runtime / X-Amk-Task-Source / X-Amk-Cli-Version（request.go:331-365, auth/resolver.go:64-72）。
APPLIES_TO: Task 1–2（pipeline/cloud.py）
GOTCHA: 鉴权就是现有的 MEDIAKIT_API_KEY，不需要新凭证；X-Amk-* 是统计头，后端是否校验未知 → 见 Notes 需用户操作（真账号冒烟）。
```

```
KEY_INSIGHT: 本地文件不是直接传给 asr-subtitles，而是先上传：
  1) POST /api/v1/tools-sync/request-media-upload-url  body {"tool_name":"asr-subtitles"}
     → {"success":true,"result":{"file_id":"mediakit://…","upload_url":"https://…(预签名)","method":"PUT",
        "upload_headers":[{"key":..,"value":..}] 或 ["K: V"]}}
  2) <method 默认 PUT> upload_url，body=文件原始字节，带 upload_headers，不带 Authorization（media_upload.go:18-58）
  3) 之后 audio_url 填 file_id（mediakit://…）。CLI 本地缓存 12h（upload_cache.go:19, 按 路径+size+mtime+key指纹）。
APPLIES_TO: Task 1（_upload / work/asr_upload.json）
GOTCHA: upload_url 带签名查询串，绝不能写进日志 / failed.json；urllib 用文件对象做 body 时必须显式给 Content-Length，
  否则走 chunked，预签名 PUT 可能拒收。54 分钟 16k 单声道 wav ≈ 104 MB，上传超时给 600s（CLI http.Client 10 分钟）。
```

```
KEY_INSIGHT: 提交与查询：
  POST /api/v1/tools/asr-subtitles  body {"audio_url":file_id,"language":"cmn-Hans-CN","enable_speaker_info":true,
       "enable_confidence":true,"client_token":<≤64 可打印 ASCII>} → {"success":true,"task_id":..,"task_type":..,"request_id":..}
  GET  /api/v1/tasks/{task_id} → {"task_id","status":running|queued|completed|failed|canceled,"result":{"duration","subtitles":[…]},"error",…}
  失败判定：HTTP ≥400 → 错误（payload 里 error.message|error.error|error.msg|message|msg|error 字符串）；
  HTTP 2xx 但 success=false → 业务失败（response.go:141-154, 189-212；executor.go:384-415）。
APPLIES_TO: Task 1（_request / submit_asr / wait_task / _error_message）
GOTCHA: CLI 的 query-task 输出把 result 拍平到顶层（executor.go:330-372），现有 transcript_raw.json 就是这个形状；
  新客户端保持拍平（{"task_id","status",**result}），format_transcript.py:40 两种都认，旧产物可直接做回归对比。
```

```
KEY_INSIGHT: 打包 Python 的 urllib 在干净 Mac 上可用：uv 的 python-build-standalone 3.12.13 / OpenSSL 3.5.5
  默认 cafile=/private/etc/ssl/cert.pem，该文件随 macOS 系统自带。
APPLIES_TO: Task 1、手动验证
GOTCHA: 不要引入 certifi/requests；如真机仍报 CERTIFICATE_VERIFY_FAILED，错误要原样进日志与诊断包。
```

```
KEY_INSIGHT: 代码用到的 ffmpeg 能力全部是原生组件，唯一外部库需求是 drawtext → libfreetype：
  编码器 h264_videotoolbox / aac / pcm_s16le / mjpeg(封面) / rawvideo；
  滤镜 scale pad setsar fps trim setpts atrim asetpts aresample concat format drawtext
       scdet blackdetect freezedetect silencedetect；输入 lavfi(color 测试源)；ffprobe format=duration。
  （aicut.py:208,286,445；render_preview.py:45-75；understand_visual.py:33-34,93-95；junk_detect.py:60-67；to_jianying.py:238）
APPLIES_TO: Task 6（build_ffmpeg.sh 自检清单）
GOTCHA: fontfile 显式给出（render_preview.py:20-30 PingFang），不需要 fontconfig/harfbuzz/fribidi；中文无需复杂字形整形。
```

```
KEY_INSIGHT: 静态构建必须防止 configure 自动探测到 Homebrew 的动态库（lzma/iconv/bzlib/sdl2/libpng…），
  否则产物链接 /opt/homebrew/...dylib，干净 Mac 直接起不来。用 --disable-autodetect 再显式开
  --enable-videotoolbox --enable-audiotoolbox --enable-zlib --enable-libfreetype；FreeType 用
  --without-png --without-harfbuzz --without-brotli --without-bzip2 --with-zlib=no 静态编。
APPLIES_TO: Task 6
GOTCHA: 构建后用 `otool -L` 断言只出现 /System/Library/ 与 /usr/lib/；`ffmpeg -L` 必须是 "GNU Lesser General Public License"；
  `-buildconf` 不得含 enable-gpl / libx264 / libx265 / nonfree。
```

```
KEY_INSIGHT: h264_videotoolbox 不认 -crf/-preset；PRD 风险表要求「码率显式设置」。替换表（Task 4）：
  分析代理 540p（原 ultrafast crf30）→ -c:v h264_videotoolbox -b:v 1500k -profile:v high -allow_sw 1 -pix_fmt yuv420p
  镜头切片 1080×1920（原 veryfast crf18）→ -b:v 12M
  预览片（原 veryfast crf20）→ -b:v 8M
APPLIES_TO: Task 3–5
GOTCHA: 10-bit / HDR 素材（iPhone HLG，yuv420p10le）直接喂 VT 会报像素格式不支持 → 必须 -pix_fmt yuv420p；
  -allow_sw 1 让硬件会话被占满或虚拟机里自动退回软件编码，避免整条流水线失败。
```

```
KEY_INSIGHT: ffmpeg CLI 作为独立进程被 subprocess 调用，不与 App 链接，静态可执行文件不触发 LGPL 「动态链接」条款；
  仍需：随附 LGPL 文本、源码（或同一渠道提供）、configure 行、声明使用 FFmpeg（legal.html 3/6/8/10/18）。
APPLIES_TO: Task 6–7（THIRD-PARTY-NOTICES、dist/sources）
GOTCHA: 「关于」对话框声明（第 10 条）当前 App 没有关于页 → 需用户决策（见 Notes）。
```

---

## Unified Discovery Table

| Category | File:Lines | Pattern | Key Snippet |
|---|---|---|---|
| Naming | `pipeline/llm.py:18-23` | 模块常量全大写；异常 `XxxError(RuntimeError)` 带中文 docstring | `class LLMError(RuntimeError):` |
| HTTP | `pipeline/llm.py:26-34` | 模块级 `default_transport`，可注入 | `def default_transport(url, headers, body, timeout) -> tuple[int, str]` |
| Retry | `pipeline/llm.py:69-83` | `for attempt in range(self.retries + 1)` + `RETRY_STATUS` + backoff 元组 | `self.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])` |
| Errors | `pipeline/cloud.py:166-180` | 终态失败写 `failed.json` 后再抛 | `record_failure(workdir, "asr", str(exc), {...}); raise` |
| Resume | `pipeline/cloud.py:144-164` | `asr_task.json` 3 天有效期 | `if tid and age < 86400 * 3:` |
| CLI 输出 | `aicut.py:48-58` | `die/info/ok` 带 `[x]/[·]/[✓]` 前缀 | `print(f"[x] {msg}"); sys.exit(1)` |
| 原子写 | `aicut.py:71-75` | `.tmp` + `os.replace` | `save_json` |
| Secrets | `pipeline/secrets.py:77-83` | 只用 `mask()` 输出 | `f"{value[:4]}****{value[-4:]}"` |
| 冻结差异 | `pipeline/proc.py:17-55` | `FROZEN`、`resource_path`、`ensure_bundled_path` | `FROZEN = bool(getattr(sys, "frozen", False))` |
| 脚本垫片 | `pipeline/export_draft.py:23-24` | 被当脚本运行时插仓库根 | `sys.path.insert(0, str(ROOT))` |
| Tests | `tests/test_cloud.py:10-31` | 假对象 + 序列化 runner，`sleep=lambda _: None` | `def client(sequence, **kw)` |
| Tests env | `tests/test_secrets.py:15-24` | fixture 用 `monkeypatch.setenv` 隔离用户目录 | `AI_CUT_CONFIG_DIR` |
| ffmpeg 测试 | `tests/test_understand_visual.py:10` | 无 ffmpeg 跳过 | `pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, ...)` |
| Config | `pyproject.toml` | 只有 pytest 配置，无 lint/typecheck | `addopts = "-q"` |
| Deps | `pyproject.toml` | 运行时只 3 个：pywebview / pyJianYingDraft / keyring；**本计划不新增任何依赖** | — |

---

## Patterns to Mirror

### NAMING_CONVENTION
```python
# SOURCE: pipeline/llm.py:18-23
DEFAULT_BASE = "https://api.deepseek.com"
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """LLM 调用的终态失败。"""
```

### ERROR_HANDLING（HTTP 传输 + 重试，Key 不入异常）
```python
# SOURCE: pipeline/llm.py:26-34
def default_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LLMError(f"网络错误：{exc}") from exc
```
```python
# SOURCE: pipeline/llm.py:69-83
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                status, text = self.transport(url, headers, body, self.timeout)
            except LLMError as exc:
                last = exc
            else:
                if status == 200:
                    return json.loads(text)
                last = LLMError(f"HTTP {status}: {text[:300]}")
                if status not in RETRY_STATUS:
                    raise last
            if attempt < self.retries:
                self.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
        raise LLMError(f"重试 {self.retries} 次仍失败：{last}")
```

### RESUME / STATE（必须保留的续查语义）
```python
# SOURCE: pipeline/cloud.py:166-184
    def transcribe(self, audio: Path, workdir: Path,
                   *, duration_s: float = 0.0) -> dict:
        """提交 + 等待，返回字幕 JSON；失败落盘。断点续跑复用已有 task_id。"""
        total_timeout = max(900.0, duration_s * 3 + 600)
        task_id = self._load_task(workdir)
        try:
            if task_id is None:
                task_id = self.submit_asr(audio)
                self._save_task(workdir, task_id)
            else:
                print(f"[·] 续查上次的子任务：{task_id}")
            data = self.wait_task(task_id, total_timeout)
        except CloudError as exc:
            record_failure(workdir, "asr", str(exc), {"audio": str(audio)})
            raise
```
```python
# SOURCE: pipeline/cloud.py:137-141  —— 超时文案被测试断言「不会重新提交」
            if time.monotonic() > deadline:
                raise CloudError(
                    f"任务超时（已等待 {total_timeout / 60:.0f} 分钟，最后状态 {last_status}）："
                    f"{task_id}。任务没有丢，重跑会接着查这个任务，不会重新提交。")
```

### LOGGING_PATTERN（现状：没有 logging，只有 print 前缀；新模块按此前缀风格写中文消息）
```python
# SOURCE: aicut.py:48-58
def die(msg: str) -> None:
    print(f"[x] {msg}")
    sys.exit(1)


def info(msg: str) -> None:
    print(f"[·] {msg}")
```
```python
# SOURCE: gui/server.py:302-303 —— 访问日志被静音（GL-19 定位点之一）
    def log_message(self, fmt, *args):  # 静音访问日志
        pass
```

### REPOSITORY_PATTERN（项目文件原子写）
```python
# SOURCE: aicut.py:71-75
def save_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
```

### SERVICE_PATTERN（冻结/开发两种运行方式）
```python
# SOURCE: aicut.py:115-128
def _run_pipeline(module: str, argv: list[str]) -> None:
    """跑一个 pipeline 脚本：开发用子进程，打包后同进程导入。"""
    if proc.FROZEN:
        code, out = proc.run_inprocess(module, argv)
        ...
    script = str(PIPELINE / (module.split(".")[-1] + ".py"))
    r = subprocess.run([sys.executable, script, *argv], capture_output=True, ...)
```
```python
# SOURCE: pipeline/export_draft.py:23-24 —— 被当脚本运行也能 import pipeline.*
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
```

### TEST_STRUCTURE
```python
# SOURCE: tests/test_llm.py:8-19
def transport_ok(content: str, status: int = 200):
    def _t(url, headers, body, timeout):
        return status, json.dumps({"choices": [{"message": {"content": content}}],
                                   "usage": {"total_tokens": 42}})
    return _t


def test_chat_json_parses_content():
    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None,
                           transport=transport_ok('{"a": 1}'))
```
```python
# SOURCE: tests/test_secrets.py:15-24
@pytest.fixture
def file_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CUT_SECRETS", "file")
    monkeypatch.setenv("AI_CUT_CONFIG_DIR", str(tmp_path / "cfg"))
    for var in secrets.ENV_KEYS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(secrets, "LEGACY_FILES", {}, raising=False)
    return tmp_path / "cfg"
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/cloud.py` | UPDATE（重写内部） | GL-01：HTTP 客户端替换 subprocess，公开接口不变 |
| `tests/test_cloud.py` | UPDATE（重写） | 先写：HTTP mock 覆盖上传/提交/轮询/续查/脱敏 |
| `pipeline/secrets.py` | UPDATE | 删除只给 mediakit-cli 用的 `env_with_secret()` |
| `aicut.py` | UPDATE | 删 `mediakit_env`；`CloudClient()` 无参；两处 libx264 → `encode.h264_args`；`die`/`run_cli` 写日志；prepare/build 阶段计时 |
| `pipeline/encode.py` | CREATE | GL-04：H.264 VideoToolbox 参数单一来源 |
| `tests/test_encode.py` | CREATE | 参数表 + 全仓无 libx264 守卫 + 可选真编码 |
| `pipeline/render_preview.py` | UPDATE | libx264 → encode；加 sys.path 垫片 |
| `pipeline/build_documentary.py` | UPDATE | libx264 → encode；加 sys.path 垫片 |
| `packaging/build_ffmpeg.sh` | CREATE | GL-04：钉 SHA256 的 LGPL 源码构建 + 自检 |
| `packaging/build_app.sh` | UPDATE | 调 build_ffmpeg.sh；`curl -f`；自检；拷 notices/说明/源码到 dist |
| `packaging/ai-cut.spec` | UPDATE | hiddenimports 加新模块；datas 加 `licenses/` 与 notices |
| `packaging/THIRD-PARTY-NOTICES.txt` | CREATE | GL-04：第三方许可声明 |
| `packaging/首次打开说明-macOS.txt` | CREATE | GL-03：随 dist 交付的使用说明 |
| `tests/test_packaging.py` | CREATE | notices 覆盖运行时依赖；构建脚本无 GPL 开关且钉哈希；spec 含新模块 |
| `pipeline/applog.py` | CREATE | GL-19：落盘、轮转、脱敏、异常钩子、阶段计时 |
| `tests/test_applog.py` | CREATE | 先写 |
| `pipeline/diagnostics.py` | CREATE | GL-19：诊断包 |
| `tests/test_diagnostics.py` | CREATE | 先写 |
| `pipeline/llm.py` | UPDATE（1 行） | 拿到 Key 后 `applog.register_secret` |
| `gui/server.py` | UPDATE | 任务日志镜像到 logger；`log_message` → debug；`POST /api/diagnostics`；`main()` 初始化日志 |
| `gui/static/index.html` | UPDATE | 「导出诊断包」按钮（侧栏 + 失败弹窗） |
| `app/main.py` | UPDATE | 启动第一件事 `applog.setup("app")` |
| `docs/PACKAGING.md` | UPDATE | GL-03 文案；ffmpeg 来源/许可；日志与诊断包位置 |
| `docs/TECH-STACK.md` | UPDATE | ASR 调用方式、ffmpeg 构建方式 |
| `docs/交付形态调研.md` | UPDATE | 第 41、151 行「右键打开」改 15+ 路径 |
| `docs/GUI.md` | UPDATE | 第 83 行删除 mediakit-cli 安装要求 |
| `docs/go-live-blockers.md` | UPDATE | GL-01/03/04/19 → done（附 commit） |

## NOT Building

- **GL-16**（ASR 失败后 `asr_task.json` 不清 / 未绑定音频指纹）属于 M4：本计划**原样保留** `_load_task/_save_task` 行为，不顺手修。
- **KI-29**（failed.json 脱敏、网络错误匹配过宽）：新客户端自身不产生明文 Key / 签名 URL，但不去改 `record_failure` 的通用逻辑。
- **KI-37**（版本号、CFBundleVersion、升级丢授权）：诊断包只**读取**现有版本号，不改版本管理。
- **KI-33 / KI-25**：不改进程清理、不改 llm.py 重试范围（llm.py 仅加 1 行 register_secret）。
- DMG 制作、ad-hoc 之外的签名公证、Intel / universal2（PRD §13 已决定不做；DMG 不在 GL-03 范围）。
- 不打包 mediakit-cli Go 二进制（备选方案，已否决，见 Notes）。
- 不做 mediakit 其他能力（OCR / 语义切片 / 视频理解）的 HTTP 化。
- 不做 GUI「关于」页面（需用户决策）。
- 不新增任何 Python 依赖（不引入 requests / certifi / structlog）。
- M1 的 Host/Origin/token 校验不在本里程碑实现；新增 POST 路由需走 M1 落地后的同一校验入口（见 Task 13 GOTCHA）。

---

## Step-by-Step Tasks

> 每个 Task 先写测试（RED）→ 跑失败 → 实现（GREEN）→ `uv run pytest -q`。顺序：GL-01 → GL-04 → GL-19 → GL-03 → 收尾。

### Task 1: 测试先行 —— HTTP 版 CloudClient（GL-01）
- **ACTION**: 重写 `tests/test_cloud.py`，删除所有 `FakeProc / runner / mediakit-cli` 断言，换成 transport/uploader mock；**保留原测试的语义**（重试成功、业务错误不重试、token 跨重试复用、transcribe 写 raw 与 failed.json、轮询至 completed、failed 抛错含 message、超时文案「不会重新提交」、从 `asr_task.json` 续查只查一次）。
- **IMPLEMENT**（测试骨架）:
```python
import json
from pathlib import Path

import pytest

from pipeline import cloud

UP_TARGET = {"success": True, "result": {
    "file_id": "mediakit://F1", "method": "PUT",
    "upload_url": "https://tos.example.com/obj?X-Tos-Signature=SECRETSIG",
    "upload_headers": [{"key": "Content-Type", "value": "audio/wav"}]}}


class FakeHttp:
    """按 (method, path) 顺序返回预设响应；记录每次请求。"""
    def __init__(self, routes):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.calls = []

    def transport(self, method, url, headers, body, timeout):
        path = url.split("volces.com", 1)[-1]
        key = (method, path.split("?")[0])
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "body": json.loads(body) if body else None})
        seq = self.routes[key]
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, Exception):
            raise item
        status, payload = item
        return status, payload if isinstance(payload, str) else json.dumps(payload)


def make(routes, uploads=None, **kw):
    http = FakeHttp(routes)
    up_calls = []

    def uploader(method, url, headers, path, timeout):
        up_calls.append({"method": method, "url": url, "headers": headers, "path": path})
        item = (uploads or [(200, "")]).pop(0) if uploads else (200, "")
        if isinstance(item, Exception):
            raise item
        return item

    c = cloud.CloudClient(api_key="AKLTsecretkey123456", sleep=lambda _: None,
                          transport=http.transport, uploader=uploader, **kw)
    return c, http, up_calls

UPLOAD = ("POST", "/api/v1/tools-sync/request-media-upload-url")
SUBMIT = ("POST", "/api/v1/tools/asr-subtitles")
def TASK(tid): return ("GET", f"/api/v1/tasks/{tid}")
```
  需要的用例（至少）:
  1. `test_submit_uploads_local_audio_then_submits_file_id`：`submit_asr(wav)` → 先 UPLOAD（body `{"tool_name":"asr-subtitles"}`），uploader 收到 `PUT` + `Content-Type` 头 + **无 Authorization**，SUBMIT body `audio_url == "mediakit://F1"`、`language == "cmn-Hans-CN"`、`enable_speaker_info is True`、`enable_confidence is True`、有 `client_token`；返回 task_id。
  2. `test_auth_header_is_bearer_and_never_in_errors`：每个 API 请求 `headers["Authorization"] == "Bearer AKLTsecretkey123456"`；401 响应抛 `CloudError`，`"AKLTsecretkey123456" not in str(exc)`，且提示「MediaKit API Key 无效」。
  3. `test_retry_on_503_then_success_reuses_client_token`：SUBMIT 先 `(503, "busy")` 再成功 → SUBMIT 被调 2 次，两次 body 的 `client_token` 相同。
  4. `test_network_error_retried`：transport 第一次抛 `cloud.CloudError("网络错误：timed out")`，第二次成功。
  5. `test_business_failure_not_retried`：SUBMIT 返回 `(200, {"success": False, "error": {"message": "invalid audio"}})` → 抛错含 `invalid audio`，SUBMIT 只调 1 次。
  6. `test_400_not_retried`：`(400, {"error": {"message": "bad param"}})` → 1 次。
  7. `test_missing_task_id_raises`。
  8. `test_wait_polls_until_completed_and_flattens_result`：TASK 依次 running/queued/completed(`{"status":"completed","task_id":"t1","result":{"duration":3.0,"subtitles":[{"start_time":0,"end_time":1,"subtitle_text":"你好"}]}}`) → 返回 dict 顶层有 `subtitles` 与 `duration`、`status == "completed"`，GET 3 次。
  9. `test_wait_raises_on_failed_task_with_message`（`{"status":"failed","error":{"message":"boom"}}` → 含 boom）；`canceled` 同理。
  10. `test_wait_times_out_with_actionable_message`（照抄原用例的 monotonic monkeypatch，断言「不会重新提交」）。
  11. `test_task_id_is_url_quoted`：task_id `"a/b"` → URL 以 `/api/v1/tasks/a%2Fb` 结尾。
  12. `test_transcribe_writes_raw_and_task_file` / `test_transcribe_failure_recorded_without_secrets`：上传失败 `(403, "<Error>SignatureDoesNotMatch ... X-Tos-Signature=SECRETSIG</Error>")` → `failed.json[-1]["stage"] == "asr"`，文件内容不含 `SECRETSIG`、不含 Key。
  13. `test_transcribe_resumes_from_saved_task`：预置 `asr_task.json`（`at: 9e9`）→ 只发 1 次 GET，不上传不提交。
  14. `test_upload_reused_within_ttl`：预置 `work/asr_upload.json`（file_id + 当前 wav 的 size/mtime_ns + 未过期 expires_at）→ submit 不调 UPLOAD；size 不符则重新上传。
  15. `test_missing_key_raises_helpful_error`：`monkeypatch.setattr(cloud.secrets, "get", lambda n: None)`，`CloudClient(api_key=None)` → 调用时抛错含 `config set mediakit`。
  16. `test_upload_headers_accept_string_form`：`upload_headers: ["Content-Type: audio/wav"]` 也被解析。
- **MIRROR**: TEST_STRUCTURE（`tests/test_llm.py:8-19`）
- **IMPORTS**: `json, pathlib.Path, pytest, pipeline.cloud`
- **GOTCHA**: wav 文件用 `tmp_path / "a.wav"` 真写几个字节（上传要 stat）；`sleep=lambda _: None` 避免真等。
- **VALIDATE**: `uv run pytest tests/test_cloud.py -q` → 全部失败（RED，`CloudClient` 还不接受 `transport`）。

### Task 2: 实现 HTTP 版 `pipeline/cloud.py`（GL-01）
- **ACTION**: 重写 `CloudClient` 内部；保留 `CloudError`、`_now`、`record_failure`、`_task_file/_load_task/_save_task`、`transcribe` 的结构与文案；删除 `subprocess` 与 `NETWORK_HINTS`。
- **IMPLEMENT**:
```python
# -*- coding: utf-8 -*-
"""火山引擎 MediaKit 云端 ASR 客户端（直连 HTTP，不依赖 mediakit-cli / Node）。

协议与 @volcengine/mediakit-cli 0.2.1 一致（internal/cloud/*.go）：
  1. POST /api/v1/tools-sync/request-media-upload-url → 预签名地址，PUT 上传本地音轨，得到 mediakit:// file_id；
  2. POST /api/v1/tools/asr-subtitles → task_id（client_token 幂等）；
  3. GET  /api/v1/tasks/{task_id} → running|queued|completed|failed|canceled。
约束：只用 urllib；429/5xx/网络错误按退避重试，业务错误立即失败；
永不把 API Key、预签名 URL 写进异常、日志或 failed.json。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pipeline import secrets

DEFAULT_ENDPOINT = "https://mediakit.cn-beijing.volces.com"
ASR_TOOL = "asr-subtitles"
UPLOAD_PATH = "/api/v1/tools-sync/request-media-upload-url"
SUBMIT_PATH = f"/api/v1/tools/{ASR_TOOL}"
TASK_PATH = "/api/v1/tasks/{task_id}"
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
AUTH_STATUS = {401, 403}
DONE = {"completed"}
FAILED = {"failed", "canceled", "cancelled"}
UPLOAD_TTL_S = 12 * 3600          # 与 mediakit-cli upload_cache.go 一致
CLIENT_HEADERS = {                 # 统计头；值待真账号确认，见计划 Notes
    "X-Amk-Cli-Runtime": "aicut",
    "X-Amk-Task-Source": "cli/aicut",
}
_URL_QUERY = re.compile(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]*")


class CloudError(RuntimeError):
    """云端调用的终态失败。"""


def _redact(text: str, key: str | None) -> str:
    """去掉 URL 查询串（预签名）并把 Key 换成掩码。"""
    text = _URL_QUERY.sub(r"\1?…", text)
    if key:
        text = text.replace(key, secrets.mask(key))
    return text


def default_transport(method: str, url: str, headers: dict, body: bytes | None,
                      timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise CloudError(f"网络错误：{exc}") from exc


def default_upload(method: str, url: str, headers: dict, path: Path,
                   timeout: float) -> tuple[int, str]:
    size = Path(path).stat().st_size
    with open(path, "rb") as fh:
        req = urllib.request.Request(url, data=fh, method=method,
                                     headers={**headers, "Content-Length": str(size)})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise CloudError(f"上传网络错误：{exc}") from exc
```
  `CloudClient.__init__(self, api_key=None, *, endpoint=DEFAULT_ENDPOINT, retries=3, backoff=(1.0, 3.0, 9.0), sleep=time.sleep, timeout_submit=30.0, timeout_poll=20.0, timeout_upload=600.0, transport=default_transport, uploader=default_upload)`：`self.api_key = api_key or secrets.get("mediakit")`；`applog.register_secret(self.api_key)`（Task 10 之后加；Task 2 时先不 import applog）。
  核心方法（每个 < 50 行）：
  - `_headers()`：无 Key → `CloudError("未配置 MEDIAKIT_API_KEY：运行 `aicut config set mediakit`")`；返回 `{"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {key}", **CLIENT_HEADERS}`。
  - `_request(method, path, payload, timeout) -> dict`：照 llm.py 重试循环；`status < 400` → `json.loads`（空串 → `{}`；非 JSON → `CloudError("返回不是 JSON：…")`）；若 `data.get("success") is False` → 立即抛 `CloudError(_error_message(data))`；`status in AUTH_STATUS` → 立即抛「MediaKit API Key 无效或无权限（HTTP 401）…」；`status in RETRY_STATUS` 重试，其余 4xx 立即抛 `CloudError(f"HTTP {status}: {msg}")`。所有消息过 `_redact(..., self.api_key)` 并截断 300 字。
  - `_error_message(payload) -> str`：按 response.go:189-212 顺序取 `error.message|error.error|error.msg` → `message|msg` → `error`(str)。
  - `_upload(audio: Path, workdir: Path | None) -> str`：先查 `workdir/asr_upload.json` 缓存（size、mtime_ns、未过期才复用，打印 `[·] 续用已上传的音轨`）；否则 `_request("POST", UPLOAD_PATH, {"tool_name": ASR_TOOL}, timeout_submit)` → `result.file_id/upload_url/method(默认 PUT)/upload_headers`（`_parse_upload_headers` 支持 dict 与 `"K: V"` 两种，mirror media_upload.go:86-108）；缺 file_id 或 upload_url → CloudError；打印 `[·] 上传音轨（{size/1e6:.0f} MB）…`；uploader 返回 `>= 400` 或抛网络错 → 整个「申请地址 + PUT」重试（预签名可能过期，所以重申请）；成功后原子写缓存 `{file_id, size, mtime_ns, expires_at}`。
  - `submit_asr(audio, *, language="cmn-Hans-CN", speaker=True, confidence=True, client_token=None, workdir=None) -> str`：`file_id = audio if str(audio).startswith(("mediakit://", "http://", "https://")) else self._upload(...)`；POST SUBMIT_PATH，body 布尔值为真 JSON 布尔；无 task_id → `CloudError(f"未返回 task_id：…")`。
  - `wait_task(task_id, total_timeout, interval=10.0) -> dict`：GET `TASK_PATH.format(task_id=urllib.parse.quote(task_id, safe=""))`；`status in DONE` → `return {"task_id": ..., "status": status, **(data.get("result") or {})}`；`in FAILED` → `CloudError(f"任务失败：{_error_message(data) or status}")`；超时文案原样保留。
  - `transcribe`：仅把 `self.submit_asr(audio)` 改为 `self.submit_asr(audio, workdir=workdir)`，其余不动（含 `print("[·] 续查上次的子任务…")` 与 failed.json 记录；`{"audio": str(audio)}` 保持）。
- **MIRROR**: ERROR_HANDLING、RESUME / STATE
- **IMPORTS**: 见上；不再 `import subprocess`
- **GOTCHA**:
  - `secrets.get()` 可能触发钥匙串弹窗：只在构造时调一次。
  - 上传缓存与 `asr_task.json` 同目录（`work/`）；**不**改 `_load_task` 3 天逻辑（GL-16 归 M4）。
  - `urllib` 对 `data=<file>` 的 Request 不会自动算长度：Content-Length 必须显式给。
  - `client_token` 用 `uuid.uuid4().hex`（32 字符，≤64 可打印 ASCII 约束满足）。
  - 不要把 `upload_url` 写进 `print` / 异常；只打印大小。
- **VALIDATE**: `uv run pytest tests/test_cloud.py -q` 全绿。

### Task 3: 调用方改造 + 清理 mediakit-cli 痕迹（GL-01）
- **ACTION**: `aicut.py` 删除 `mediakit_env()`（143-147）；`cmd_transcribe` 中 `cloud.CloudClient(env=mediakit_env())` → `cloud.CloudClient()`；`pipeline/secrets.py` 删除 `env_with_secret()`（167-172）。`docs/GUI.md:83`、`docs/TECH-STACK.md:19-20,93` 改为「Python 直连 MediaKit HTTP API（`pipeline/cloud.py`）」。
- **IMPLEMENT**: 在 `tests/test_packaging.py`（Task 8 创建，可先建空文件）加守卫：
```python
def test_no_mediakit_cli_subprocess():
    src = (ROOT / "pipeline/cloud.py").read_text(encoding="utf-8") + \
          (ROOT / "aicut.py").read_text(encoding="utf-8")
    assert "mediakit-cli" not in src.replace("@volcengine/mediakit-cli 0.2.1", "")
    assert "env_with_secret" not in src
```
- **MIRROR**: —
- **GOTCHA**: `aicut.py:212` 的「未配置 MEDIAKIT_API_KEY」预检保留（早失败，文案不变）。
- **VALIDATE**: `uv run pytest -q` 全绿；`grep -rn "env_with_secret\|mediakit_env" aicut.py pipeline gui` 无输出。

### Task 4: 测试先行 —— VideoToolbox 编码参数（GL-04）
- **ACTION**: 新建 `tests/test_encode.py`。
- **IMPLEMENT**:
```python
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import encode

ROOT = Path(__file__).resolve().parent.parent
CODE = [ROOT / "aicut.py", *sorted((ROOT / "pipeline").glob("*.py")), ROOT / "gui/server.py"]


@pytest.mark.parametrize("kind,rate", [("proxy", "1500k"), ("clip", "12M"), ("preview", "8M")])
def test_h264_args_use_videotoolbox_with_explicit_bitrate(kind, rate):
    args = encode.h264_args(kind)
    assert args[args.index("-c:v") + 1] == "h264_videotoolbox"
    assert args[args.index("-b:v") + 1] == rate
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert "-crf" not in args and "-preset" not in args


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        encode.h264_args("nope")


def test_no_libx264_anywhere_in_code():
    hits = [str(p) for p in CODE if re.search(r"libx26[45]", p.read_text(encoding="utf-8"))]
    assert hits == []


def _has_vt() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return "h264_videotoolbox" in out


@pytest.mark.skipif(not _has_vt(), reason="需要带 h264_videotoolbox 的 ffmpeg")
def test_real_encode_one_second(tmp_path):
    dst = tmp_path / "o.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=320x240:rate=30:duration=1",
                    *encode.h264_args("proxy"), str(dst)], check=True)
    assert dst.stat().st_size > 0
```
- **MIRROR**: TEST_STRUCTURE；ffmpeg skip 模式（`tests/test_understand_visual.py:10`）
- **GOTCHA**: `research/pyjianyingdraft_examples.py` 注释里有 libx264 —— 不在 `CODE` 列表内（研究脚本不入包），不改。
- **VALIDATE**: RED（`pipeline.encode` 不存在）。

### Task 5: 实现 `pipeline/encode.py` 并替换全部 libx264 调用点（GL-04）
- **ACTION**: 新模块 + 改 4 处调用点。
- **IMPLEMENT**:
```python
# -*- coding: utf-8 -*-
"""H.264 编码参数的唯一来源：一律 VideoToolbox（LGPL ffmpeg 不含 libx264，PRD §7 / §13）。

VideoToolbox 不支持 -crf/-preset，码率显式给出；-pix_fmt yuv420p 兜住 10-bit/HDR 素材；
-allow_sw 1 让硬件会话不可用时退回软件编码而不是整条流水线失败。
"""
from __future__ import annotations

ENCODER = "h264_videotoolbox"
BITRATES = {
    "proxy": "1500k",   # 540p 分析代理（原 libx264 ultrafast crf30）
    "clip": "12M",      # 1080×1920 镜头切片，进剪映（原 veryfast crf18）
    "preview": "8M",    # 审片预览（原 veryfast crf20）
}


def h264_args(kind: str) -> list[str]:
    return ["-c:v", ENCODER, "-b:v", BITRATES[kind], "-profile:v", "high",
            "-allow_sw", "1", "-pix_fmt", "yuv420p"]
```
  调用点替换（逐一）：
  | 位置 | 原参数 | 新参数 |
  |---|---|---|
  | `aicut.py:286-288`（`cmd_junk` 代理） | `"-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"` | `*encode.h264_args("proxy")` |
  | `aicut.py:442-449`（`ensure_clips`） | `"-c:v", "libx264", "-preset", "veryfast", "-crf", "18"` | `*encode.h264_args("clip")` |
  | `pipeline/render_preview.py:97` | `"-c:v", "libx264", "-preset", "veryfast", "-crf", "20"` | `*encode.h264_args("preview")` |
  | `pipeline/build_documentary.py:54` | `"-c:v", "libx264", "-preset", "veryfast", "-crf", "18"` | `*encode.h264_args("clip")` |
  `aicut.py` 顶部 import 加 `encode`（`from pipeline import (classify, cloud, encode, ...)`）。`render_preview.py` / `build_documentary.py` 顶部加垫片后 import：
```python
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import encode  # noqa: E402
```
- **MIRROR**: SERVICE_PATTERN（`pipeline/export_draft.py:23-24` 垫片）
- **GOTCHA**:
  - dev 模式 `_run_pipeline` 以 `python pipeline/render_preview.py` 运行 → 没垫片会 `ModuleNotFoundError: pipeline`。
  - `render_preview` 的 filter 已以 `format=yuv420p` 结尾，`-pix_fmt yuv420p` 重复无害。
  - `ensure_clips` 的缓存键 `clip_key` 不含编码器 → 旧 libx264 切片会被复用（内容正确，可接受）；不改缓存键。
  - 开发机系统 ffmpeg（Homebrew）同样带 h264_videotoolbox，开发流程不受影响。
- **VALIDATE**: `uv run pytest tests/test_encode.py -q` 全绿（真编码用例在本机执行而非 skip）；`grep -rn "libx26" aicut.py pipeline gui` 无输出。

### Task 6: `packaging/build_ffmpeg.sh` —— LGPL 静态 ffmpeg 可复现构建（GL-04）
- **ACTION**: 新脚本；产物 `vendor/bin/{ffmpeg,ffprobe}`、`vendor/licenses/{FFmpeg-COPYING.LGPLv2.1,FreeType-FTL.TXT,ffmpeg-buildconf.txt}`、`vendor/sources/{ffmpeg-8.1.3.tar.xz,freetype-2.14.3.tar.xz}`。
- **IMPLEMENT**（完整骨架）:
```bash
#!/usr/bin/env bash
# 从源码构建 LGPL 静态 ffmpeg/ffprobe（arm64），供 build_app.sh 打包。
#   ./packaging/build_ffmpeg.sh
# 不启用 GPL / nonfree；H.264 编码只用 VideoToolbox；drawtext 需要 FreeType（FTL 许可）。
set -euo pipefail

FFMPEG_VER=8.1.3
FFMPEG_SHA256=7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3
FREETYPE_VER=2.14.3
FREETYPE_SHA256=36bc4f1cc413335368ee656c42afca65c5a3987e8768cc28cf11ba775e785a5f

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/vendor/sources"; WORK="$ROOT/build/ffmpeg"; PREFIX="$WORK/prefix"
export MACOSX_DEPLOYMENT_TARGET=11.0          # 与 ai-cut.spec 的 LSMinimumSystemVersion 一致
mkdir -p "$SRC" "$WORK" "$ROOT/vendor/bin" "$ROOT/vendor/licenses"

fetch() {  # url file sha256
  local url=$1 out="$SRC/$2" sum=$3
  if [[ ! -f "$out" ]]; then curl -fsSL --retry 3 -o "$out.part" "$url" && mv "$out.part" "$out"; fi
  echo "$sum  $out" | shasum -a 256 -c - || { rm -f "$out"; echo "✗ 校验失败：$2"; exit 1; }
}
fetch "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VER.tar.xz" "ffmpeg-$FFMPEG_VER.tar.xz" "$FFMPEG_SHA256"
fetch "https://download.savannah.gnu.org/releases/freetype/freetype-$FREETYPE_VER.tar.xz" \
      "freetype-$FREETYPE_VER.tar.xz" "$FREETYPE_SHA256"

rm -rf "$WORK/src" && mkdir -p "$WORK/src"
tar -xf "$SRC/freetype-$FREETYPE_VER.tar.xz" -C "$WORK/src"
tar -xf "$SRC/ffmpeg-$FFMPEG_VER.tar.xz" -C "$WORK/src"

( cd "$WORK/src/freetype-$FREETYPE_VER"
  ./configure --prefix="$PREFIX" --enable-static --disable-shared \
    --without-png --without-harfbuzz --without-brotli --without-bzip2 --with-zlib=no
  make -j"$(sysctl -n hw.ncpu)" && make install )

( cd "$WORK/src/ffmpeg-$FFMPEG_VER"
  PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig" ./configure --prefix="$PREFIX" \
    --arch=arm64 --cc=clang --pkg-config-flags=--static \
    --enable-static --disable-shared --disable-debug --disable-doc --disable-ffplay \
    --disable-network --disable-autodetect \
    --enable-videotoolbox --enable-audiotoolbox --enable-zlib --enable-libfreetype
  make -j"$(sysctl -n hw.ncpu)" && make install
  cp COPYING.LGPLv2.1 "$ROOT/vendor/licenses/FFmpeg-COPYING.LGPLv2.1" )
cp "$WORK/src/freetype-$FREETYPE_VER/docs/FTL.TXT" "$ROOT/vendor/licenses/FreeType-FTL.TXT"
install -m 755 "$PREFIX/bin/ffmpeg" "$PREFIX/bin/ffprobe" "$ROOT/vendor/bin/"
verify   # 见下方；失败即 exit 1
```
  在同一脚本中实现 `verify()`（也供 `build_app.sh` 复用，`--verify-only` 参数只跑校验），断言失败即 `exit 1`：
```bash
verify() {
  local ff="$ROOT/vendor/bin/ffmpeg" fp="$ROOT/vendor/bin/ffprobe"
  "$ff" -hide_banner -L | grep -q "GNU Lesser General Public License" || die "不是 LGPL 构建"
  if "$ff" -hide_banner -buildconf | grep -Eq "enable-gpl|enable-nonfree|libx264|libx265"; then die "含 GPL/nonfree 组件"; fi
  "$ff" -hide_banner -encoders | grep -q h264_videotoolbox || die "缺 h264_videotoolbox"
  for f in drawtext scdet blackdetect freezedetect silencedetect concat scale pad fps trim atrim aresample; do
    "$ff" -hide_banner -filters | grep -Eq "^ [^ ]+ $f " || die "缺滤镜 $f"
  done
  for b in "$ff" "$fp"; do
    if otool -L "$b" | tail -n +2 | grep -vE "^\s+(/System/Library/|/usr/lib/)"; then die "$b 链接了非系统库"; fi
  done
  "$ff" -hide_banner -buildconf > "$ROOT/vendor/licenses/ffmpeg-buildconf.txt"
}
```
  （脚本结构：`die(){ echo "✗ $*"; exit 1; }` 与 `verify()` 定义在变量之后、下载之前；紧接着 `if [[ "${1:-}" == "--verify-only" ]]; then verify; exit 0; fi`；构建结束调用 `verify`。）
- **MIRROR**: `packaging/build_app.sh:5-8`（`set -euo pipefail`、`ROOT=...`、中文 `echo "→ …"` 进度行）
- **GOTCHA**:
  - **`--disable-autodetect` 必须有**：否则 configure 会自动链接 Homebrew 的 liblzma/libiconv/SDL2，干净 Mac 上 dyld 失败。显式开 `--enable-zlib`（系统 /usr/lib/libz）。
  - 需要 Xcode CLT（clang/make）与 `pkg-config`（本机已有 `/opt/homebrew/bin/pkg-config`）——只在**构建机**需要，用户机器不需要。
  - savannah 会 302 到镜像，`curl -fsSL` 跟随；哈希不符即删文件退出。
  - FreeType `--with-zlib=no` 使用内置 zlib 副本，避免再拉动态库。
  - 构建约 5–10 分钟；只在 `vendor/bin/ffmpeg` 缺失时由 build_app.sh 触发。
  - `build/` 与 `vendor/` 已是不入库目录（CLAUDE.md 备注）。
- **VALIDATE**: 手动：`./packaging/build_ffmpeg.sh` 成功结束；`./packaging/build_ffmpeg.sh --verify-only` 退出 0；对旧的 osxexperts 版跑 `--verify-only` 应失败于「不是 LGPL 构建」。

### Task 7: `build_app.sh` / `ai-cut.spec` / THIRD-PARTY-NOTICES（GL-04）
- **ACTION**:
  1. `packaging/build_app.sh`：删除第 11-18 行 osxexperts 下载块，换成：
```bash
if [[ ! -x vendor/bin/ffmpeg ]] || ! ./packaging/build_ffmpeg.sh --verify-only; then
  echo "→ 构建 LGPL ffmpeg/ffprobe（首次约 5–10 分钟）"
  rm -f vendor/bin/ffmpeg vendor/bin/ffprobe
  ./packaging/build_ffmpeg.sh
fi
```
     PyInstaller 之后追加：
```bash
cp packaging/THIRD-PARTY-NOTICES.txt "dist/THIRD-PARTY-NOTICES.txt"
cp "packaging/首次打开说明-macOS.txt" "dist/首次打开说明-macOS.txt"
mkdir -p dist/sources && cp vendor/sources/*.tar.xz packaging/build_ffmpeg.sh dist/sources/
```
     （仓库内已无其它 `curl -sL` 下载；`curl -f` 要求由 build_ffmpeg.sh 的 `curl -fsSL` 满足。）
  2. `packaging/ai-cut.spec`：`hidden` 增加 `"pipeline.encode", "pipeline.applog", "pipeline.diagnostics"`；`datas` 增加
```python
    (str(ROOT / "packaging" / "THIRD-PARTY-NOTICES.txt"), "licenses"),
]
LICENSES = ROOT / "vendor" / "licenses"
if LICENSES.exists():
    datas.append((str(LICENSES), "licenses"))
else:
    print(f"[warn] 缺少 {LICENSES}，许可文本不会随包")
```
  3. `packaging/THIRD-PARTY-NOTICES.txt`（UTF-8）内容来源与必含条目：
     - **FFmpeg 8.1.3** — LGPL v2.1 or later；全文 `licenses/FFmpeg-COPYING.LGPLv2.1`；configure 行 `licenses/ffmpeg-buildconf.txt`；源码：随包 `sources/ffmpeg-8.1.3.tar.xz` 及 https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz；声明「本软件以独立进程调用 FFmpeg，FFmpeg 版权归其各自作者所有，未作修改」。
     - **FreeType 2.14.3** — FTL（选用 FTL 而非 GPLv2）；必须原文写 “Portions of this software are copyright © 2025 The FreeType Project (www.freetype.org). All rights reserved.”；全文 `licenses/FreeType-FTL.TXT`。（年份以 tarball 内 `docs/FTL.TXT`/`LICENSE.TXT` 为准，实施时核对。）
     - **Python 3.12**（PSF-2.0，经 PyInstaller 打包）；**PyInstaller bootloader**（GPL-2.0 with bootloader exception，例外条款允许随闭源程序分发）。
     - Python 运行时依赖（按 `uv.lock` 闭包，macOS 平台）：pywebview 6.2.1（BSD-3-Clause）、bottle 0.13.4（MIT）、proxy-tools 0.1.0（MIT）、typing-extensions 4.16.0（PSF-2.0）、pyobjc-core / pyobjc-framework-{cocoa,quartz,security,uniformtypeidentifiers,webkit} 12.2.2（MIT）、pyJianYingDraft 0.3.1（Apache-2.0，需附 NOTICE/LICENSE 全文或链接）、imageio 2.38.1（BSD-2-Clause）、pymediainfo 7.0.1（MIT，内含 libmediainfo，BSD-2-Clause）、pillow 13.0.0（MIT-CMU）、numpy 2.5.4（BSD-3-Clause 等）、keyring 25.7.0（MIT）、jaraco-classes / jaraco-context / jaraco-functools（MIT）、more-itertools（MIT）、packaging（Apache-2.0 OR BSD-2-Clause）、zipp（MIT）。
     - 不再包含：mediakit-cli（未打包）。外部服务条款链接：火山引擎视频云服务专有条款 https://www.volcengine.com/docs/6448/79646、DeepSeek 开放平台条款。
- **MIRROR**: `packaging/ai-cut.spec:35-41`（缺文件打印 `[warn]` 而不是崩）
- **GOTCHA**: `numpy` 在 spec `excludes` 里，可能实际不随包——列出无害，别为此删条目；版本号变化时 `tests/test_packaging.py` 只校验**名字**，不校验版本。
- **VALIDATE**: 见 Task 8。

### Task 8: `tests/test_packaging.py`（GL-04 守卫，先于 Task 6/7 写也可）
- **ACTION**: 新测试文件。
- **IMPLEMENT**:
```python
import re
import sys
import tomllib
from pathlib import Path

from packaging.markers import Marker  # 由 dev 依赖 pyinstaller 带入
```
  > GOTCHA：仓库里有本地 `packaging/` 目录（含 `__init__.py`），会遮蔽 PyPI 的 `packaging` 包！不要 `from packaging.markers import ...`；改为纯手写的简化 marker 判断（只认 `sys_platform == 'xxx'` 与 `python_full_version <|>= 'x'`），或直接按名单排除 `{"pythonnet","pywin32-ctypes","uiautomation","comtypes","clr-loader","secretstorage","jeepney","cffi","cryptography","pycparser","qtpy","backports-tarfile","importlib-metadata"}`。推荐后者（KISS）：
```python
ROOT = Path(__file__).resolve().parent.parent
NOT_ON_MAC = {"pythonnet", "pywin32-ctypes", "uiautomation", "comtypes", "clr-loader",
              "secretstorage", "jeepney", "cffi", "cryptography", "pycparser", "qtpy",
              "backports-tarfile", "importlib-metadata"}


def runtime_closure() -> set[str]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    pk = {p["name"]: p for p in lock["package"]}
    todo = [d["name"] for d in pk["ai-cut"].get("dependencies", [])]
    seen: set[str] = set()
    while todo:
        n = todo.pop()
        if n in seen or n in NOT_ON_MAC:
            continue
        seen.add(n)
        todo += [d["name"] for d in pk[n].get("dependencies", [])]
    return seen


def test_notices_cover_every_runtime_dependency():
    text = (ROOT / "packaging/THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8").lower()
    norm = lambda s: re.sub(r"[-_.]+", "-", s.lower())
    missing = [n for n in runtime_closure() if norm(n) not in re.sub(r"[-_.]+", "-", text)]
    assert missing == []


def test_notices_mention_ffmpeg_lgpl_and_freetype_credit():
    text = (ROOT / "packaging/THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
    assert "FFmpeg" in text and "LGPL" in text
    assert "The FreeType Project (www.freetype.org)" in text


def test_ffmpeg_build_is_lgpl_and_pinned():
    sh = (ROOT / "packaging/build_ffmpeg.sh").read_text(encoding="utf-8")
    assert "--enable-gpl" not in sh and "--enable-nonfree" not in sh
    assert "libx264" not in sh.replace('libx264|libx265"', "")  # 只允许出现在 verify 的 grep 里
    assert "--disable-autodetect" in sh and "--enable-videotoolbox" in sh
    assert re.search(r"FFMPEG_SHA256=[0-9a-f]{64}", sh)
    assert re.search(r"FREETYPE_SHA256=[0-9a-f]{64}", sh)
    assert "shasum -a 256 -c" in sh and "curl -fsSL" in sh


def test_build_app_has_no_unverified_download():
    sh = (ROOT / "packaging/build_app.sh").read_text(encoding="utf-8")
    assert "osxexperts" not in sh and "curl -sL" not in sh


def test_spec_includes_new_modules():
    spec = (ROOT / "packaging/ai-cut.spec").read_text(encoding="utf-8")
    for mod in ("pipeline.encode", "pipeline.applog", "pipeline.diagnostics"):
        assert f'"{mod}"' in spec
```
  加上 Task 3 的 `test_no_mediakit_cli_subprocess`。
- **MIRROR**: TEST_STRUCTURE
- **GOTCHA**: 见上（本地 `packaging` 包遮蔽）。`test_ffmpeg_build_is_lgpl_and_pinned` 的 libx264 断言需与 verify() 中 grep 字符串写法一致，实施时按最终脚本调整排除串。
- **VALIDATE**: `uv run pytest tests/test_packaging.py -q` 全绿。

### Task 9: 测试先行 —— `pipeline/applog.py`（GL-19）
- **ACTION**: 新建 `tests/test_applog.py`。
- **IMPLEMENT**（用例）:
  1. `log_dir` fixture：`monkeypatch.setenv("AI_CUT_LOG_DIR", str(tmp_path))`；每个用例结束 `applog.reset_for_tests()`（移除已装 handler，恢复 `sys.excepthook` / `threading.excepthook`）。
  2. `test_setup_writes_utf8_file`：`log = applog.setup("app")` → `log.info("转写开始")` → `(tmp_path/"app.log").read_text("utf-8")` 含「转写开始」；再次 `setup("app")` 不重复加 handler（写一行只出现一次）。
  3. `test_default_dir_is_library_logs`：未设 env 时 `applog.log_dir() == Path.home()/"Library/Logs/剪辑台"`（不创建）。
  4. `test_registered_secret_is_masked`：`applog.register_secret("AKLTsecretkey123456")` → 日志 `f"key={k}"` → 文件含 `AKLT****3456`、不含原文。
  5. `test_bearer_and_presigned_query_masked`：`"Authorization: Bearer sk-abcdef1234567890"` → 文件不含 `sk-abcdef1234567890`；`"https://tos.x/obj?X-Tos-Signature=SIG&X-Tos-Credential=CRED"` → 不含 `SIG`/`CRED`。
  6. `test_exception_args_masked`：`log.error("失败：%s", "AKLTsecretkey123456")`（参数里的秘密也要被脱敏——Filter 里先 `record.getMessage()` 再替换并清空 `args`）。
  7. `test_rotation`：`setup("app", max_bytes=200, backups=2)` 写 50 行 → 存在 `app.log.1`，且文件数 ≤ 3。
  8. `test_uncaught_thread_exception_logged`：起一个抛 `RuntimeError("线程炸了")` 的 `threading.Thread` → 文件含「线程炸了」与 `Traceback`。
  9. `test_stage_records_timing`：`with applog.stage(work_dir, "transcribe"):` 正常退出 → `work/timings.json["transcribe"]` 有 `seconds` (float ≥ 0) 与 `ok: True`；抛异常时 `ok: False` 且异常继续抛出。
- **MIRROR**: TEST_STRUCTURE（`tests/test_secrets.py:15-24` 的 monkeypatch 隔离）
- **VALIDATE**: RED。

### Task 10: 实现 `pipeline/applog.py`（GL-19）
- **IMPLEMENT**:
```python
# -*- coding: utf-8 -*-
"""日志落盘：~/Library/Logs/剪辑台/（PRD FR-13）。

  * 标准库 logging + RotatingFileHandler（5 MB × 5 份），UTF-8；
  * GUI 进程写 app.log，命令行进程写 cli.log —— RotatingFileHandler 不支持多进程写同一文件；
  * RedactFilter：已登记的密钥值 → secrets.mask()；Bearer 令牌、URL 查询串签名一律打码；
  * 未捕获异常（主线程 / 子线程）记 ERROR 带堆栈；
  * stage()：记录阶段耗时到 work/timings.json，诊断包会带上。
"""
from __future__ import annotations

import contextlib
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
from pathlib import Path

from pipeline import secrets

ROOT_LOGGER = "aicut"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 5
FORMAT = "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s"
_PATTERNS = (
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+"), r"\1****"),
    (re.compile(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]*"), r"\1?…"),
    (re.compile(r"\bsk-[A-Za-z0-9]{8,}"), "sk-****"),
)
_SECRETS: set[str] = set()
_LOCK = threading.Lock()


def log_dir() -> Path:
    if custom := os.environ.get("AI_CUT_LOG_DIR"):
        return Path(custom).expanduser()
    return Path.home() / "Library" / "Logs" / "剪辑台"


def register_secret(value: str | None) -> None:
    if value and len(value) >= 8:
        with _LOCK:
            _SECRETS.add(value)


def redact(text: str) -> str:
    for value in list(_SECRETS):
        text = text.replace(value, secrets.mask(value))
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True
```
  其余函数：
  - `setup(name: str = "app", *, max_bytes=MAX_BYTES, backups=BACKUPS) -> logging.Logger`：取 `logging.getLogger(ROOT_LOGGER)`；若已有 `getattr(h, "_aicut", False)` 的 handler 直接返回；`log_dir().mkdir(parents=True, exist_ok=True)`；`RotatingFileHandler(log_dir()/f"{name}.log", maxBytes=..., backupCount=..., encoding="utf-8")`，`h._aicut = True`，`addFilter(RedactFilter())`，`setFormatter(logging.Formatter(FORMAT))`；logger `setLevel(INFO)`、`propagate=False`；安装 `sys.excepthook` / `threading.excepthook`（记 `logger.error("未捕获异常", exc_info=...)` 后调用原钩子）；mkdir 失败（只读 home 等）→ 退回 `logging.NullHandler` 不崩；写一行 `启动 pid=… frozen=…`。
  - `get(child: str) -> logging.Logger`：`logging.getLogger(f"{ROOT_LOGGER}.{child}")`。
  - `stage(workdir: Path, key: str)`：`@contextlib.contextmanager`，`time.monotonic()` 计时；`finally` 里读-改-写 `workdir/timings.json`（`.tmp` + `os.replace`，坏 JSON 当空并记 warning），值 `{"started": ISO 时间, "seconds": round(x, 2), "ok": bool}`；同时 `get("stage").info("阶段 %s %s %.1fs", key, "完成" if ok else "失败", secs)`。
  - `reset_for_tests()`：移除 `_aicut` handler、清 `_SECRETS`、还原钩子。
- **MIRROR**: `pipeline/secrets.py` 的模块结构与中文 docstring；REPOSITORY_PATTERN（原子写）
- **GOTCHA**:
  - Filter 里必须先 `getMessage()` 合并 args 再脱敏，否则 `%s` 参数里的 Key 漏网。
  - `record.msg` 被改写后同一 record 若被其他 handler 再格式化不会二次合并 args（已置 None）。
  - 不要在 `setup()` 里调用 `secrets.get()`（会触发钥匙串弹窗）；密钥由客户端拿到时 `register_secret`。
- **VALIDATE**: `uv run pytest tests/test_applog.py -q` 全绿。

### Task 11: 接入日志（GL-19）
- **ACTION / IMPLEMENT**:
  1. `app/main.py`：`import` 后 `main()` 第一行 `applog.setup("app")`（在 `proc.ensure_bundled_path()` 之前）。
  2. `gui/server.py`：
     - 顶部 `from pipeline import applog, proc, review, schema, style`；`LOG = applog.get("gui")`。
     - `main()`（开发/浏览器版）开头 `applog.setup("app")`。
     - `log_message`（302-303）→ `LOG.debug("%s %s", self.address_string(), fmt % args)`。
     - `start_job`：任务开始 `LOG.info("任务开始 %s %s %s", job_id, task, name)`；`_JobLog.write` / dev `worker` 每追加一行同时 `applog.get("job").info("[%s] %s", job_id, line)`（抽一个小函数 `_job_append(job_id, lines)`，DRY 两处）；结束 `LOG.info/ warning("任务结束 %s 退出码 %s", ...)`；`except Exception` 分支改 `LOG.exception(...)`。
  3. `aicut.py`：`LOG = applog.get("cli")`；`die()` 里 `LOG.error(msg)`；`run_cli` 的 `except Exception` 分支加 `LOG.exception("命令异常：%s", argv[:2])`；`main()`：`if __name__ == "__main__":` 分支先 `applog.setup("cli")`（GUI 冻结同进程调用 `run_cli` 时不重复 setup，共用 app.log）。
  4. `cmd_prepare` / `cmd_build`：把阶段调用包进计时，抽助手避免重复：
```python
def _staged(pdir: Path, key: str, fn, args) -> None:
    with applog.stage(pdir / "work", key):
        fn(args)
```
     `cmd_prepare` 改为对 `[("ingest", cmd_ingest), ("transcribe", cmd_transcribe), ...]` 循环调用 `_staged`（保持原顺序与「无 DeepSeek Key 跳过 b 路」逻辑不变）。`cmd_build` 只包 `ensure_clips`、渲染预览、草稿生成三段（key: `clips` / `preview` / `draft`）。
  5. `pipeline/llm.py:50` 后加 `applog.register_secret(self.api_key)`；`pipeline/cloud.py` 构造函数同样加。
- **MIRROR**: LOGGING_PATTERN；SERVICE_PATTERN
- **GOTCHA**:
  - `die()` 的 `sys.exit` 会被 `applog.stage` 视为异常（SystemExit 继承 BaseException）：`stage` 用 `try/except BaseException: ok=False; raise`，保证失败阶段也写时长。
  - dev 模式 GUI 起子进程跑 aicut：子进程写 `cli.log`，GUI 进程把同样的行镜像进 `app.log` —— 有重复但不冲突（不同文件）。
  - 不要改 `print` 输出格式（前端按 `[x]`/`[✓]` 渲染）。
- **VALIDATE**: `uv run pytest -q` 全绿；手动 `AI_CUT_LOG_DIR=/tmp/aicut-logs uv run python aicut.py status <项目>` 后该目录出现 `cli.log`。

### Task 12: 测试先行 + 实现 `pipeline/diagnostics.py`（GL-19）
- **ACTION**: 先写 `tests/test_diagnostics.py`，再实现。
- **IMPLEMENT（测试用例）**:
  1. `test_bundle_contains_meta_logs_and_project_files`：tmp 日志目录放 `app.log`、`app.log.1`；tmp 项目放 `project.json`（含 `"material": "/Users/x/Movies/秘密素材.mov"`）、`work/timings.json`、`work/failed.json`、`work/transcript.md`（含「隐私原话」）；`build_bundle(out_dir, project_dir=p)` → zip 内有 `meta.json`、`logs/app.log`、`logs/app.log.1`、`project/project.json`、`project/work/timings.json`、`project/work/failed.json`、`project/files.txt`。
  2. `test_bundle_excludes_transcripts_and_media`：zip 内无 `transcript.md`/`*.wav`/`*.mp4`/`segments*.json`；`files.txt` 只列「相对路径 + 字节数」。
  3. `test_bundle_redacts_secrets_and_material_path`：日志里预埋已登记的 Key → zip 中所有文本不含原文；`project.json` 的 `material` 只剩文件名 `秘密素材.mov`。
  4. `test_meta_has_versions_and_masked_credentials`：`monkeypatch.setattr(diagnostics.secrets, "status", lambda: {"mediakit": {"configured": True, "source": "keyring", "masked": "AKLT****3456"}})` → `meta["credentials"]["mediakit"]["masked"] == "AKLT****3456"`；`meta` 有 `app_version`、`macos`、`arch`、`python`、`frozen`、`ffmpeg`（无 ffmpeg 时为 `null`，不崩）。
  5. `test_bundle_without_project`：`project_dir=None` 也能生成。
  6. `test_bundle_name_is_timestamped_and_unique`：两次调用不同名（`剪辑台诊断-YYYYmmdd-HHMMSS[-n].zip`）。
- **IMPLEMENT（模块要点）**:
```python
# -*- coding: utf-8 -*-
"""一键诊断包（PRD FR-13）：版本、阶段耗时、错误栈（日志）、脱敏配置。

不含：转写文本、音视频、分镜内容、API Key 明文。素材路径只保留文件名。
"""
SAFE_WORK_FILES = ("timings.json", "failed.json", "asr_task.json")
```
  - `app_version()`：冻结时 `plistlib.load(Path(sys.executable).resolve().parents[1] / "Info.plist")["CFBundleShortVersionString"]`；开发时 `tomllib` 读 `proc.app_root()/"pyproject.toml"` 的 `project.version`；都失败 → `"unknown"`。
  - `ffmpeg_info()`：`shutil.which("ffmpeg")` → `subprocess.run([ff, "-hide_banner", "-version"], timeout=5)` 取第一行与 `-L` 是否 LGPL；异常返回 `None`。
  - `build_bundle(out_dir: Path, project_dir: Path | None = None) -> Path`：用 `zipfile.ZipFile(tmp, "w", ZIP_DEFLATED)` 写到 `out_dir/".剪辑台诊断-….zip.part"` 再 `os.replace`；文本一律经 `applog.redact()`；日志取 `applog.log_dir().glob("*.log*")`；项目只取 `project.json`（`material` → `Path(v).name`）与 `SAFE_WORK_FILES`，外加 `files.txt`（`work/` 下 `rglob` 的相对路径 + `st_size`，不跟随符号链接）。
  - `default_out_dir()`：`Path.home()/"Downloads"`，不存在则 `Path.home()/"Desktop"`。
- **MIRROR**: REPOSITORY_PATTERN（`.part` + `os.replace`）
- **IMPORTS**: `json, os, platform, plistlib, shutil, subprocess, sys, time, tomllib, zipfile, pathlib.Path`；`from pipeline import applog, proc, secrets`
- **GOTCHA**: `secrets.status()` 会访问钥匙串（可能弹授权）——只在用户点按钮时调用；`project_dir` 必须先过 `server.project_path()` 校验（Task 13）。
- **VALIDATE**: `uv run pytest tests/test_diagnostics.py -q` 全绿。

### Task 13: GUI 入口「导出诊断包」（GL-19）
- **ACTION**:
  - `gui/server.py` `do_POST` 增加：
```python
        if p == "/api/diagnostics":
            from pipeline import diagnostics
            pdir = None
            if name := body.get("project"):
                try:
                    pdir = project_path(name)
                except ValueError:
                    return self._json({"error": "bad project"}, 400)
            try:
                path = diagnostics.build_bundle(diagnostics.default_out_dir(), pdir)
            except OSError as exc:
                LOG.exception("诊断包失败")
                return self._json({"error": f"导出失败：{exc}"}, 500)
            subprocess.run(["open", "-R", str(path)], capture_output=True)
            return self._json({"ok": True, "path": str(path)})
```
  - `gui/static/index.html`：侧栏（`#projects` 列表下方）加 `<button class="ghost" onclick="exportDiag()">导出诊断包</button>`；任务失败时弹窗里也渲染同一按钮；
```js
async function exportDiag(){
  try{
    const j = await api('/api/diagnostics', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({project: state.project})});
    toast('诊断包已保存到「下载」文件夹，已在访达中选中，直接拖进微信发给开发者', 4000);
  }catch(e){ toast(e.message, 4000); }
}
```
- **MIRROR**: `gui/server.py:608-621`（`/api/open` 的写法与 `open` 调用）；`index.html:162-167` 的 `api()`
- **GOTCHA**:
  - M1（GL-05）落地后所有 POST 需要 token/Origin 校验 —— 本路由必须挂在同一入口之后，不得单独绕过；若 M1 先合入，按其约定传 token。
  - 失败弹窗的关闭逻辑属 GL-22（M4），这里只**加按钮**不改弹窗行为。
  - 路径 toast 不显示完整 home 路径以外的信息即可；不弹系统对话框（KISS）。
- **VALIDATE**: 手动：`uv run python app/main.py` → 点「导出诊断包」→ Finder 选中 zip，解压检查内容不含 Key / 转写文本；计时从点击到可发送 < 1 分钟（FR-13 验收）。

### Task 14: GL-03 交付说明（文档）
- **ACTION**:
  1. 新建 `packaging/首次打开说明-macOS.txt`（UTF-8，面向剪辑师，口吻同 `dist/给剪辑师的使用说明.txt`）：
```
第一次打开「AI粗剪」（只需要做一次）

macOS 15（Sequoia）及以后：
1. 把 AI粗剪.app 拖进「应用程序」文件夹，双击打开。
2. 弹出「无法打开 / Apple 无法验证…」时，点「完成」（不要点「移到废纸篓」）。
3. 打开「系统设置」→「隐私与安全性」，滚到最下面，
   会看到「已阻止 AI粗剪 以保护 Mac」，点旁边的「仍要打开」。
4. 再点一次「仍要打开」，输入开机密码。以后直接双击就能用。
   （这个按钮在第 1 步之后大约一小时内有效；找不到就重新双击一次 App 再去看。）

macOS 13 / 14：
   在「应用程序」里按住 Control 点 AI粗剪.app →「打开」→ 再点「打开」。

第一次运行会弹「钥匙串」授权（读取你填的 API Key），选「始终允许」。

为什么会被拦：这个 App 没有花钱向苹果做开发者签名和公证，只在你们工作室内部使用，不是病毒。
出问题时：在 App 左下角点「导出诊断包」，把「下载」文件夹里的 zip 发给开发者。
日志位置：~/Library/Logs/剪辑台/
```
  2. `docs/PACKAGING.md`：第 56 行改为「未签名/未公证：macOS 15+ 首次打开须到 系统设置 → 隐私与安全性 → 仍要打开（详见 `packaging/首次打开说明-macOS.txt`，随 dist 交付）；macOS 13/14 可右键 → 打开」；第 57 行改为「ffmpeg 为 LGPL 构建（`packaging/build_ffmpeg.sh`，源码 SHA256 钉死，无 x264/x265），H.264 用 VideoToolbox；许可见 THIRD-PARTY-NOTICES」；第 10-11 行「首次自动下载」改为「首次从源码构建（5–10 分钟，需 Xcode CLT + pkg-config）」；新增「日志与诊断」小节（`~/Library/Logs/剪辑台/app.log|cli.log`，5MB×5 轮转；诊断包内容清单）；性能表「生成 540p 分析代理」备注 `ultrafast/crf30` → `VideoToolbox 1.5Mbps`（时长以实测为准，见手动验证）。
  3. `docs/交付形态调研.md:41,151`：「首次右键打开」→「macOS 15+：系统设置 → 隐私与安全性 → 仍要打开」。
- **GOTCHA**: `dist/给剪辑师的使用说明.txt` 是 **Windows 剪映导入包**的说明（`build_package.py` 产物，不入库），与 Mac App 无关，不改。
- **VALIDATE**: `grep -rn "右键 → 打开\|右键→打开\|右键打开" docs packaging` 只剩「macOS 13/14」语境。

### Task 15: 收尾 —— 文档同步与登记册
- **ACTION**: `docs/TECH-STACK.md` 第 17 行版本「≥6.1」→「8.1.3（LGPL 自建）」、第 19-20 / 93 行改 HTTP 直连、第 146 行改「已采用 LGPL 构建」；`docs/go-live-blockers.md` GL-01/03/04/19 状态 `open` → `done（<commit>）`；`docs/PROGRESS.md:23,70` 同步。
- **VALIDATE**: `uv run pytest -q` 全绿（基线 112 passed + 新增用例）。

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| upload→submit | 本地 wav | UPLOAD→PUT(无 Auth)→SUBMIT(audio_url=mediakit://) | |
| upload 缓存 | 有效 `asr_upload.json` | 不再上传 | ✓ size/mtime 变化 → 重传 |
| 503 重试 | 503, 200 | 2 次，同 client_token | ✓ |
| 网络错误 | 抛 CloudError, 200 | 重试成功 | ✓ |
| 业务失败 | 200 + success=false | 立即失败、不重试 | ✓ |
| 401 | 401 | 「Key 无效」，不含 Key | ✓ |
| 轮询 | running→queued→completed | 拍平 result | |
| failed/canceled | status=failed | 含后端 message | ✓ |
| 超时 | monotonic 前进 | 文案含「不会重新提交」 | ✓ |
| 续查 | asr_task.json | 只 GET 1 次 | |
| 脱敏 | 403 正文含签名 | failed.json 无签名、无 Key | ✓ |
| task_id 转义 | `a/b` | `a%2Fb` | ✓ |
| h264_args | proxy/clip/preview | VT + 显式码率 + yuv420p | |
| 无 libx264 | 全部代码 | 0 命中 | |
| notices 覆盖 | uv.lock 闭包 | 无遗漏 | |
| build_ffmpeg 守卫 | 脚本文本 | 无 GPL 开关、钉 SHA256、curl -f | |
| 日志落盘/轮转 | 写 50 行 | `app.log.1` 存在 | ✓ |
| 日志脱敏 | Key / Bearer / 预签名 | 全部打码 | ✓ |
| 线程异常 | 子线程抛错 | 记录带堆栈 | ✓ |
| 阶段计时 | 正常 / 异常 / SystemExit | timings.json ok=True/False | ✓ |
| 诊断包 | 日志+项目 | 含 meta/logs/timings/failed；不含转写/媒体/Key | ✓ |

### Edge Cases Checklist
- [x] 空输入：无 Key（cloud / diagnostics 凭证状态）、无项目的诊断包
- [x] 最大输入：3 小时音频（服务端上限）——上传超时 600s、轮询总超时 `max(900, dur*3+600)` 不变
- [x] 非法类型：`upload_headers` 两种格式；非 JSON 响应
- [x] 并发：RotatingFileHandler 分进程分文件；`register_secret` 加锁
- [x] 网络故障：上传 / 提交 / 轮询各自重试；轮询耗尽后保留 task 供续查
- [x] 权限：日志目录不可写 → NullHandler 不崩；401/403 明确提示
- [ ] 真机：干净 Mac 首次打开 + 真账号转写（手动，见下）

---

## Validation Commands

### Static Analysis
```bash
# 仓库未配置 lint / typecheck（CLAUDE.md）；做语法级检查：
uv run python -m compileall -q aicut.py pipeline gui app
bash -n packaging/build_ffmpeg.sh packaging/build_app.sh
```
EXPECT: 无输出、退出码 0

### Unit Tests
```bash
uv run pytest tests/test_cloud.py tests/test_encode.py tests/test_packaging.py tests/test_applog.py tests/test_diagnostics.py -q
```
EXPECT: All pass

### Full Test Suite
```bash
uv run pytest -q
```
EXPECT: 基线 112 passed + 新增用例全部通过，无回归

### 守卫 grep
```bash
grep -rn "libx26[45]" aicut.py pipeline gui        # 期望无输出
grep -rn "mediakit-cli\|env_with_secret\|mediakit_env" aicut.py pipeline gui   # 只允许 cloud.py docstring 的出处说明
```

### Packaging（手动）
```bash
./packaging/build_ffmpeg.sh                 # 首次 5–10 分钟
./packaging/build_ffmpeg.sh --verify-only   # 退出 0
./packaging/build_app.sh
otool -L "dist/AI粗剪.app/Contents/Frameworks/bin/ffmpeg"   # 只有 /System/Library 与 /usr/lib
"dist/AI粗剪.app/Contents/Frameworks/bin/ffmpeg" -hide_banner -L | head -3   # GNU Lesser General Public License
ls dist/THIRD-PARTY-NOTICES.txt dist/首次打开说明-macOS.txt dist/sources/
```
EXPECT: 全部存在且通过

### Manual Validation
- [ ] **ASR 回归**（开发机，真账号）：对一个已有 `work/transcript_raw.json` 的旧项目复制一份、删掉 `transcript_raw.json`/`asr_task.json`，跑 `uv run python aicut.py transcribe <项目>`；新旧 `subtitles` 条数、首尾时间码、文本逐句比对一致（允许服务端细微差异，人工确认）。
- [ ] **续查**：转写中途 Ctrl-C → 重跑 → 日志出现「续查上次的子任务」，控制台无重复上传/提交（MediaKit 控制台任务数 +1 而非 +2）。
- [ ] **编码画质**：同一项目 `build` 新旧版本对比预览片 / 切片画质与体积；剪映（Mac + Windows）能打开新草稿并播放。
- [ ] **性能**：54 分钟素材生成 540p 代理耗时记录到 PACKAGING.md 性能表。
- [ ] **干净 Mac 放行检查**（新用户账户、无 brew/Node、macOS 15）：按「首次打开说明」打开 → 填 Key → 处理素材（转写成功）→ 生成成片 → 导出诊断包（<1 分钟）→ 检查 `~/Library/Logs/剪辑台/app.log` 无 Key。
- [ ] `ffmpeg` 构建产物在干净 Mac 上 `ffmpeg -version` 可运行（无 dyld 错误）。

---

## Acceptance Criteria
- [ ] GL-01：App 内转写不调用任何外部进程；同一 MediaKit Key；续查与幂等语义保持；Key 与预签名 URL 不出现在日志/异常/failed.json
- [ ] GL-03：PACKAGING.md 与随 dist 的说明写明 macOS 15+「仍要打开」路径
- [ ] GL-04：全仓无 libx264；内置 ffmpeg 通过 LGPL / 链接库 / 编码器 / 滤镜自检；源码哈希钉死、`curl -f`；随包 THIRD-PARTY-NOTICES + 许可全文 + 源码
- [ ] GL-19：日志落 `~/Library/Logs/剪辑台/` 并轮转；脱敏；GUI 一键导出诊断包（版本、阶段耗时、错误栈、脱敏配置）
- [ ] 所有验证命令通过；新测试先 RED 后 GREEN
- [ ] 无新增依赖

## Completion Checklist
- [ ] 代码遵循发现的模式（transport 注入、RETRY_STATUS、中文错误、原子写）
- [ ] 错误处理与 llm.py 一致；Key 永不入异常
- [ ] 日志不改变现有 `print` 前缀输出
- [ ] 测试遵循 test_llm / test_secrets 写法
- [ ] 无硬编码秘密；码率、端点、哈希均为命名常量
- [ ] 文档已更新（PACKAGING / TECH-STACK / 交付形态调研 / GUI / 登记册）
- [ ] 未越界实现 GL-16 / KI-29 / KI-37 / M1 / M4 内容
- [ ] 自包含：实施无需再搜索代码库

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 后端校验 `X-Amk-*` 头或拒绝非 CLI 客户端 | 低-中 | 高 | 头值集中在 `CLIENT_HEADERS`；真账号冒烟先跑（需用户操作）；必要时改为 CLI 同值（`X-Amk-Task-Source: cli/skill` 是旧代码经 `MEDIAKIT_SURFACE=skill` 实际发出的值） |
| 预签名 PUT 对 Content-Type / chunked 敏感 | 中 | 中 | 严格按 `upload_headers` 设头 + 显式 Content-Length；单测断言 |
| MediaKit HTTP API 非公开文档、未来变更 | 中 | 高 | 协议出处钉在 docstring（mediakit-cli 0.2.1）；`transcript_raw.json` 形状与旧产物一致便于回归 |
| 自建 ffmpeg 误链 Homebrew 动态库 | 中 | 高 | `--disable-autodetect` + `otool -L` 自检失败即中止构建 |
| VideoToolbox 码率下画质/体积与 x264 不同 | 中 | 中 | 显式码率 + 手动对比；参数集中在 `encode.BITRATES` 便于调整 |
| 10-bit/HDR 素材 VT 报像素格式错误 | 中 | 中 | `-pix_fmt yuv420p` |
| 构建机缺 pkg-config / CLT | 低 | 低 | 脚本开头检测并给出提示；只影响开发者 |
| 诊断包误带隐私内容 | 低 | 高 | 白名单文件 + `redact()` + 测试断言 |
| 与 M1/M4 并行修改 `gui/server.py`、`index.html` 冲突 | 中 | 低 | 本计划只加路由/按钮与日志行，改动面小；合入顺序以 PRD 里程碑为准 |

## Notes

**方案取舍**
- GL-01 备选「把 mediakit-cli 的 Go 二进制（MIT，7MB，arm64）打进 App」可行但否决：仍是外部进程、需随版本追更、子进程超时问题仍在（cloud.py:122-123 的历史教训），且 GL 条目明确要求「Python 直连 HTTP API（同 llm.py 写法）」。
- GL-04 备选预编译包全部不合格（ae-ffmpeg 无 drawtext 且停更；martin-riedl / osxexperts / evermeet 为 GPL；BtbN 无 macOS），故采用「钉哈希源码 + 仓库内构建脚本」，满足 PRD §7「可复现构建」。
- 已核实 pyJianYingDraft 为 Apache-2.0（非 GPL），无额外许可风险。
- 凭证：直连 API 用的仍是现有 `MEDIAKIT_API_KEY`（Bearer），**不需要新凭证**。

**需用户决策**
1. **LGPL 源码随附方式**：计划默认把 `ffmpeg-8.1.3.tar.xz`、`freetype-2.14.3.tar.xz` 与 `build_ffmpeg.sh` 放进 `dist/sources/` 与 App 一起发（约 +14 MB）。若只想附「书面提供源码」声明而不随包，请确认（FFmpeg legal 清单第 3/8 条倾向随附）。
2. **「关于」入口**：FFmpeg 清单第 10 条要求在程序关于框声明使用 FFmpeg/LGPL。App 目前没有关于页；本计划不做 GUI 关于页，只在 App 包 `licenses/` 与 dist 附声明。是否另加一个「关于 / 第三方许可」按钮？（产品/UI 决策）
3. **诊断包内容边界**：默认**不含**转写文本、分镜、素材完整路径（只留文件名）。若希望带上 `segments.json` 等便于复现选段问题，需确认隐私取舍（PRD §7：日志与项目文件不得含 API Key；转写文本属于用户内容）。
4. **诊断包保存位置**：默认 `~/Downloads`（不存在则桌面）并在访达中选中；如更希望放桌面请告知。
5. **VideoToolbox 码率**：proxy 1.5 Mbps / 切片 12 Mbps / 预览 8 Mbps 为工程默认值，画质/体积是否可接受需剪辑师看片确认。
6. **X-Amk 统计头取值**：默认 `X-Amk-Cli-Runtime: aicut`、`X-Amk-Task-Source: cli/aicut`、不发 `X-Amk-Cli-Version`；若希望与旧流程完全一致（`cli/skill` + CLI 版本号），请确认。

**需用户操作**
1. **真账号冒烟**：在开发机用真实 MediaKit Key 跑一次 `transcribe`（会产生一次 ASR 计费），确认上传 / 提交 / 查询全通，并与旧 `transcript_raw.json` 对比。
2. **干净 Mac 放行检查**：新建 macOS 15 用户账户（无 brew/Node）走完整流程（PRD Success Metrics 第一行）；这是 GL-01/03/04/19 的最终验收，只能人工完成。
3. **剪映打开验证**：VideoToolbox 编码的切片生成草稿后，在 Mac 与 Windows 剪映各打开播放一次。
4. 构建机需已装 Xcode Command Line Tools 与 `pkg-config`（本机已具备，换机构建时需安装——改依赖类操作需你确认）。

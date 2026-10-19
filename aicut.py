#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aicut —— 把视频剪辑流水线固化成一条命令。

设计目标：
  1. 一个入口：所有动作都是 `python3 aicut.py <命令>`
  2. 一份配置：每个项目一个 project.json，想改风格/平台/时长改这里
  3. 一层可调：shots.json（分镜表）是唯一需要手改的地方，改完只重出，不重跑 ASR
  4. 版本不覆盖：每次出片进 output/v1 v2 v3，剪映草稿名也带版本号

命令：
  new <项目名> --material <原片> [--title 片名] [--preset 纪实3min] [--target 秒]
  run <项目名> [--version v2] [--no-draft]   全流程（已完成的自动跳过）
  ingest <项目名>              素材台账
  transcribe <项目名>          抽音轨 + 云端转写 + 分段文稿
  junk <项目名>                代理片 + 规则层废片检测
  brief <项目名>               生成"给 AI/给人看"的策划分派单
  select <项目名> [--target 秒]  改目标时长后只重跑选段（不转写、不调 LLM）
  build <项目名> [--version v2] [--no-draft]   分镜表 → 切片 → 预览 → 剪映草稿
  status <项目名>              看每个环节的状态
  list                         列出所有项目
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pipeline.pyver import require_supported_python; require_supported_python()  # noqa: E702 先于新语法
from pipeline import (applog, build_documentary, classify, cloud, consent, encode, export_draft,  # noqa: E402
                      jy_env, media_io, notices, proc, questions, readiness, review, schema, secrets,
                      select, style, summarize, to_jianying, understand_audio, understand_text, understand_visual)
from pipeline.llm import LLMError

ROOT = proc.app_root()
PROJECTS = proc.user_data_root()
PRESETS = proc.resource_path("presets")
proc.ensure_bundled_path()
JY_VENV = Path.home() / ".aicut/venv"
LOG = applog.get("cli")


# ------------------------------------------------------------------ 基础
def die(msg: str) -> None:
    LOG.error(msg)
    print(f"[x] {msg}")
    sys.exit(1)


def info(msg: str) -> None:
    print(f"[·] {msg}")


def ok(msg: str) -> None:
    print(f"[✓] {msg}")


def warn(msg: str) -> None:
    print(f"[!] {msg}")


TARGET_PROMPT = "想剪成多长的片子？（秒，回车用预设 {default} 秒）"
TEXT_PARTIAL_WARNING = ("上次逐句标注没有完成（work/segments_text.partial.json），"
                        "这次分档用的是上一次完整的标注结果；重新运行「处理素材」可补齐")
TEXT_INCOMPLETE_STATUS = "未完成"
TARGET_CHANGED = "目标时长已改为 {target}，只重跑选段"
CLIP_VF = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
           "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30")
MEDIA_SUFFIXES = (".wav", ".mp4")  # 这些产物以完成标记判定（GL-15；旧项目可被认领），其余看存在
DRAFT_LOG_LINES = 40  # 草稿失败时打印的日志行数（按行截，不按字符，KI-60）
DRAFT_NOT_INSTALLED = "草稿未安装（已回滚，剪映草稿库保持原样）"
PREPARE_KEYS_MISSING = ("缺少 {names}：在剪辑台「⚙ 设置 · API Key」里填写，"
                        "或运行 `uv run python aicut.py config set <mediakit|deepseek>`")
DIR_NOT_EMPTY = "{pdir} 已存在且不是空目录（也不是项目），换个项目名"
MUST_KEEP_OVER_HINT = ("必留内容共 {must}，超过目标 {target}。想剪成多长？"
                       "运行：aicut.py select {name} --target <秒>（建议 --target {suggest}）")
INGEST_FAILED = "素材读不出来：{reason}"
PRESET_MISSING = "找不到预设 {preset}（presets/{preset}.json），可用：{names}"
LIST_CORRUPT = "（project.json 损坏）"


def load_json(p: Path, default=None):
    return schema.read_json(p, default=default)  # 损坏抛 CorruptJSON，由 main() 统一变成人话（KI-21）


def load_preset(name: str) -> dict:
    if (preset := load_json(PRESETS / f"{name}.json")) is None:
        die(PRESET_MISSING.format(preset=name, names=[p.stem for p in PRESETS.glob("*.json")]))
    return preset


def save_json(p: Path, obj) -> None:
    schema.write_json(p, obj)


def check_or_die(check, value) -> None:
    """调用 schema 的白名单校验；不合法就 die（GL-06）。"""
    try:
        check(value)
    except ValueError as exc:
        die(str(exc))


def project_dir(name: str) -> Path:
    check_or_die(schema.check_project_name, name)
    p = PROJECTS / name
    if not (p / "project.json").exists():
        die(f"项目不存在：{name}（用 new 创建）")
    return p


def cfg(pdir: Path) -> dict:
    return schema.load(pdir / "project.json")


def ensure_jy_python() -> str:
    """剪映草稿依赖 pyJianYingDraft：打包版已打进 App；开发态用专用 venv（旧版 Python 建的会重建，KI-82）。"""
    if proc.FROZEN:
        return sys.executable
    try:
        return jy_env.ensure(JY_VENV)
    except jy_env.JyEnvError as exc:
        die(str(exc))


def _run_pipeline(module: str, argv: list[str]) -> None:
    """跑一个 pipeline 脚本：开发用子进程，打包后同进程导入。"""
    if proc.FROZEN:
        code, out = proc.run_inprocess(module, argv)
        if code != 0:
            print(out[-600:])
            die(f"{module} 执行失败")
        return
    r = subprocess.run(proc.dev_module_cmd(sys.executable, module, argv), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print((r.stdout or "")[-600:], (r.stderr or "")[-600:])
        die(f"{module} 执行失败")


def require_consent() -> None:
    """任何把数据发到云端（ASR / LLM）的步骤之前调用：没确认过外发说明就停（PRD §7）。"""
    if not consent.accepted():
        die(consent.CLI_REQUIRED_MSG)


# ------------------------------------------------------------------ 命令
def cmd_new(args) -> None:
    check_or_die(schema.check_project_name, args.name)
    pdir = PROJECTS / args.name
    if (pdir / "project.json").exists():
        die(f"项目已存在：{pdir}")
    if pdir.exists() and (not pdir.is_dir() or any(pdir.iterdir())):
        die(DIR_NOT_EMPTY.format(pdir=pdir))  # 上次失败留下的空目录可以复用（GL-20）
    src = Path(args.material).expanduser().resolve()
    if not src.exists():
        die(f"原片不存在：{src}")
    preset = load_preset(args.preset)
    no_input = getattr(args, "no_input", False)  # GUI 调用：绝不 input()（GL-20）
    target = getattr(args, "target", None)
    if target is not None:  # 先校验再建目录：失败不留空项目
        check_or_die(schema.check_target_duration, target)
        target = schema.check_target_duration(target)
    else:
        default = schema.check_target_duration(preset.get("duration") or 175)
        target = default if no_input else ask_target(default)
    given = {k: v for k, v in {"tone": args.tone, "audience": args.audience,
                               "must_lines": args.must_lines}.items() if v is not None}
    calibration = style.normalize(given) if given or no_input else ask_calibration({})
    project = schema.default_project(
        args.name, str(src),
        title=args.title or args.name,
        preset=args.preset,
        platform=preset.get("platform", "douyin"),
        target_duration=target,
        created=time.strftime("%Y-%m-%d %H:%M:%S"),
        calibration=calibration,
    )
    created = not pdir.exists()
    pdir.mkdir(parents=True, exist_ok=True)
    try:
        schema.save(pdir / "project.json", project)
    except BaseException:
        if created:  # 只清自己建的目录，重试同名不会撞上空目录
            shutil.rmtree(pdir, ignore_errors=True)
        raise
    ok(f"项目已创建：{pdir}")
    info(f"下一步：python3 aicut.py run {args.name}")


def cmd_ingest(args) -> None:
    pdir = project_dir(args.name)
    try:  # KI-66 / KI-19：认不出的素材给人话，不给 KeyError
        entry = media_io.material_entry(Path(cfg(pdir)["material"]))
    except media_io.MediaError as exc:
        die(INGEST_FAILED.format(reason=exc))
    save_json(pdir / "work/materials.json", {"items": [entry]})
    ok(f"素材台账：{entry['duration'] / 60:.1f} 分钟，{entry['size'] / 1e9:.1f} GB")


def cmd_transcribe(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    work = pdir / "work"
    wav = work / "audio/asr.wav"
    raw = work / "transcript_raw.json"
    if not media_io.complete_or_adopt(wav):
        info("抽音轨…")
        try:
            media_io.ffmpeg_to(wav, ["-i", c["material"], "-vn", "-ac", "1", "-ar", "16000",
                                     "-c:a", "pcm_s16le"])
        except media_io.MediaError as exc:
            die(f"抽音轨失败：{exc}")
    if not raw.exists():
        require_consent()
        if not secrets.get("mediakit"):
            die("未配置 MEDIAKIT_API_KEY：运行 `uv run python aicut.py config set mediakit`")
        info("获取云端转写结果（长素材要几分钟，中断后重跑会接着查）…")
        client = cloud.CloudClient()
        try:
            client.transcribe(wav, work, duration_s=media_io.duration_or_zero(wav))
        except cloud.CloudError as exc:
            die(f"转写失败：{exc}")
    info("整理分段文稿…")
    _run_pipeline("pipeline.format_transcript", [str(raw), "-o", str(work)])
    ok("转写完成 → work/transcript.md / work/segments.json")


def cmd_analyze(args) -> None:
    """a 路：给每句算响度/语速/停顿/抢话。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    wav, segs = work / "audio/asr.wav", work / "segments.json"
    if not media_io.complete_or_adopt(wav) or not segs.exists():
        die("先跑 transcribe（需要 work/audio/asr.wav 与 work/segments.json）")
    res = understand_audio.run(wav, segs, work / "segments_audio.json")
    interrupts = sum(1 for x in res["segments"] if x["signals"]["interrupt"])
    ok(f"声音特征：{len(res['segments'])} 句 · 中位响度 {res['median_db']} dB · "
       f"抢话 {interrupts} 处")


def cmd_text(args) -> None:
    """b 路：LLM 话题分段 + 信息标注。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    segs = work / "segments.json"
    if not segs.exists():
        die("先跑 transcribe（需要 work/segments.json）")
    require_consent()
    if not secrets.get("deepseek"):
        die("未配置 DEEPSEEK_API_KEY：运行 `uv run python aicut.py config set deepseek`")
    batch = getattr(args, "batch", 40)
    model = getattr(args, "model", "deepseek-chat")
    info(f"调用 {model} 做话题分段与逐句标注（{batch} 句/批）…")
    pref = style.directive(cfg(pdir).get("calibration"))
    if pref:
        info("已应用剪辑偏好：" + pref)
    try:
        res = understand_text.run(segs, work / "segments_text.json",
                                  batch=batch, model=model, style=pref)
    except LLMError as exc:  # GL-09：含 AnnotationIncomplete；不能当成功往下走
        die(str(exc))
    key = sum(1 for x in res["segments"] if x["key_info"])
    ok(f"话题 {len(res['topics'])} 个 · 关键信息 {key} 句"
       + (" · 已补齐上次失败的句子" if res.get("resumed") else ""))


def cmd_score(args) -> None:
    """合成三档：废片 / 待定 / 可用。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    text = work / "segments_text.json"
    if not text.exists():
        die("先跑 text（需要 work/segments_text.json）")
    c = cfg(pdir)
    if understand_text.partial_path(text).exists():
        warn(TEXT_PARTIAL_WARNING)
    try:
        res = classify.run(text, work / "segments_audio.json",
                           work / "segments_scored.json",
                           total_target=float(c.get("target_duration") or 175),
                           visual_path=work / "visual_quality.json")
    except classify.TextIncomplete as exc:
        die(str(exc))
    s = res["summary"]
    flagged = sum(1 for x in res["segments"] if x.get("visual_flags"))
    demoted = (res.get("pending") or {}).get("demoted", 0)
    ok(f"废片 {s['waste']} · 待定 {s['pending']} · 可用 {s['usable']}"
       + (f" · 画面异常 {flagged}" if flagged else "")
       + (f" · 自动降级 {demoted}" if demoted else ""))
    for w in res.get("warnings") or []:
        warn(w)


def cmd_junk(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    work = pdir / "work"
    proxy = work / "proxy.mp4"
    if not media_io.complete_or_adopt(proxy):
        info("生成 540p 分析代理…")
        try:
            media_io.ffmpeg_to(proxy, ["-i", c["material"], "-vf", "scale=-2:540,fps=30",
                                       *encode.h264_args("proxy"),
                                       "-c:a", "aac", "-b:a", "64k"])
        except media_io.MediaError as exc:
            die(f"生成分析代理失败：{exc}")
    _run_pipeline("pipeline.junk_detect", [str(proxy), "-o", str(work), "--scene"])
    ok("废片检测完成 → work/junk_report.csv")


def cmd_scenes(args) -> None:
    """c 路第一层：在代理片上切镜头。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    proxy = work / "proxy.mp4"
    if not media_io.complete_or_adopt(proxy):
        die("先跑 junk（需要 work/proxy.mp4）")
    info("分析镜头切点（在代理片上跑，长素材要 1–3 分钟）…")
    try:
        res = understand_visual.run(proxy, work / "shots_visual.json", threshold=getattr(args, "threshold", 8.0))
    except media_io.MediaError as exc:  # KI-19：坏素材不能得到「1 个镜头」
        die(f"镜头切分失败：{exc}")
    ok(f"镜头 {len(res['shots'])} 个（切点 {res['cut_count']}）")


def cmd_quality(args) -> None:
    """画面质量：亮度/运动/清晰度，按句聚合。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    proxy, segs = work / "proxy.mp4", work / "segments.json"
    if not media_io.complete_or_adopt(proxy) or not segs.exists():
        die("先跑 junk 与 transcribe（需要 proxy.mp4 与 segments.json）")
    info("抽帧分析画面质量（1 fps，长素材约 30–90 秒）…")
    try:
        res = understand_visual.run_quality(proxy, segs, work / "visual_quality.json")
    except media_io.MediaError as exc:  # 画面质量只是加分项：[!] 提示后继续，分档会注明没用上（M8 审查）
        return warn(understand_visual.QUALITY_SKIPPED.format(reason=exc))
    counts: dict[str, int] = {}
    for v in res["segments"].values():
        for f in v.get("flags", []):
            counts[f] = counts.get(f, 0) + 1
    detail = " · ".join(f"{k} {n}" for k, n in sorted(counts.items())) or "无明显异常"
    ok(f"画面质量：{res['samples']} 帧 · {detail}")


def cmd_summary(args) -> None:
    """1.5 内容摘要：一句话 + 3–6 个关键信息。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    text, scored = work / "segments_text.json", work / "segments_scored.json"
    if not text.exists() or not scored.exists():
        die("先跑 text 与 score")
    require_consent()
    info("生成内容摘要…")
    pref = style.directive(cfg(pdir).get("calibration"))
    res = summarize.run(text, scored, work / "content_summary.json", style=pref)
    if res["fallback"]:  # KI-22：兜底要说出原因
        warn(notices.fallback_notice(notices.SUMMARY_FALLBACK_NOTICE, res))
    ok(res["summary"])


def cmd_questions(args) -> None:
    """2.4 由内容生成 3–5 个决策问题。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    summary, scored = work / "content_summary.json", work / "segments_scored.json"
    if not summary.exists() or not scored.exists():
        die("先跑 score 与 summary")
    out = work / "questions.json"
    if not getattr(args, "force", False) and questions.reusable(out):  # KI-22：未作答的兜底重新生成
        if (cached := load_json(out)).get("fallback"):
            warn(notices.fallback_notice(notices.QUESTIONS_FALLBACK_NOTICE, cached))
        info("决策问题已存在，跳过（--force 可重新生成，但会让已保存答案失效）")
        return
    require_consent()
    res = questions.run(summary, scored, out)
    if res["fallback"]:
        warn(notices.fallback_notice(notices.QUESTIONS_FALLBACK_NOTICE, res))
    ok(f"决策问题 {len(res['questions'])} 个")
    for q in res["questions"]:
        info(f"  {q['text']} → " + " / ".join(o["label"] for o in q["options"]))


def cmd_select(args) -> None:
    """M3 覆盖式选段：按话题预算挑镜头，输出选段表与时间线。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    if not (work / "segments_scored.json").exists():
        die("先跑 score")
    c = cfg(pdir)
    new_target = None
    if getattr(args, "target", None) is not None:  # prepare 透传的 args 没有 target
        check_or_die(schema.check_target_duration, args.target)
        new_target = schema.check_target_duration(args.target)
        c = {**c, "target_duration": new_target}
    try:
        res = select.run(work / "segments_scored.json", work / "brief_answers.json", work,
                         questions_path=work / "questions.json",
                         title=c.get("title", args.name), material=c["material"],
                         weights=style.weights(c.get("calibration")),
                         calibration=c.get("calibration"),
                         target=float(c.get("target_duration") or 175))
    except select.SelectionError as exc:
        die(str(exc))
    if new_target is not None:  # 选段成功后才保存新目标
        schema.save(pdir / "project.json", c)
        info(TARGET_CHANGED.format(target=select.fmt_duration(new_target)))
    _report_selection(res, args.name)


def _report_selection(res: dict, name: str) -> None:
    missing, must_n = res["missing_must_topics"], res["stats"].get("must_keep", 0)
    ok(f"选段 {res['stats']['shots']} 镜 · {res['total']:.0f}s / 目标 {res['target']:.0f}s"
       + (f" · 必留 {must_n} 段" if must_n else "")
       + (f" · 未覆盖必留话题 {len(missing)}" if missing else ""))
    if res.get("over_target"):
        warn(MUST_KEEP_OVER_HINT.format(must=select.fmt_duration(res["must_keep_total"]),
                                        target=select.fmt_duration(res["target"]),
                                        name=name, suggest=res["suggested_target"]))
    for w in res.get("warnings") or []:
        warn(w)


def cmd_export(args) -> None:
    """M4 导出：时间线 → Windows 可双击导入的剪映包。"""
    pdir = project_dir(args.name)
    timeline = Path(args.timeline) if args.timeline else None
    if timeline is None:
        candidates = sorted((pdir / "output").glob("*/timeline.json"),
                            key=lambda x: x.stat().st_mtime, reverse=True)
        if not candidates:
            die("找不到时间线，先跑 select 与 build_documentary，或指定 --timeline")
        timeline = candidates[0]
        info(f"使用最新时间线：{timeline.relative_to(pdir)}")
    name = args.package_name or f'{pdir.name.split("_")[0]}_{timeline.parent.name}'
    out = Path(args.out) / f"{name}.zip"
    info("生成草稿并打包（媒体要拷一遍，几分钟）…")
    try:
        res = export_draft.build_windows_package(timeline, name, out)
    except (RuntimeError, FileNotFoundError) as exc:
        die(str(exc))
    for w in res.get("warnings", []):  # KI-18：子进程成功时的警告不能吞掉
        warn(w)
    ok(f"已导出：{out}（{res['size'] / 1e6:.0f} MB）")


def cmd_brief(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    preset = load_preset(c["preset"])
    segs = load_json(pdir / "work/segments.json", {}).get("segments", [])
    junk = load_json(pdir / "work/junk_report.json", {}).get("items", [])
    lines = [f"# 策划分派单 · {c['title']}", "",
             f"- 原片：`{c['material']}`",
             f"- 预设：{preset.get('name')}（{preset.get('duration')}s，{c['platform']}）",
             f"- 结构建议：{' → '.join(preset.get('structure', []))}",
             f"- 字幕：≤{preset.get('subtitle', {}).get('max_chars', 14)} 字/行",
             "", f"## 分段文稿（{len(segs)} 段）", ""]
    for s in segs:
        lines.append(f"**[{s['id']}] {s['start']:.1f}–{s['end']:.1f}s** {s['text']}")
    if junk:
        lines += ["", "## 规则层废片候选", ""]
        for j in junk:
            lines.append(f"- {j['start_tc']}–{j['end_tc']} {j['reason']}（{j['suggest']}）")
    lines += ["", "## 产出要求", "",
              "写 `shots.json`：每镜含 id / in / out / sub / note；",
              "再跑 `python3 aicut.py build <项目> --version v1` 出片。"]
    out = pdir / "work/brief.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    ok(f"策划分派单 → {out}")


# ------------------------------------------------------------------ build
def clip_key(shot: dict, src: Path) -> str:
    h = hashlib.sha1(f"{src}:{shot['in']}:{shot['out']}:{shot.get('id')}"
                     .encode()).hexdigest()[:12]
    return h


def ensure_clips(pdir: Path, c: dict, shots: list[dict]) -> Path:
    """只重切"入出点变了"的镜头，其余复用缓存。"""
    check_or_die(schema.check_shot_ids, shots)  # id 即切片文件名：必须安全且唯一
    clips_dir = pdir / "work/clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = clips_dir / "manifest.json"
    manifest = media_io.read_manifest(manifest_path)  # 损坏只是缓存：提示后全部重切
    src = Path(c["material"])
    changed = 0
    for sh in shots:
        key = clip_key(sh, src)
        dst = clips_dir / f"{sh['id']}.mp4"
        if manifest.get(sh["id"]) == key and media_io.complete_or_adopt(dst):
            continue
        info(f"切镜头 {sh['id']}（{sh['out'] - sh['in']:.1f}s）")
        try:
            media_io.ffmpeg_to(dst, ["-ss", f"{sh['in']:.3f}", "-t", f"{sh['out'] - sh['in']:.3f}",
                                     "-i", str(src), "-vf", CLIP_VF,
                                     *encode.h264_args("clip"),
                                     "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"])
        except media_io.MediaError as exc:
            die(f"切镜头 {sh['id']} 失败：{exc}")
        manifest = {**manifest, sh["id"]: key}
        save_json(manifest_path, manifest)  # 每镜落盘：中断后已切好的不重切
        changed += 1
    info(f"切片：{changed} 个新切，{len(shots) - changed} 个复用")
    return clips_dir


def actual_durations(clips_dir: Path, shots: list[dict]) -> dict[str, float]:
    """以切片文件真实时长为准，避免"请求 10 秒、实际 8 秒"导致预览和草稿不一致。"""
    out = {}
    for sh in shots:
        d = media_io.duration_or_zero(clips_dir / f"{sh['id']}.mp4")
        out[sh["id"]] = round(d if d > 0 else sh["out"] - sh["in"], 3)
    return out


def compose_timeline(c: dict, preset: dict, shots: list[dict], clips_dir: Path,
                     durations: dict[str, float]) -> dict:
    import re
    max_chars = preset.get("subtitle", {}).get("max_chars", 14)

    def split_sub(text: str) -> list[str]:
        parts = re.split(r"(?<=[，。！？；])", text)
        cards, cur = [], ""
        for p in parts:
            if not p:
                continue
            if len(cur) + len(p) <= max_chars:
                cur += p
            else:
                if cur:
                    cards.append(cur)
                while len(p) > max_chars:
                    cards.append(p[:max_chars]); p = p[max_chars:]
                cur = p
        if cur:
            cards.append(cur)
        return cards or [text]

    tl = {"project": {"name": c["title"], "width": 1080, "height": 1920,
                      "fps": 30, "platform": c.get("platform", "douyin")},
          "video": [], "audio": [], "text": []}
    t = 0.0
    for sh in shots:
        dur = durations.get(sh["id"], round(sh["out"] - sh["in"], 3))
        tl["video"].append({"id": sh["id"], "source": str(clips_dir / f"{sh['id']}.mp4"),
                            "in": 0.0, "out": dur, "timeline_in": round(t, 3),
                            "role": "broll" if not sh.get("sub") else "speech",
                            "caption": sh.get("note", "")})
        if sh.get("sub"):
            cards = split_sub(sh["sub"])
            total = sum(len(x) for x in cards)
            ct = t
            for card in cards:
                cd = dur * len(card) / total
                tl["text"].append({"id": f"{sh['id']}_{len(tl['text'])}",
                                   "text": card, "start": round(ct, 3),
                                   "end": round(ct + cd, 3),
                                   "style": {"size": preset.get("subtitle", {}).get("size", 6.5),
                                             "color": [1, 1, 1], "bold": True, "align": 2}})
                ct += cd
        t += dur
    tl["text"] += build_documentary.card_entries(
        preset.get("cards", []), t,
        size=preset.get("card", {}).get("size", build_documentary.CARD_SIZE))
    return tl


def ensure_preview(vdir: Path, tl_hash: str) -> Path:
    """预览片：哈希一致且有完成标记才复用；渲染写临时文件，成功才改名（GL-15）。"""
    preview, stamp = vdir / "preview.mp4", vdir / ".timeline.sha"
    if stamp.exists() and stamp.read_text().strip() == tl_hash and media_io.complete_or_adopt(preview):
        info("预览片无变化，跳过渲染")
        return preview
    info("渲染预览片…")
    try:
        with media_io.atomic_output(preview) as tmp:
            _run_pipeline("pipeline.render_preview", [str(vdir / "timeline.json"), "-o", str(tmp)])
    except media_io.MediaError as exc:
        die(f"预览片渲染失败：{exc}")
    stamp.write_text(tl_hash)  # 必须在产物落盘之后
    return preview


def next_version(pdir: Path) -> str:
    vs = [int(p.name[1:]) for p in (pdir / "output").glob("v*")
          if p.is_dir() and p.name[1:].isdigit()]
    return f"v{max(vs) + 1 if vs else 1}"


def cmd_build(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    preset = load_preset(c["preset"])
    shots_file = pdir / "shots.json"
    if not shots_file.exists():  # 用覆盖式选段的结果直接出片
        selected = pdir / "work/shots-selected.json"
        if selected.exists():
            shots_file = selected
            info("使用覆盖式选段结果：work/shots-selected.json")
    if not shots_file.exists():
        die(f"缺少分镜表 {shots_file}（先跑 brief，再写 shots.json）")
    shots = schema.read_shots(shots_file)  # KI-48：损坏 / 缺键 / 入出点不对 → CorruptJSON，切片前由 main() 报
    if args.version:
        check_or_die(schema.check_version, args.version)
    try:  # GL-25：切片（耗时）之前确认分镜表覆盖全部必留段
        missing = select.missing_must_keep(pdir / "work", shots)
    except review.OverridesCorrupt as exc:
        die(str(exc))
    if missing:
        die(select.describe_missing(missing, from_selection=shots_file != pdir / "shots.json"))

    with applog.stage(pdir / "work", "clips"):
        clips_dir = ensure_clips(pdir, c, shots)
    version = args.version or next_version(pdir)
    vdir = pdir / "output" / version
    vdir.mkdir(parents=True, exist_ok=True)

    durations = actual_durations(clips_dir, shots)
    tl = compose_timeline(c, preset, shots, clips_dir, durations)
    save_json(vdir / "timeline.json", tl)
    tl_hash = hashlib.sha1(json.dumps(tl, ensure_ascii=False, sort_keys=True)
                           .encode()).hexdigest()
    total = sum(durations.values())
    ok(f"时间线：{len(shots)} 镜，{int(total // 60)}:{total % 60:05.2f}")
    with applog.stage(pdir / "work", "preview"):
        ok(f"预览片：{ensure_preview(vdir, tl_hash)}")
    if not args.no_draft:
        with applog.stage(pdir / "work", "draft"):
            install_draft(vdir, f"{c['title']}_{version}")
    ok(f"完成 → {vdir}")


def install_draft(vdir: Path, draft_name: str) -> None:
    """时间线 → 剪映草稿（安装前静态校验）。成功时把警告、草稿位置、注册表备份报出来。"""
    info("生成剪映草稿（安装前静态校验，FAIL 不交付）…")
    argv = [str(vdir / "timeline.json"), "--name", draft_name]
    if proc.FROZEN:
        code, out = proc.run_inprocess("pipeline.to_jianying", argv)
    else:
        r = subprocess.run(proc.dev_module_cmd(ensure_jy_python(), "pipeline.to_jianying", argv),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        code, out = r.returncode, (r.stdout or "") + (r.stderr or "")
    if code != 0:
        print("\n".join(out.strip().splitlines()[-DRAFT_LOG_LINES:]))
        die(DRAFT_NOT_INSTALLED)
    report = to_jianying.parse_report(out)
    for w in report["warnings"]:
        warn(w)
    ok(f"剪映草稿：{draft_name}（已通过静态校验）")
    if report["draft_path"]:
        info(f"草稿位置：{report['draft_path']}")
    if report["backup"]:
        info(f"注册表备份：{report['backup']}")


def cmd_prepare(args) -> None:
    """GUI 用：只做前期（不 build），完成后再由人挑镜头。缺告知 / 缺 Key 一开始就停（GL-02）。"""
    pdir = project_dir(args.name)
    require_consent()
    if missing := readiness.missing_keys(pdir / "work"):
        die(PREPARE_KEYS_MISSING.format(names=readiness.describe(missing)))
    if problem := encode.preflight():  # 付费步骤之前确认能出片
        die(problem)
    for step in readiness.PREPARE_STEPS:  # 每段计时进 work/timings.json（GL-19，诊断包会带上）
        with applog.stage(pdir / "work", step):
            globals()[f"cmd_{step}"](args)
    ok("前期处理完成，可以去挑镜头了")


def cmd_run(args) -> None:
    cmd_ingest(args); cmd_transcribe(args); cmd_junk(args); cmd_brief(args)
    pdir = project_dir(args.name)
    if (pdir / "shots.json").exists():
        cmd_build(args)
    else:
        info("还没有 shots.json —— 让 AI 按 work/brief.md 写一版，或手动写，然后跑 build")


def ask_target(default: int) -> int:
    """在终端里问成片时长；非交互环境（含 GUI）直接用预设值。"""
    if not sys.stdin.isatty():
        return default
    while True:
        raw = input(TARGET_PROMPT.format(default=default) + "\n  > ").strip()
        if not raw:
            return default
        try:
            return schema.check_target_duration(raw)
        except ValueError as exc:
            print(f"  {exc}")


def ask_calibration(existing: dict) -> dict:
    """在终端里问剪辑员三个问题（非交互环境直接返回原值）。"""
    cur = style.normalize(existing)
    if not sys.stdin.isatty():
        return cur
    print("\n先问三个问题，答案会写进提示词（回车沿用当前值）：")
    for key, question in style.QUESTIONS:
        default = cur.get(key, "")
        suffix = f" [{default}]" if default else ""
        raw = input(f"  {question}{suffix}\n  > ").strip()
        if raw:
            cur[key] = raw
    cur = style.normalize(cur)
    print(f"  已记录：{style.TONES[cur['tone']]}"
          + (f" · 观众 {cur['audience']}" if cur["audience"] else "")
          + (" · 含指定原话" if cur["must_lines"] else ""))
    return cur


def cmd_calibrate(args) -> None:
    """运行时校准剪辑偏好；不传参数则交互式问答。"""
    pdir = project_dir(args.name)
    c = cfg(pdir)
    current = c.get("calibration") or {}
    if args.show:
        cur = style.normalize(current)
        print(f"tone      : {cur['tone']}（{style.TONES[cur['tone']]}）")
        print(f"audience  : {cur['audience'] or '（未填）'}")
        print(f"must_lines: {cur['must_lines'] or '（未填）'}")
        print(f"提示词效果: {style.directive(cur) or '（无，使用默认）'}")
        return
    if args.reset:
        c["calibration"] = {}
        schema.save(pdir / "project.json", c)
        ok("已清除剪辑偏好")
        return
    updated = dict(current)
    for key in ("tone", "audience", "must_lines"):
        value = getattr(args, key, None)
        if value is not None:
            updated[key] = value
    if not any(getattr(args, k, None) is not None for k in ("tone", "audience", "must_lines")):
        updated = ask_calibration(current)
    c["calibration"] = style.normalize(updated)
    schema.save(pdir / "project.json", c)
    ok("剪辑偏好已保存：" + (style.directive(c["calibration"]) or "（空）"))


def cmd_config(args) -> None:
    """凭证管理：查看（掩码）/ 设置 / 删除。"""
    if not args.action:
        st = secrets.status()
        for name, item in st.items():
            mark = "✓" if item["configured"] else "·"
            src = f"（来源 {item['source']}）" if item["source"] else ""
            print(f"[{mark}] {name:9s} {item['masked'] or '未配置'} {src}")
        if not st["mediakit"]["configured"]:
            info("设置：uv run python aicut.py config set mediakit")
        return
    if args.action == "consent":
        print(consent.NOTICE_TITLE)
        print("\n".join(consent.NOTICE_LINES))
        consent.accept()
        ok("已记录：你已阅读数据外发说明")
        return
    provider = args.provider
    if args.action == "set":
        if sys.stdin.isatty():
            import getpass
            value = getpass.getpass(f"粘贴 {provider} 的 Key（输入不回显）：").strip()
        else:
            value = sys.stdin.readline().strip()
        if not value:
            die("Key 为空，已取消")
        backend = secrets.set(provider, value)
        ok(f"已保存到 {backend}：{secrets.mask(value)}")
    elif args.action == "unset":
        secrets.delete(provider)
        ok(f"已删除 {provider}")
    else:
        die(f"未知操作：{args.action}")


def cmd_status(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    checks = [
        ("素材台账", pdir / "work/materials.json"),
        ("音轨", pdir / "work/audio/asr.wav"),
        ("转写", pdir / "work/transcript_raw.json"),
        ("分段文稿", pdir / "work/transcript.md"),
        ("声音特征 (a)", pdir / "work/segments_audio.json"),
        ("文本标注 (b)", pdir / "work/segments_text.json"),
        ("分析代理", pdir / "work/proxy.mp4"),
        ("废片表", pdir / "work/junk_report.csv"),
        ("镜头切分 (c)", pdir / "work/shots_visual.json"),
        ("三档判定", pdir / "work/segments_scored.json"),
        ("内容摘要", pdir / "work/content_summary.json"),
        ("决策问题", pdir / "work/questions.json"),
        ("人工裁决", pdir / "work/overrides.json"),
        ("策划分派单", pdir / "work/brief.md"),
        ("分镜表", pdir / "shots.json"),
        ("选段时间线", pdir / "work/shots-selected.json"),
    ]
    print(f"\n项目：{c['title']}（{c['name']}）")
    print(f"预设：{c['preset']}　平台：{c['platform']}　目标：{c['target_duration']}s\n")
    text_incomplete = understand_text.is_incomplete(pdir / "work/segments_text.json")
    for label, p in checks:
        if p.name == "segments_text.json" and text_incomplete:
            print(f"  [!] {label}：{TEXT_INCOMPLETE_STATUS}")
            continue
        done = media_io.complete_or_adopt(p) if p.suffix in MEDIA_SUFFIXES else p.exists()
        print(f"  [{'✓' if done else '·'}] {label}")
    outs = sorted(p.name for p in (pdir / "output").glob("v*") if p.is_dir())
    print(f"\n已出片：{outs or '无'}")


def cmd_list(args) -> None:
    for p in sorted(PROJECTS.glob("*/project.json")):
        try:
            c = load_json(p)
        except schema.CorruptJSON:  # 一个项目坏了不影响列出其它项目
            c = {"name": p.parent.name, "title": LIST_CORRUPT}
        outs = sorted(x.name for x in (p.parent / "output").glob("v*"))
        print(f"{c['name']:28s} {c.get('title', ''):12s} {c.get('preset', ''):10s} {outs}")


# ------------------------------------------------------------------ 入口
def run_cli(argv: list[str]) -> int:
    """执行一条命令并返回退出码（供 GUI 在同一进程里调用）。"""
    try:
        main(argv)
        return 0
    except SystemExit as exc:
        return proc.exit_code(exc, sys.stdout)
    except Exception:  # noqa: BLE001
        import traceback
        LOG.exception("命令异常：%s", argv[:2])
        traceback.print_exc()
        return 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="aicut 视频剪辑流水线")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new"); p.add_argument("name")
    p.add_argument("--material", required=True); p.add_argument("--title")
    p.add_argument("--preset", default="纪实3min")
    p.add_argument("--tone", choices=list(style.TONES))
    p.add_argument("--audience", default=None)
    p.add_argument("--must-lines", dest="must_lines", default=None)
    p.add_argument("--target", default=None, help="成片目标时长（秒），默认用预设")
    p.add_argument("--no-input", dest="no_input", action="store_true",
                   help="不在终端提问（GUI 调用时使用）")
    p.set_defaults(fn=cmd_new)

    for name, fn in [("run", cmd_run), ("build", cmd_build)]:  # KI-16：run 有 shots.json 时直接调 cmd_build
        p = sub.add_parser(name); p.add_argument("name"); p.set_defaults(fn=fn)
        p.add_argument("--version"); p.add_argument("--no-draft", action="store_true")
    for name, fn in [("prepare", cmd_prepare),
                     ("ingest", cmd_ingest), ("analyze", cmd_analyze),
                     ("transcribe", cmd_transcribe), ("junk", cmd_junk),
                     ("brief", cmd_brief), ("status", cmd_status)]:
        p = sub.add_parser(name); p.add_argument("name"); p.set_defaults(fn=fn)

    p = sub.add_parser("text"); p.add_argument("name")
    p.add_argument("--batch", type=int, default=40)
    p.add_argument("--model", default="deepseek-chat")
    p.set_defaults(fn=cmd_text)

    p = sub.add_parser("quality"); p.add_argument("name")
    p.set_defaults(fn=cmd_quality)

    p = sub.add_parser("export"); p.add_argument("name")
    p.add_argument("--timeline", default=None)
    p.add_argument("--package-name", dest="package_name", default=None)
    p.add_argument("-o", "--out", default="dist")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("select"); p.add_argument("name")
    p.add_argument("--target", default=None, help="改目标时长（秒）后只重跑选段")
    p.set_defaults(fn=cmd_select)

    p = sub.add_parser("questions"); p.add_argument("name")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_questions)

    p = sub.add_parser("summary"); p.add_argument("name")
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("score"); p.add_argument("name")
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser("scenes"); p.add_argument("name")
    p.add_argument("--threshold", type=float, default=8.0)
    p.set_defaults(fn=cmd_scenes)

    p = sub.add_parser("calibrate"); p.add_argument("name")
    p.add_argument("--tone", choices=list(style.TONES))
    p.add_argument("--audience")
    p.add_argument("--must-lines", dest="must_lines")
    p.add_argument("--show", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("config"); p.set_defaults(fn=cmd_config)
    p.add_argument("action", nargs="?", choices=["set", "unset", "consent"])
    p.add_argument("provider", nargs="?", default="mediakit",
                   choices=list(secrets.PROVIDERS))

    p = sub.add_parser("list"); p.set_defaults(fn=cmd_list)

    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except (schema.CorruptJSON, review.OverridesCorrupt) as exc:  # KI-21 / KI-56：人话，不给 traceback
        die(str(exc))


if __name__ == "__main__":
    applog.setup("cli")
    proc.start_parent_watchdog()  # 由剪辑台起的任务：剪辑台没了就带着 ffmpeg 一起退出
    main()

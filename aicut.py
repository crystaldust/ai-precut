#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aicut —— 把视频剪辑流水线固化成一条命令。

设计目标：
  1. 一个入口：所有动作都是 `python3 aicut.py <命令>`
  2. 一份配置：每个项目一个 project.json，想改风格/平台/时长改这里
  3. 一层可调：shots.json（分镜表）是唯一需要手改的地方，改完只重出，不重跑 ASR
  4. 版本不覆盖：每次出片进 output/v1 v2 v3，剪映草稿名也带版本号

命令：
  new <项目名> --material <原片> [--title 片名] [--preset 纪实3min]
  run <项目名>                 全流程（已完成的自动跳过）
  ingest <项目名>              素材台账
  transcribe <项目名>          抽音轨 + 云端转写 + 分段文稿
  junk <项目名>                代理片 + 规则层废片检测
  brief <项目名>               生成"给 AI/给人看"的策划分派单
  build <项目名> [--version v2] [--no-draft]   分镜表 → 切片 → 预览 → 剪映草稿
  status <项目名>              看每个环节的状态
  list                         列出所有项目
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pipeline import (classify, cloud, questions, schema, secrets, summarize,
                      understand_audio, understand_text, understand_visual)

ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / "projects"
PRESETS = ROOT / "presets"
PIPELINE = ROOT / "pipeline"
DRAFT_ROOT = Path.home() / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
JY_VENV = Path.home() / ".aicut/venv"


# ------------------------------------------------------------------ 基础
def die(msg: str) -> None:
    print(f"[x] {msg}")
    sys.exit(1)


def info(msg: str) -> None:
    print(f"[·] {msg}")


def ok(msg: str) -> None:
    print(f"[✓] {msg}")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def load_json(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def project_dir(name: str) -> Path:
    p = PROJECTS / name
    if not (p / "project.json").exists():
        die(f"项目不存在：{name}（用 new 创建）")
    return p


def cfg(pdir: Path) -> dict:
    return schema.load(pdir / "project.json")


def probe_duration(path: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def ensure_jy_python() -> str:
    """剪映草稿生成依赖 pyJianYingDraft；用专用 venv，不污染系统 Python。"""
    py = JY_VENV / "bin/python"
    if py.exists():
        return str(py)
    info("首次使用：创建 ~/.aicut/venv 并安装 pyJianYingDraft（约 20 秒）…")
    JY_VENV.parent.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "venv", str(JY_VENV)], check=True)
    r = run([str(py), "-m", "pip", "install", "-q", "pyJianYingDraft"])
    if r.returncode != 0:
        die(f"安装 pyJianYingDraft 失败：{r.stderr[-300:]}")
    ok("依赖就绪")
    return str(py)


def mediakit_env() -> dict:
    env = secrets.env_with_secret()
    env["MEDIAKIT_SURFACE"] = "skill"
    env["MEDIAKIT_RUNTIME"] = "aicut"
    return env


# ------------------------------------------------------------------ 命令
def cmd_new(args) -> None:
    pdir = PROJECTS / args.name
    if (pdir / "project.json").exists():
        die(f"项目已存在：{pdir}")
    src = Path(args.material).expanduser().resolve()
    if not src.exists():
        die(f"原片不存在：{src}")
    preset = load_json(PRESETS / f"{args.preset}.json")
    if preset is None:
        die(f"找不到预设 {args.preset}，可用：{[p.stem for p in PRESETS.glob('*.json')]}")
    pdir.mkdir(parents=True)
    project = schema.default_project(
        args.name, str(src),
        title=args.title or args.name,
        preset=args.preset,
        platform=preset.get("platform", "douyin"),
        target_duration=preset.get("duration"),
        created=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    schema.save(pdir / "project.json", project)
    ok(f"项目已创建：{pdir}")
    info(f"下一步：python3 aicut.py run {args.name}")


def cmd_ingest(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    src = Path(c["material"])
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size,bit_rate",
             "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate",
             "-of", "json", str(src)])
    data = json.loads(r.stdout)
    entry = {"path": str(src), "name": src.name,
             "size": src.stat().st_size,
             "duration": float(data["format"].get("duration", 0)),
             "streams": data.get("streams", [])}
    save_json(pdir / "work/materials.json", {"items": [entry]})
    ok(f"素材台账：{entry['duration'] / 60:.1f} 分钟，{entry['size'] / 1e9:.1f} GB")


def cmd_transcribe(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    work = pdir / "work"
    wav = work / "audio/asr.wav"
    raw = work / "transcript_raw.json"
    if not wav.exists():
        wav.parent.mkdir(parents=True, exist_ok=True)
        info("抽音轨…")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", c["material"],
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
    if not raw.exists():
        if not secrets.get("mediakit"):
            die("未配置 MEDIAKIT_API_KEY：运行 `uv run python aicut.py config set mediakit`")
        info("提交云端转写（长素材要几分钟）…")
        client = cloud.CloudClient(env=mediakit_env())
        try:
            client.transcribe(wav, work, duration_s=probe_duration(wav))
        except cloud.CloudError as exc:
            die(f"转写失败：{exc}")
    info("整理分段文稿…")
    subprocess.run([sys.executable, str(PIPELINE / "format_transcript.py"),
                    str(raw), "-o", str(work)], check=True, capture_output=True)
    ok("转写完成 → work/transcript.md / work/segments.json")


def cmd_analyze(args) -> None:
    """a 路：给每句算响度/语速/停顿/抢话。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    wav, segs = work / "audio/asr.wav", work / "segments.json"
    if not wav.exists() or not segs.exists():
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
    if not secrets.get("deepseek"):
        die("未配置 DEEPSEEK_API_KEY：运行 `uv run python aicut.py config set deepseek`")
    info(f"调用 {args.model} 做话题分段与逐句标注（{args.batch} 句/批）…")
    res = understand_text.run(segs, work / "segments_text.json",
                              batch=args.batch, model=args.model)
    key = sum(1 for x in res["segments"] if x["key_info"])
    msg = f"话题 {len(res['topics'])} 个 · 关键信息 {key} 句"
    if res["failures"]:
        msg += f" · {len(res['failures'])} 批失败（详见 segments_text.json）"
    ok(msg)


def cmd_score(args) -> None:
    """合成三档：废片 / 待定 / 可用。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    text = work / "segments_text.json"
    if not text.exists():
        die("先跑 text（需要 work/segments_text.json）")
    c = cfg(pdir)
    res = classify.run(text, work / "segments_audio.json",
                       work / "segments_scored.json",
                       total_target=float(c.get("target_duration") or 175),
                       visual_path=work / "visual_quality.json")
    s = res["summary"]
    flagged = sum(1 for x in res["segments"] if x.get("visual_flags"))
    ok(f"废片 {s['waste']} · 待定 {s['pending']} · 可用 {s['usable']}"
       + (f" · 画面异常 {flagged}" if flagged else ""))


def cmd_junk(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    work = pdir / "work"
    proxy = work / "proxy.mp4"
    if not proxy.exists():
        info("生成 540p 分析代理…")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", c["material"],
             "-vf", "scale=-2:540,fps=30", "-c:v", "libx264", "-preset",
             "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "64k", str(proxy)],
            check=True)
    subprocess.run([sys.executable, str(PIPELINE / "junk_detect.py"),
                    str(proxy), "-o", str(work), "--scene"], check=True)
    ok("废片检测完成 → work/junk_report.csv")


def cmd_scenes(args) -> None:
    """c 路第一层：在代理片上切镜头。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    proxy = work / "proxy.mp4"
    if not proxy.exists():
        die("先跑 junk（需要 work/proxy.mp4）")
    info("分析镜头切点（在代理片上跑，长素材要 1–3 分钟）…")
    res = understand_visual.run(proxy, work / "shots_visual.json",
                                threshold=args.threshold)
    ok(f"镜头 {len(res['shots'])} 个（切点 {res['cut_count']}）")


def cmd_quality(args) -> None:
    """画面质量：亮度/运动/清晰度，按句聚合。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    proxy, segs = work / "proxy.mp4", work / "segments.json"
    if not proxy.exists() or not segs.exists():
        die("先跑 junk 与 transcribe（需要 proxy.mp4 与 segments.json）")
    info("抽帧分析画面质量（1 fps，长素材约 30–90 秒）…")
    res = understand_visual.run_quality(proxy, segs, work / "visual_quality.json")
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
    info("生成内容摘要…")
    res = summarize.run(text, scored, work / "content_summary.json")
    ok(("（兜底）" if res["fallback"] else "") + res["summary"])


def cmd_questions(args) -> None:
    """2.4 由内容生成 3–5 个决策问题。"""
    pdir = project_dir(args.name)
    work = pdir / "work"
    summary, scored = work / "content_summary.json", work / "segments_scored.json"
    if not summary.exists() or not scored.exists():
        die("先跑 score 与 summary")
    res = questions.run(summary, scored, work / "questions.json")
    tag = "（兜底）" if res["fallback"] else ""
    ok(f"决策问题 {len(res['questions'])} 个{tag}")
    for q in res["questions"]:
        info(f"  {q['text']} → " + " / ".join(o["label"] for o in q["options"]))


def cmd_brief(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    preset = load_json(PRESETS / f"{c['preset']}.json", {})
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
    clips_dir = pdir / "work/clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_json(pdir / "work/clips/manifest.json", {})
    src = Path(c["material"])
    changed = 0
    for sh in shots:
        key = clip_key(sh, src)
        dst = clips_dir / f"{sh['id']}.mp4"
        if manifest.get(sh["id"]) == key and dst.exists():
            continue
        info(f"切镜头 {sh['id']}（{sh['out'] - sh['in']:.1f}s）")
        run(["ffmpeg", "-y", "-loglevel", "error",
             "-ss", f"{sh['in']:.3f}", "-t", f"{sh['out'] - sh['in']:.3f}",
             "-i", str(src),
             "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             str(dst)], check=True)
        manifest[sh["id"]] = key
        changed += 1
    save_json(pdir / "work/clips/manifest.json", manifest)
    info(f"切片：{changed} 个新切，{len(shots) - changed} 个复用")
    return clips_dir


def actual_durations(clips_dir: Path, shots: list[dict]) -> dict[str, float]:
    """以切片文件真实时长为准，避免"请求 10 秒、实际 8 秒"导致预览和草稿不一致。"""
    out = {}
    for sh in shots:
        d = probe_duration(clips_dir / f"{sh['id']}.mp4")
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
    for card in preset.get("cards", []):
        tl["text"].append({"id": f"card_{card['at']}", "text": card["text"],
                           "start": card["at"],
                           "end": min(card["at"] + card["dur"], t),
                           "style": {"size": preset.get("card", {}).get("size", 6.8),
                                     "color": [1, 1, 1], "bold": True, "align": 5}})
    return tl


def next_version(pdir: Path) -> str:
    vs = [int(p.name[1:]) for p in (pdir / "output").glob("v*")
          if p.is_dir() and p.name[1:].isdigit()]
    return f"v{max(vs) + 1 if vs else 1}"


def cmd_build(args) -> None:
    pdir = project_dir(args.name)
    c = cfg(pdir)
    preset = load_json(PRESETS / f"{c['preset']}.json", {})
    shots_file = pdir / "shots.json"
    if not shots_file.exists():
        die(f"缺少分镜表 {shots_file}（先跑 brief，再写 shots.json）")
    spec = load_json(shots_file)
    shots = spec["shots"]

    clips_dir = ensure_clips(pdir, c, shots)
    version = args.version or next_version(pdir)
    vdir = pdir / "output" / version
    vdir.mkdir(parents=True, exist_ok=True)

    durations = actual_durations(clips_dir, shots)
    tl = compose_timeline(c, preset, shots, clips_dir, durations)
    save_json(vdir / "timeline.json", tl)
    tl_hash = hashlib.sha1(json.dumps(tl, ensure_ascii=False, sort_keys=True)
                           .encode()).hexdigest()
    stamp = vdir / ".timeline.sha"
    same = stamp.exists() and stamp.read_text().strip() == tl_hash
    total = sum(durations.values())
    ok(f"时间线：{len(shots)} 镜，{int(total // 60)}:{total % 60:05.2f}")

    if same and (vdir / "preview.mp4").exists():
        info("预览片无变化，跳过渲染")
    else:
        info("渲染预览片…")
        subprocess.run([sys.executable, str(PIPELINE / "render_preview.py"),
                        str(vdir / "timeline.json"), "-o", str(vdir / "preview.mp4")],
                       check=True, capture_output=True)
        stamp.write_text(tl_hash)
    ok(f"预览片：{vdir / 'preview.mp4'}")

    if not args.no_draft:
        info("生成剪映草稿…")
        draft_name = f"{c['title']}_{version}"
        r = subprocess.run([ensure_jy_python(), str(PIPELINE / "to_jianying.py"),
                            str(vdir / "timeline.json"), "--name", draft_name],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout[-500:], r.stderr[-500:])
            die("草稿生成失败")
        ok(f"剪映草稿：{draft_name}")
        v = subprocess.run([sys.executable, str(ROOT / "research/validate_draft.py"),
                            str(DRAFT_ROOT / draft_name)], capture_output=True, text=True)
        tail = [l for l in v.stdout.splitlines() if "结果：" in l]
        ok(f"校验：{tail[0].strip() if tail else '见输出'}")
    ok(f"完成 → {vdir}")


def cmd_prepare(args) -> None:
    """GUI 用：只做前期（不 build），完成后再由人挑镜头。"""
    cmd_ingest(args); cmd_transcribe(args); cmd_analyze(args)
    if secrets.get("deepseek"):
        cmd_text(args)
    else:
        info("跳过 b 路：未配置 DEEPSEEK_API_KEY")
    cmd_junk(args); cmd_scenes(args); cmd_quality(args)
    cmd_score(args); cmd_summary(args); cmd_questions(args); cmd_brief(args)
    ok("前期处理完成，可以去挑镜头了")


def cmd_run(args) -> None:
    cmd_ingest(args); cmd_transcribe(args); cmd_junk(args); cmd_brief(args)
    pdir = project_dir(args.name)
    if (pdir / "shots.json").exists():
        cmd_build(args)
    else:
        info("还没有 shots.json —— 让 AI 按 work/brief.md 写一版，或手动写，然后跑 build")


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
        ("策划分派单", pdir / "work/brief.md"),
        ("分镜表", pdir / "shots.json"),
    ]
    print(f"\n项目：{c['title']}（{c['name']}）")
    print(f"预设：{c['preset']}　平台：{c['platform']}　目标：{c['target_duration']}s\n")
    for label, p in checks:
        mark = "✓" if p.exists() else "·"
        print(f"  [{mark}] {label}")
    outs = sorted(p.name for p in (pdir / "output").glob("v*") if p.is_dir())
    print(f"\n已出片：{outs or '无'}")


def cmd_list(args) -> None:
    for p in sorted(PROJECTS.glob("*/project.json")):
        c = load_json(p)
        outs = sorted(x.name for x in (p.parent / "output").glob("v*"))
        print(f"{c['name']:28s} {c.get('title', ''):12s} {c.get('preset', ''):10s} {outs}")


# ------------------------------------------------------------------ 入口
def main() -> None:
    ap = argparse.ArgumentParser(description="aicut 视频剪辑流水线")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new"); p.add_argument("name")
    p.add_argument("--material", required=True); p.add_argument("--title")
    p.add_argument("--preset", default="纪实3min"); p.set_defaults(fn=cmd_new)

    for name, fn in [("run", cmd_run), ("prepare", cmd_prepare),
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

    p = sub.add_parser("questions"); p.add_argument("name")
    p.set_defaults(fn=cmd_questions)

    p = sub.add_parser("summary"); p.add_argument("name")
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("score"); p.add_argument("name")
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser("scenes"); p.add_argument("name")
    p.add_argument("--threshold", type=float, default=8.0)
    p.set_defaults(fn=cmd_scenes)

    p = sub.add_parser("build"); p.add_argument("name")
    p.add_argument("--version"); p.add_argument("--no-draft", action="store_true")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("config"); p.set_defaults(fn=cmd_config)
    p.add_argument("action", nargs="?", choices=["set", "unset"])
    p.add_argument("provider", nargs="?", default="mediakit",
                   choices=list(secrets.PROVIDERS))

    p = sub.add_parser("list"); p.set_defaults(fn=cmd_list)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()

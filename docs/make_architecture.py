#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成架构图（SVG）与说明页（HTML）。

用法：
    python3 docs/make_architecture.py
产物：
    docs/架构图.html   ← 浏览器打开
    docs/架构图.svg    ← 可插入文档/PPT
图上每一个"云端调用"都对应代码里的真实调用点，改代码后请同步改这里的 STEPS/CLOUD。
"""
from __future__ import annotations

from pathlib import Path

W, H = 1520, 1000
FONT = "PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif"

COL = {
    "local":   ("#eaf2ff", "#7aa7e0", "#16324f"),
    "cloud":   ("#fff3e2", "#e8a33d", "#7a4a12"),
    "gray":    ("#eef0f3", "#b9c0cb", "#3b424e"),
    "green":   ("#e9f8ef", "#4caf7d", "#1f5137"),
    "zone_l":  ("#fbfcff", "#d7dfee", "#4a5a7a"),
    "zone_c":  ("#fffaf3", "#ead6b8", "#8a6a3a"),
}

# 管线步骤：(序号, 标题, 副标题, 类型)
STEPS = [
    ("①", "素材入库", "ffprobe · 生成 materials.json", "local"),
    ("②", "抽音轨", "ffmpeg · 16k 单声道 wav（素材不上传）", "local"),
    ("③", "转写文稿", "云端返回 · transcript / segments", "local"),
    ("④", "废片检测", "ffmpeg 滤镜 + 规则 · junk_report.csv", "local"),
    ("⑤", "分镜编排", "人 / AI 写 shots.json · 脚本校验", "local"),
    ("⑥", "切片", "ffmpeg 按入出点切 · clips/（带缓存）", "local"),
    ("⑦", "预览渲染", "ffmpeg 拼接 + 字幕 · preview.mp4", "local"),
    ("⑧", "剪映草稿", "pyJianYingDraft · 写入草稿库", "local"),
]

CLOUD_ACTIVE = ("ASR 语音转字幕", "上传 16k 单声道 wav · 返回带时间戳字幕 JSON")
CLOUD_OPTIONAL = [
    "语义切片 semantic-segment（改用本地句群切分）",
    "视频理解 video-understand --scene editing",
    "OCR video-ocr / 高光拆条 / 画质增强",
]


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def box(x, y, w, h, title, sub="", kind="local", dashed=False, rx=10):
    fill, stroke, fg = COL[kind]
    da = ' stroke-dasharray="6 5"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
           f'fill="{fill}" stroke="{stroke}" stroke-width="1.6"{da}/>']
    out.append(f'<text x="{x+16}" y="{y+24}" font-size="15" font-weight="600" '
               f'fill="{fg}" font-family="{FONT}">{esc(title)}</text>')
    if sub:
        out.append(f'<text x="{x+16}" y="{y+44}" font-size="12" fill="#5b6b82" '
                   f'font-family="{FONT}">{esc(sub)}</text>')
    return "\n".join(out)


def zone(x, y, w, h, label, kind="zone_l"):
    fill, stroke, fg = COL[kind]
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.2" stroke-dasharray="8 6"/>\n'
            f'<text x="{x+20}" y="{y+24}" font-size="13" font-weight="600" fill="{fg}" '
            f'font-family="{FONT}">{esc(label)}</text>')


def arrow(x1, y1, x2, y2, color="#3b6ea5", dashed=False, label="", lx=None, ly=None):
    da = ' stroke-dasharray="5 4"' if dashed else ""
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
           f'stroke-width="1.8"{da} marker-end="url(#arw)"/>']
    if label:
        out.append(f'<text x="{lx if lx is not None else (x1+x2)/2}" '
                   f'y="{ly if ly is not None else (y1+y2)/2 - 6}" font-size="11" '
                   f'fill="#6b7c93" text-anchor="middle" font-family="{FONT}">{esc(label)}</text>')
    return "\n".join(out)


def path_arrow(pts, color="#3b6ea5", dashed=False, label="", lx=0, ly=0):
    da = ' stroke-dasharray="5 4"' if dashed else ""
    d = "M " + " L ".join(f"{x},{y}" for x, y in pts)
    out = [f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8"{da} '
           f'marker-end="url(#arw)"/>']
    if label:
        out.append(f'<text x="{lx}" y="{ly}" font-size="11" fill="#6b7c93" '
                   f'text-anchor="middle" font-family="{FONT}">{esc(label)}</text>')
    return "\n".join(out)


def build_svg() -> str:
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">',
         '<defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
         'markerHeight="7" orient="auto-start-reverse">'
         '<path d="M 0 0 L 10 5 L 0 10 z" fill="#3b6ea5"/></marker></defs>',
         f'<rect width="{W}" height="{H}" fill="#ffffff"/>']

    p.append(f'<text x="40" y="46" font-size="25" font-weight="700" fill="#12243a" '
             f'font-family="{FONT}">AI 粗剪工具 · 模块与调用关系</text>')
    p.append(f'<text x="40" y="74" font-size="13" fill="#6b7c93" font-family="{FONT}">'
             f'蓝＝本地执行　橙＝云端调用　灰＝第三方软件　绿＝产物；图上每个云端框都对应代码里真实的一条调用</text>')

    # ---------- 区域一：界面 ----------
    p.append(zone(24, 96, 1472, 96, "① 界面层（本地）"))
    p.append(box(56, 130, 110, 52, "剪辑师", "选片 / 改表 / 出片", "gray"))
    p.append(box(196, 130, 260, 52, "剪辑台界面", "pywebview 窗口 · HTML/JS", "local"))
    p.append(box(486, 130, 260, 52, "本地服务", "gui/server.py · 127.0.0.1", "local"))
    p.append(arrow(166, 156, 194, 156))
    p.append(arrow(456, 156, 484, 156))
    p.append(f'<text x="790" y="152" font-size="12" fill="#4c8a6a" font-family="{FONT}">'
             f'素材永远不进浏览器：界面只拿到文件路径</text>')
    p.append(f'<text x="790" y="172" font-size="12" fill="#6b7c93" font-family="{FONT}">'
             f'本机 HTTP，不监听外网，不经过任何服务器</text>')
    p.append(path_arrow([(516, 182), (516, 206), (330, 206), (330, 266)],
                        label="调用 aicut.py", lx=430, ly=196))

    # ---------- 区域二：本地管线 ----------
    p.append(zone(24, 220, 1472, 570, "② 本地处理管线（aicut.py 编排，全部在本机执行）"))
    ys = [264, 328, 392, 456, 520, 584, 648, 712]
    for (num, title, sub, kind), y in zip(STEPS, ys):
        p.append(box(60, y, 380, 56, f"{num} {title}", sub, kind))
    for i in range(7):
        p.append(arrow(250, ys[i] + 56, 250, ys[i + 1] - 2))

    # ---------- 区域三：云端 ----------
    p.append(zone(1020, 220, 476, 570, "③ 云端 AI（火山引擎 MediaKit · 按量计费）", "zone_c"))
    p.append(box(1050, 316, 416, 80,
                 CLOUD_ACTIVE[0] + "（当前唯一启用的云端调用）", CLOUD_ACTIVE[1], "cloud"))
    p.append(arrow(440, 356, 1046, 356, color="#e08a2e", label="上传音轨（不含画面）", lx=760, ly=348))
    p.append(path_arrow([(1250, 396), (1250, 420), (442, 420)], color="#e08a2e",
                        label="返回字幕 JSON（几 KB）", lx=900, ly=414))

    p.append(box(1050, 452, 416, 150, "可选云端能力（已接入命令行，当前未启用）", "", "cloud", dashed=True))
    for i, line in enumerate(CLOUD_OPTIONAL):
        p.append(f'<text x="1066" y="{490 + i*22}" font-size="12" fill="#7a4a12" '
                 f'font-family="{FONT}">{esc("· " + line)}</text>')
    p.append(arrow(440, 484, 1046, 484, color="#e08a2e", dashed=True, label="按需启用", lx=760, ly=476))
    p.append(f'<text x="1050" y="632" font-size="11" fill="#8a6a3a" font-family="{FONT}">'
             f'原则：只有"必须靠大模型"的事才上云；能本地算的（切、拼、检）一律不上传</text>')
    p.append(box(1050, 650, 416, 96, "大模型（LLM）· 未接入",
                 "用于把一句话想法写成分镜脚本", "cloud", dashed=True))
    p.append(f'<text x="1066" y="716" font-size="11" fill="#8a6a3a" font-family="{FONT}">'
             f'当前由 AI 助手在会话中完成，产出仍是本地文件 shots.json</text>')

    # ---------- 区域四：交付 ----------
    p.append(zone(24, 806, 1472, 104, "④ 交付物"))
    p.append(box(60, 832, 220, 56, "剪映专业版", "调色 / 音效 / 转场 / 字幕样式", "gray"))
    p.append(box(320, 832, 160, 56, "成片", "导出发布", "green"))
    p.append(arrow(250, 768, 250, 830, label="写入本机草稿库", lx=346, ly=796))
    p.append(arrow(280, 860, 318, 860))
    p.append(f'<text x="520" y="854" font-size="12" fill="#3b556e" font-family="{FONT}">'
             f'中间产物：materials.json · asr.wav · transcript.json · segments.json</text>')
    p.append(f'<text x="520" y="874" font-size="12" fill="#3b556e" font-family="{FONT}">'
             f'　　　　　junk_report.csv · shots.json · clips/ · preview.mp4 · 剪映草稿</text>')

    # ---------- 图例 ----------
    lx, ly = 40, 962
    legend = [("local", "本地执行（ffmpeg / Python）"), ("cloud", "云端调用（MediaKit）"),
              ("gray", "第三方软件"), ("green", "产物文件")]
    x = lx
    for kind, text in legend:
        fill, stroke, _ = COL[kind]
        p.append(f'<rect x="{x}" y="{ly-12}" width="16" height="12" rx="3" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="1.4"/>')
        p.append(f'<text x="{x+24}" y="{ly-1}" font-size="12" fill="#5b6b82" '
                 f'font-family="{FONT}">{esc(text)}</text>')
        x += 26 + len(text) * 12 + 20
    p.append(f'<text x="{W-40}" y="{ly-1}" text-anchor="end" font-size="11" fill="#8a97a8" '
             f'font-family="{FONT}">虚线 = 可选 / 未启用　｜　素材原片全程不出本机</text>')

    p.append("</svg>")
    return "\n".join(p)


HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>AI 粗剪工具 · 架构图</title>
<style>
body{{margin:0;padding:28px;background:#fff;font-family:{font};color:#12243a}}
h1{{font-size:22px;margin:0 0 6px}} .sub{{color:#6b7c93;font-size:13px;margin-bottom:18px}}
h2{{font-size:16px;margin:34px 0 10px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th{{text-align:left;background:#f5f7fb;color:#4a5a7a;font-weight:600;padding:9px 10px;border-bottom:1px solid #e2e8f2}}
td{{padding:8px 10px;border-bottom:1px solid #eef1f6;vertical-align:top}}
code{{background:#f4f6fa;padding:1px 5px;border-radius:4px;font-size:12px}}
.tag{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px}}
.l{{background:#eaf2ff;color:#245a96}} .c{{background:#fff3e2;color:#8a5a17}}
.g{{background:#eef0f3;color:#3b424e}} .o{{background:#e9f8ef;color:#1f5137}}
</style></head><body>
{svg}
<h2>模块清单</h2>
<table>
<tr><th style="width:190px">模块</th><th style="width:250px">代码位置</th><th style="width:100px">运行位置</th><th>依赖 / 说明</th></tr>
<tr><td>剪辑台界面</td><td><code>gui/static/index.html</code></td><td><span class="tag l">本地</span></td><td>单文件 HTML/JS，pywebview 承载；只发 JSON，不传素材</td></tr>
<tr><td>本地服务</td><td><code>gui/server.py</code></td><td><span class="tag l">本地</span></td><td>127.0.0.1 HTTP；文件选择、任务调度、视频 Range 直读</td></tr>
<tr><td>流程编排</td><td><code>aicut.py</code></td><td><span class="tag l">本地</span></td><td>new / prepare / build / status；缓存与版本号</td></tr>
<tr><td>素材台账</td><td><code>pipeline/</code> + ffprobe</td><td><span class="tag l">本地</span></td><td>只读元信息，不转码</td></tr>
<tr><td>转写整理</td><td><code>pipeline/format_transcript.py</code></td><td><span class="tag l">本地</span></td><td>把 ASR 结果切成段、加时间码</td></tr>
<tr><td>废片检测</td><td><code>pipeline/junk_detect.py</code></td><td><span class="tag l">本地</span></td><td>ffmpeg 滤镜 blackdetect / freezedetect / silencedetect / scdet</td></tr>
<tr><td>切片</td><td><code>aicut.py::ensure_clips</code></td><td><span class="tag l">本地</span></td><td>ffmpeg 按入出点切，做缓存（只重切变了的镜头）</td></tr>
<tr><td>预览渲染</td><td><code>pipeline/render_preview.py</code></td><td><span class="tag l">本地</span></td><td>ffmpeg concat + drawtext，1080×1920/30fps</td></tr>
<tr><td>剪映草稿</td><td><code>pipeline/to_jianying.py</code></td><td><span class="tag l">本地</span></td><td>pyJianYingDraft 生成 → 适配 Mac/Win → 注册进草稿库</td></tr>
<tr><td>草稿校验</td><td><code>research/validate_draft.py</code></td><td><span class="tag l">本地</span></td><td>纯标准库；FAIL 不交付</td></tr>
<tr><td>语音转字幕</td><td><code>mediakit-cli video asr-subtitles</code></td><td><span class="tag c">云端</span></td><td>火山引擎 MediaKit；上传 16k 单声道音轨，返回时间戳字幕</td></tr>
<tr><td>语义切片 / 视频理解 / OCR / 高光</td><td><code>mediakit-cli …</code></td><td><span class="tag c">云端（可选）</span></td><td>已接入命令行但当前未启用；现阶段用本地规则 + 人判断替代</td></tr>
<tr><td>分镜编排的判断</td><td>—</td><td><span class="tag l">本地</span></td><td>当前由人 / AI 在会话里完成，写入 <code>shots.json</code>；未接 LLM API</td></tr>
<tr><td>剪映专业版</td><td>第三方应用</td><td><span class="tag g">本地</span></td><td>人工精修与导出</td></tr>
<tr><td>成片</td><td>—</td><td><span class="tag o">产物</span></td><td>preview.mp4 / 剪映导出</td></tr>
</table>

<h2>本地 vs 云端：边界在哪</h2>
<table>
<tr><th style="width:160px">数据</th><th style="width:110px">在哪</th><th>说明</th></tr>
<tr><td>素材原片（GB 级）</td><td><span class="tag l">本机</span></td><td>永不整段上传；ffmpeg 直接读磁盘</td></tr>
<tr><td>抽出的音轨（16k wav）</td><td><span class="tag c">上传云端</span></td><td>仅 ASR 使用，约 100 MB/小时，任务结束即弃</td></tr>
<tr><td>字幕 JSON</td><td><span class="tag c">云端返回</span></td><td>几 KB</td></tr>
<tr><td>视频画面</td><td><span class="tag l">本机</span></td><td>当前不送云端；若启用"视频理解"，才会上传抽帧或视频</td></tr>
<tr><td>剪映草稿</td><td><span class="tag l">本机</span></td><td>写入 <code>~/Movies/JianyingPro/…</code>（Mac）或 <code>%LOCALAPPDATA%\\JianyingPro\\…</code>（Win）</td></tr>
</table>
</body></html>
"""


def main() -> None:
    svg = build_svg()
    out = Path(__file__).with_name("架构图")
    out.with_suffix(".svg").write_text(svg, encoding="utf-8")
    out.with_suffix(".html").write_text(HTML.format(svg=svg, font=FONT), encoding="utf-8")
    print(f"已生成：{out.with_suffix('.svg')}")
    print(f"已生成：{out.with_suffix('.html')}")


if __name__ == "__main__":
    main()

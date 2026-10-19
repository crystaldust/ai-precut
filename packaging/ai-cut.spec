# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置：把剪辑台打成 AI粗剪.app。

构建：uv run pyinstaller packaging/ai-cut.spec --noconfirm
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent
BIN = ROOT / "vendor" / "bin"

hidden = [
    "aicut",
    "gui.jobs", "gui.settings",
    "pipeline.asr_state", "pipeline.consent", "pipeline.readiness",
    "pipeline.build_documentary", "pipeline.classify", "pipeline.cloud",
    "pipeline.export_draft", "pipeline.format_transcript", "pipeline.junk_detect",
    "pipeline.llm", "pipeline.media_io",
    "pipeline.proc", "pipeline.questions", "pipeline.render_preview",
    "pipeline.review", "pipeline.schema", "pipeline.secrets", "pipeline.select",
    "pipeline.style", "pipeline.summarize", "pipeline.to_jianying",
    "pipeline.understand_audio", "pipeline.understand_text",
    "pipeline.understand_visual", "research.validate_draft",
    "webview.platforms.cocoa",
]

datas = collect_data_files("pyJianYingDraft")  # 草稿模板 JSON 在包内，必须一起带
datas += [
    (str(ROOT / "gui" / "static"), "gui/static"),
    (str(ROOT / "presets"), "presets"),
    (str(ROOT / "research" / "base_template_11.0.json"), "research"),
    (str(ROOT / "research" / "validate_draft.py"), "research"),
]

binaries = []
for name in ("ffmpeg", "ffprobe"):
    p = BIN / name
    if p.exists():
        binaries.append((str(p), "bin"))
    else:
        print(f"[warn] 缺少 {p}，打包后可能无法处理素材")

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ai-cut",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=os.environ.get("CODESIGN_IDENTITY") or None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ai-cut")

app = BUNDLE(
    coll,
    name="AI粗剪.app",
    icon=None,
    bundle_identifier="com.aicut.desktop",
    info_plist={
        "CFBundleName": "AI粗剪",
        "CFBundleDisplayName": "AI 粗剪",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "个人使用",
        "LSArchitecturePriority": ["arm64"],
    },
)

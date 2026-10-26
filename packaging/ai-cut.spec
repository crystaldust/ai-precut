# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置：把剪辑台打成 AI粗剪.app。

构建：uv run pyinstaller packaging/ai-cut.spec --noconfirm
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

IS_WIN = sys.platform == "win32"
EXE_SUFFIX = ".exe" if IS_WIN else ""
ROOT = Path(SPECPATH).resolve().parent
BIN = ROOT / "vendor" / "bin"

# KI-37：版本号按文件路径加载（packaging/ 与 PyPI 的 packaging 包同名，不能 import packaging.version）
_spec = importlib.util.spec_from_file_location("aicut_version", ROOT / "packaging" / "version.py")
_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_version)
SHORT_VERSION = _version.short_version(ROOT)
BUILD_NUMBER = _version.build_number(ROOT)  # 拿不到就构建失败，不静默打成 1
BUILD_INFO = _version.build_info(ROOT)

hidden = [
    "aicut",
    "gui.analysis", "gui.browse_batch", "gui.confirm", "gui.jianying", "gui.jobs", "gui.maintenance",
    "gui.media", "gui.opener", "gui.payloads", "gui.prefs", "gui.project_routes", "gui.result_payload", "gui.result_routes",
    "gui.server", "gui.session", "gui.settings",
    "gui.static_files", "gui.support", "gui.views", "gui.wizard",
    "pipeline.applog", "pipeline.asr_state", "pipeline.brief", "pipeline.build_documentary",
    "pipeline.cache", "pipeline.classify", "pipeline.cli_args", "pipeline.clips",
    "pipeline.cloud", "pipeline.config_cli", "pipeline.consent", "pipeline.diagnostics",
    "pipeline.diskspace", "pipeline.encode", "pipeline.exclusions", "pipeline.export_draft", "pipeline.export_flow", "pipeline.filelock",
    "pipeline.fingerprints", "pipeline.format_transcript",
    "pipeline.junk_detect", "pipeline.jy_env", "pipeline.jy_version", "pipeline.llm",
    "pipeline.media_io", "pipeline.notices", "pipeline.outputs", "pipeline.plat", "pipeline.proc", "pipeline.proctree", "pipeline.project_cli",
    "pipeline.project_lock", "pipeline.prompts", "pipeline.pyver", "pipeline.questions",
    "pipeline.readiness", "pipeline.render_preview", "pipeline.review", "pipeline.safe_http",
    "pipeline.schema", "pipeline.secrets", "pipeline.select", "pipeline.select_rules",
    "pipeline.shot_diff", "pipeline.shot_sub", "pipeline.shots_store", "pipeline.style", "pipeline.summarize", "pipeline.timeline", "pipeline.topic_names",
    "pipeline.to_jianying", "pipeline.transcript_stamp", "pipeline.understand_audio", "pipeline.understand_text",
    "pipeline.understand_visual", "pipeline.usage",
    "research.validate_draft",
]
if IS_WIN:
    hidden += ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr_loader", "pythonnet"]
else:
    hidden += ["webview.platforms.cocoa"]

# KI-52：静态文件只带白名单（gui/static_files.py 零依赖，按文件路径读，不 import gui）
_static = {}
exec((ROOT / "gui" / "static_files.py").read_text(encoding="utf-8"), _static)
STATIC_FILES = sorted(_static["STATIC_FILES"])

datas = collect_data_files("pyJianYingDraft")  # 草稿模板 JSON 在包内，必须一起带
datas += [(str(ROOT / "gui" / "static" / name), "gui/static") for name in STATIC_FILES]
datas += [
    (str(ROOT / "presets"), "presets"),
    (str(ROOT / "research" / "base_template_11.0.json"), "research"),
    (str(ROOT / "research" / "validate_draft.py"), "research"),
    (str(ROOT / "packaging" / "THIRD-PARTY-NOTICES.txt"), "licenses"),  # GL-04：「关于」页也读它
]
# 两个平台都带 build_info.json（pipeline.diagnostics 读 version）；写到 build/（已 gitignore，--clean 在 spec 执行前清）
_info_path = ROOT / "build" / "build_info.json"
_info_path.parent.mkdir(parents=True, exist_ok=True)
_info_path.write_text(json.dumps(BUILD_INFO, ensure_ascii=False, indent=2), encoding="utf-8")
datas.append((str(_info_path), "."))
LICENSES = ROOT / "vendor" / "licenses"  # build_ffmpeg.sh 产物：LGPL / FTL 全文 + configure 行
if LICENSES.exists():
    datas.append((str(LICENSES), "licenses"))
else:
    print(f"[warn] 缺少 {LICENSES}，许可全文不会随包")

binaries = []
for name in ("ffmpeg", "ffprobe"):
    p = BIN / (name + EXE_SUFFIX)
    if p.exists():
        binaries.append((str(p), "bin"))
    else:
        print(f"[warn] 缺少 {p}，打包后可能无法处理素材")

EXCLUDES = ["tkinter", "matplotlib", "numpy", "pandas", "pytest", "PyInstaller"]
if IS_WIN:
    EXCLUDES += ["webview.platforms.cocoa", "webview.platforms.gtk", "webview.platforms.qt",
                 "PyQt5", "PyQt6", "PySide2", "PySide6"]

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

# Windows：Python UTF-8 模式（运行期选项，等价于 python -X utf8；用 PYTHONUTF8 环境变量无法随包带）
RUNTIME_OPTIONS = [("X utf8", None, "OPTION")] if IS_WIN else []

exe = EXE(
    pyz, a.scripts, RUNTIME_OPTIONS,
    exclude_binaries=True,
    name="ai-cut",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None if IS_WIN else (os.environ.get("CODESIGN_IDENTITY") or None),
    # Windows：未捕获异常不弹模态对话框（任务子进程会一直挂着），直接退出，原因看 cli-*.log
    disable_windowed_traceback=IS_WIN,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ai-cut")

if not IS_WIN:
    app = BUNDLE(
        coll,
        name="AI粗剪.app",
        icon=None,
        bundle_identifier="com.aicut.desktop",
        info_plist={
            "CFBundleName": "AI粗剪",
            "CFBundleDisplayName": "AI 粗剪",
            "CFBundleShortVersionString": SHORT_VERSION,
            "CFBundleVersion": BUILD_NUMBER,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "个人使用",
            "LSArchitecturePriority": ["arm64"],
        },
    )

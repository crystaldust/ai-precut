"""端到端（KI-39）：一段真实编码的测试素材 → 处理素材 → 出片 → 剪映草稿 / Windows 导出包。

只在网络边界打桩：MediaKit 走假 transport/uploader，DeepSeek 换成按 prompt 应答的假客户端
（仍经 aicut.metered 计量、查预算）。外发告知、编码预检（真跑 VideoToolbox）、磁盘余量检查、
ffmpeg 抽音轨 / 代理 / 切片 / 预览、三路分析、分档、选段、必留校验、时间线、草稿生成、
静态校验、注册全部真跑。草稿根、HOME、项目目录、凭证、日志全部在 tmp_path 下。
"""
import functools
import json
import re
import shutil
import subprocess
import zipfile

import pytest

import aicut
from pipeline import cloud, encode, export_draft, media_io, proc, review, secrets, understand_text, usage
from pipeline import to_jianying as tj
from pipeline.llm import LLMError
from research import validate_draft

NAME = "e2e"
MUST_SID, MUST_TEXT = "S002", "九千八"   # 剪辑师标★的那句：必须出现在交付的草稿里
# 同一说话人、句间停顿 1.4s > 1.2s（format_transcript.GAP_SAME_SPEAKER）→ 切成 3 段 S001–S003
SUBS = [("大家好，今天来看合同。", 0.2, 1.6), ("学费一共九千八。", 3.0, 4.4),
        ("可以分两期缴费。", 5.8, 7.6)]
MATERIAL_SECONDS = 8
FAKE_USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}


def _has_videotoolbox() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                         text=True).stdout
    return f" {encode.ENCODER} " in out


pytestmark = pytest.mark.skipif(not _has_videotoolbox(),
                                reason="需要带 h264_videotoolbox 的 ffmpeg（产品只用 VideoToolbox 编码）")


class FakeLLM:
    model = "fake-e2e"

    def __init__(self):
        self.calls = 0
        self.answered = 0   # 成功应答的次数（失败的调用没有用量，不记账）
        self.last_usage = {}

    def chat_json(self, system, user, **kw):
        self.calls += 1
        ids = re.findall(r"^(S\d{3}) ", user, flags=re.M)
        if "归并成" in user:                       # understand_text.TOPIC_USER
            return self._answer({"topics": [{"name": "讲解合同", "segment_ids": ids}]})
        if user.startswith("给下面每句话标注"):    # understand_text.ANNOTATE_USER
            return self._answer({"segments": [{"id": i, "info_type": "金额价格", "key_info": True,
                                               "entities": [MUST_TEXT], "reason": "含金额"}
                                              for i in ids]})
        raise LLMError("e2e：摘要 / 决策问题走兜底")   # summarize / questions 任何模型错误都兜底


    def _answer(self, data):
        self.answered += 1
        self.last_usage = dict(FAKE_USAGE)
        return data


class FakeMediaKit:
    """上传 → 提交 → 轮询一次即完成；记录调用以证明没有真实请求。"""

    def __init__(self):
        self.paths = []

    def transport(self, method, url, headers, body, timeout):
        path = url[len(cloud.DEFAULT_ENDPOINT):]
        self.paths.append((method, path))
        if path == cloud.UPLOAD_PATH:
            return 200, json.dumps({"success": True, "result": {
                "file_id": "mediakit://F1", "method": "PUT",
                "upload_url": "https://tos.example.com/o"}})
        if path == cloud.SUBMIT_PATH:
            return 200, json.dumps({"success": True, "task_id": "t1"})
        return 200, json.dumps({"task_id": "t1", "status": "completed", "result": {
            "duration": float(MATERIAL_SECONDS),
            "subtitles": [{"subtitle_text": t, "start_time": s, "end_time": e, "speaker": "1"}
                          for t, s, e in SUBS]}})

    def upload(self, method, url, headers, path, timeout):
        return 200, ""


@pytest.fixture
def material(tmp_path):
    out = tmp_path / "素材" / "现场.mp4"   # 中文路径：真实用户素材就是这样
    out.parent.mkdir()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={MATERIAL_SECONDS}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={MATERIAL_SECONDS}",
                    "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(out)], check=True)
    return out


@pytest.fixture
def jy_root(tmp_path, monkeypatch):
    root = tmp_path / "jy_root"
    root.mkdir()
    (root / tj.ROOT_META_NAME).write_text(json.dumps(
        {"all_draft_store": [], "draft_ids": 1, "root_path": str(root)}), encoding="utf-8")
    monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(root))
    return root


@pytest.fixture
def world(tmp_path, monkeypatch, jy_root):
    """除网络外一切真实；返回打桩对象供断言。外发告知由各用例自己决定（consented fixture）。"""
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # Windows 的 Path.home()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # to_jianying --staging 默认 ~/.aicut/staging
    monkeypatch.setenv(secrets.ENV_KEYS["mediakit"], "AK-e2e")
    monkeypatch.setenv(secrets.ENV_KEYS["deepseek"], "sk-e2e")
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr(encode, "_PREFLIGHT", {})  # 真跑一次 VideoToolbox 预检（conftest 默认直接放行）
    monkeypatch.setattr(understand_text, "_sleep", lambda _s: None)
    llm, mk = FakeLLM(), FakeMediaKit()
    monkeypatch.setattr(aicut, "DeepSeekClient", lambda *a, **k: llm)  # aicut.metered 的工厂现取这个名字
    monkeypatch.setattr(cloud, "CloudClient", functools.partial(
        cloud.CloudClient, sleep=lambda _s: None, transport=mk.transport, uploader=mk.upload))
    return {"llm": llm, "mediakit": mk, "pdir": tmp_path / "projects" / NAME, "root": jy_root}


def _new(material, capsys):
    assert aicut.run_cli(["new", NAME, "--material", str(material),
                          "--target", "30", "--no-input"]) == 0, capsys.readouterr().out


def _prepare(material, world, capsys):
    _new(material, capsys)
    review.set_must(world["pdir"] / "work", MUST_SID, True)   # 剪辑师先标★（浏览素材）
    code = aicut.run_cli(["prepare", NAME])
    assert code == 0, capsys.readouterr().out
    assert world["mediakit"].paths and world["llm"].calls      # 确实走的是桩，不是网络
    ledger = usage.load(world["pdir"] / "work")                # 每次 LLM 调用都记了账（KI-32）
    assert ledger["calls"] == world["llm"].answered > 0
    assert ledger["total_tokens"] == world["llm"].answered * FAKE_USAGE["total_tokens"]


def test_prepare_without_consent_stops_before_any_cloud_call(material, world, capsys):
    """PRD §7：没确认过数据外发说明，处理素材在第一个请求之前就停下。"""
    _new(material, capsys)
    assert aicut.run_cli(["prepare", NAME]) == 1
    assert world["mediakit"].paths == [] and world["llm"].calls == 0
    assert not (world["pdir"] / "work/audio/asr.wav").exists()  # 连抽音轨都没开始


def test_material_to_installed_jianying_draft(material, world, consented, monkeypatch,
                                              tmp_path, capsys):
    """打包版路径（proc.FROZEN）：流水线脚本与 to_jianying 同进程运行。"""
    monkeypatch.setattr(proc, "FROZEN", True)
    monkeypatch.setattr(tj, "jianying_running", lambda: False)  # 开发机上剪映可能开着
    _prepare(material, world, capsys)
    pdir, root = world["pdir"], world["root"]

    # GL-25：手写分镜表漏掉★必留段 → 切片之前就拒绝出片
    selected = json.loads((pdir / "work/shots-selected.json").read_text(encoding="utf-8"))
    assert any(MUST_TEXT in (s.get("sub") or "") for s in selected["shots"])
    without_must = [s for s in selected["shots"] if MUST_TEXT not in (s.get("sub") or "")]
    (pdir / "shots.json").write_text(json.dumps({**selected, "shots": without_must},
                                                ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert aicut.run_cli(["build", NAME]) == 1
    assert not (pdir / "output").exists() and not (pdir / "work/clips").exists()
    (pdir / "shots.json").unlink()

    assert aicut.run_cli(["build", NAME]) == 0, capsys.readouterr().out

    tl = json.loads((pdir / "output/v1/timeline.json").read_text(encoding="utf-8"))
    assert media_io.is_complete(pdir / "output/v1/preview.mp4")
    assert all(media_io.is_complete(v["source"]) for v in tl["video"])
    entries = json.loads((root / tj.ROOT_META_NAME).read_text(encoding="utf-8"))["all_draft_store"]
    assert [e["draft_name"] for e in entries] == [f"{NAME}_v1"]
    draft = root / f"{NAME}_v1"
    assert entries[0]["draft_fold_path"] == str(draft)
    res = validate_draft.check(str(draft), expect=tj.expected(tl))
    assert res["fails"] == [], res["fails"]
    assert MUST_TEXT in (draft / "draft_content.json").read_text(encoding="utf-8")  # 必留进片
    assert not (tmp_path / "home/.aicut/staging" / f"{NAME}_v1").exists()  # 安装成功后暂存不保留


def test_material_to_windows_package_dev_mode(material, world, consented, monkeypatch,
                                              tmp_path, capsys):
    """开发版路径：流水线脚本以子进程运行；Windows 包走 module_cmd 子进程 + --dry-run。"""
    monkeypatch.setattr(proc, "FROZEN", False)
    _prepare(material, world, capsys)

    # --no-draft：开发模式装草稿走子进程，里面的 jianying_running（真实 pgrep）无法打桩
    assert aicut.run_cli(["build", NAME, "--no-draft"]) == 0, capsys.readouterr().out
    assert media_io.is_complete(world["pdir"] / "output/v1/preview.mp4")

    out = tmp_path / "exports"
    assert aicut.run_cli(["export", NAME, "-o", str(out)]) == 0, capsys.readouterr().out
    pkg = out / f"{NAME}_v1.zip"
    info = export_draft.inspect_package(pkg)
    assert info["install"] and info["fix_paths"] and info["placeholder"]
    with zipfile.ZipFile(pkg) as z:
        assert MUST_TEXT in z.read(info["drafts"][0]).decode("utf-8")
    assert [p.name for p in out.iterdir()] == [pkg.name]          # 不留 .partial 残片
    assert json.loads((world["root"] / tj.ROOT_META_NAME).read_text(
        encoding="utf-8"))["all_draft_store"] == []               # 导出不碰剪映草稿库


def test_preview_then_export_promotes_the_same_preview(material, world, consented, monkeypatch,
                                                       capsys):
    """M14：先生成预览片（不产生版本），导出时晋升同一份预览片与时间线，再装草稿。"""
    monkeypatch.setattr(proc, "FROZEN", True)
    monkeypatch.setattr(tj, "jianying_running", lambda: False)
    _prepare(material, world, capsys)
    pdir, root = world["pdir"], world["root"]

    assert aicut.run_cli(["preview", NAME]) == 0, capsys.readouterr().out
    staging = pdir / "output/preview"
    assert media_io.is_complete(staging / "preview.mp4")
    assert [p.name for p in (pdir / "output").iterdir()] == ["preview"]  # 没有任何 vN

    assert aicut.run_cli(["build", NAME, "--require-preview"]) == 0, capsys.readouterr().out
    vdir = pdir / "output/v1"
    assert (vdir / "preview.mp4").stat().st_ino == (staging / "preview.mp4").stat().st_ino
    assert media_io.is_complete(vdir / "preview.mp4")
    assert (vdir / "timeline.json").read_bytes() == (staging / "timeline.json").read_bytes()
    entries = json.loads((root / tj.ROOT_META_NAME).read_text(encoding="utf-8"))["all_draft_store"]
    assert [e["draft_name"] for e in entries] == [f"{NAME}_v1"]
    res = validate_draft.check(str(root / f"{NAME}_v1"),
                               expect=tj.expected(json.loads((vdir / "timeline.json").read_text(encoding="utf-8"))))
    assert res["fails"] == [], res["fails"]

# -*- coding: utf-8 -*-
"""剪辑台 · 设置：API Key 与首次使用的数据外发告知（GL-02）。

Key 直接经 pipeline.secrets 存取（钥匙串优先），任何响应、日志都只出现掩码。
路由入口 handle_get / handle_post 返回 (状态码, JSON)；不是本模块的路径返回 None。
"""
from __future__ import annotations

import re
from pathlib import Path

from pipeline import applog, consent, encode, outputs, plat, readiness, schema, secrets, to_jianying

KEY_RE = re.compile(r"[\x21-\x7e]{8,512}")  # 可打印 ASCII、无空白

NEED_CONSENT_MSG = "请先阅读并确认数据外发说明"
NEED_KEYS_MSG = "还没有填写 API Key：{names}。请在「更多 → 设置 · API Key」里填写"
JIANYING_RUNNING_MSG = "剪映正在运行，请先完全退出（Cmd+Q）再导出到 Mac 剪映"
JIANYING_RUNNING_MSG_WIN = "剪映正在运行，请先关闭剪映窗口再导出到 Windows 剪映"
EXPORT_BLOCKED_NEED = "export_blocked"
UNKNOWN_PROVIDER_MSG = "未知的 Key 类型"
BAD_KEY_MSG = "Key 格式不对：应为 8–512 位、不含空格的英文字母 / 数字 / 符号"
SAVE_FAILED_MSG = "保存失败：无法写入钥匙串或配置文件"
DELETE_FAILED_MSG = "清除失败：{reason}"


class PrepareBlocked(Exception):
    """处理素材的前置条件不满足：need = consent | keys。"""

    def __init__(self, need: str, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.need = need
        self.missing = list(missing or [])


def config_payload() -> dict:
    st = secrets.status()  # 只含 configured / source / masked，没有明文
    return {"consent": consent.accepted(),
            "providers": [{"key": k, **secrets.PROVIDER_LABELS[k], **st[k]}
                          for k in secrets.PROVIDERS]}


def check_prepare_ready(pdir: Path) -> None:
    if not consent.accepted():
        raise PrepareBlocked("consent", NEED_CONSENT_MSG)
    missing = readiness.missing_keys(Path(pdir) / "work")
    if missing:
        names = "、".join(secrets.PROVIDER_LABELS[k]["label"] for k in missing)
        raise PrepareBlocked("keys", NEED_KEYS_MSG.format(names=names), missing)
    if problem := encode.preflight():  # 剪辑台进程用的是同一份内置 ffmpeg
        raise PrepareBlocked("encoder", problem)


def check_questions_ready(_pdir: Path) -> None:
    """重新生成决策问题（KI-86）：要外发告知 + DeepSeek Key；不需要转写 Key、不需要编码器。"""
    if not consent.accepted():
        raise PrepareBlocked("consent", NEED_CONSENT_MSG)
    if not secrets.get("deepseek"):
        raise PrepareBlocked("keys", NEED_KEYS_MSG.format(
            names=secrets.PROVIDER_LABELS["deepseek"]["label"]), ["deepseek"])


def jianying_running_msg() -> str:
    return JIANYING_RUNNING_MSG_WIN if plat.IS_WIN else JIANYING_RUNNING_MSG


def check_build_ready(_pdir: Path, body: dict) -> None:
    """导出到 Mac 剪映：剪映开着就先停（E19），免得切片、晋升都做完才在装草稿时失败。"""
    if body.get("target") != "mac":
        return
    try:
        running = to_jianying.jianying_running()
    except to_jianying.InstallError as exc:  # Windows 上 tasklist 失败：无法确认 = 当作开着，别往下做
        raise PrepareBlocked("close_jianying", str(exc)) from exc
    if running:
        raise PrepareBlocked("close_jianying", jianying_running_msg())


def check_export_ready(pdir: Path, body: dict) -> None:
    """生成 Windows 包：含不可用片段（或无法确认）的版本不能再生成（KI-100，⚑Q3）。"""
    _, blocked = outputs.export_block(pdir, schema.check_version(body.get("version")))
    if blocked:
        raise PrepareBlocked(EXPORT_BLOCKED_NEED, blocked)


READY_CHECKS = {"prepare": check_prepare_ready, "questions": check_questions_ready}
BODY_READY_CHECKS = {"build": check_build_ready, "export": check_export_ready}  # 要看请求内容的检查


def check_ready(pdir: Path, task: str, body: dict | None = None) -> None:
    """起任务前的前置检查（没有检查的任务直接放行）；不满足抛 PrepareBlocked → 409。"""
    if isinstance(task, str) and (check := READY_CHECKS.get(task)) is not None:
        check(pdir)
    if isinstance(task, str) and (body_check := BODY_READY_CHECKS.get(task)) is not None:
        body_check(pdir, body or {})


def _provider(body: dict) -> str | None:
    provider = body.get("provider")
    return provider if isinstance(provider, str) and provider in secrets.PROVIDERS else None


def save_key(body: dict) -> tuple[int, dict]:
    provider = _provider(body)
    if provider is None:
        return 400, {"error": UNKNOWN_PROVIDER_MSG}
    value = body.get("value")
    value = value.strip() if isinstance(value, str) else ""
    if not KEY_RE.fullmatch(value):
        return 400, {"error": BAD_KEY_MSG}
    applog.register_secret(value)  # 之后本进程任何日志里出现都打码
    try:
        secrets.set(provider, value)
    except Exception:  # noqa: BLE001 - 异常信息可能带着输入，绝不透传
        return 500, {"error": SAVE_FAILED_MSG}
    return 200, config_payload()


def delete_key(body: dict) -> tuple[int, dict]:
    provider = _provider(body)
    if provider is None:
        return 400, {"error": UNKNOWN_PROVIDER_MSG}
    try:
        secrets.delete(provider)
    except secrets.SecretDeleteError as exc:  # 自家文案，不含 Key
        return 500, {"error": DELETE_FAILED_MSG.format(reason=exc)}
    except Exception:  # noqa: BLE001 - 第三方异常信息可能带 Key，不透传
        return 500, {"error": DELETE_FAILED_MSG.format(reason="无法写入钥匙串或配置文件")}
    return 200, config_payload()


def accept_consent(_body: dict) -> tuple[int, dict]:
    consent.accept()
    return 200, config_payload()


POST_ROUTES = {
    "/api/config/consent": accept_consent,
    "/api/config/key": save_key,
    "/api/config/key/delete": delete_key,
}


def handle_get(path: str) -> tuple[int, dict] | None:
    return (200, config_payload()) if path == "/api/config" else None


def handle_post(path: str, body: dict) -> tuple[int, dict] | None:
    route = POST_ROUTES.get(path)
    return route(body) if route else None

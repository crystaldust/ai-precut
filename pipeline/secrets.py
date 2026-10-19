# -*- coding: utf-8 -*-
"""凭证存储：优先 Keychain（keyring），可降级到 0600 文件。

优先级：
  1. 环境变量（CI / 临时覆盖）
  2. 系统钥匙串（keyring → macOS Keychain / Windows Credential Manager）
  3. 文件 ~/.config/ai-cut/credentials.json（0600）

`AI_CUT_SECRETS=file` 可强制走文件后端（测试/无钥匙串环境）。
日志与界面只用 `mask()`，永不输出明文。
"""
from __future__ import annotations

import json
import os
import stat
import uuid
from pathlib import Path

SERVICE = "ai-cut"
PROVIDERS = ("mediakit", "deepseek")
ENV_KEYS = {
    "mediakit": "MEDIAKIT_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# 界面按这个渲染 Key 输入框；GL-01 换实现时只改这里，界面不用动
PROVIDER_LABELS = {
    "mediakit": {"label": "语音转写（火山引擎）", "hint": "用于把素材音轨转成文字"},
    "deepseek": {"label": "文本分析（DeepSeek）", "hint": "用于理解转写内容、找出重要片段"},
}



class SecretDeleteError(RuntimeError):
    """清除后 Key 仍然读得到（钥匙串被锁 / 拒绝删除），不能假装已清除。"""


# 历史遗留位置：老版本把 mediakit key 放在这里，读取时兼容
LEGACY_FILES = {
    "mediakit": Path.home() / ".mediakit/api_key",
}


def _config_dir() -> Path:
    if custom := os.environ.get("AI_CUT_CONFIG_DIR"):
        return Path(custom).expanduser()
    return Path.home() / ".config" / "ai-cut"


def config_dir() -> Path:
    """凭证与「数据外发告知」确认记录所在目录（不在项目里）。"""
    return _config_dir()


def _cred_file() -> Path:
    return _config_dir() / "credentials.json"


def _force_file() -> bool:
    return os.environ.get("AI_CUT_SECRETS", "").lower() == "file"


def _keyring():
    if _force_file():
        return None
    try:
        import keyring  # type: ignore

        keyring.get_keyring()  # 触发后端选择，但不读写
        return keyring
    except Exception:  # noqa: BLE001 - 没装/无后端都退化为文件
        return None


def _read_file() -> dict:
    path = _cred_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_file(data: dict) -> None:
    """原子写凭证文件：临时文件一创建就是 0600（不经过默认权限），名字随机，失败不留残渣。"""
    path = _cred_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, stat.S_IRWXU)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def mask(value: str | None) -> str:
    """AKLTabcd…9f2a → AKLT****9f2a；过短直接打码。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-4:]}"


def get(provider: str) -> str | None:
    if provider not in PROVIDERS:
        raise ValueError(f"未知凭证：{provider}")
    env = os.environ.get(ENV_KEYS[provider])
    if env:
        return env.strip()
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, provider)
            if value:
                return value
        except Exception:  # noqa: BLE001 - 钥匙串被锁/拒绝时继续降级
            pass
    value = _read_file().get(provider)
    if value:
        return value
    legacy = LEGACY_FILES.get(provider)
    if legacy and legacy.exists():
        try:
            return legacy.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    return None


def peek(provider: str) -> str | None:
    """不碰钥匙串的读取（环境变量 → 凭证文件 → 旧版文件），给日志脱敏登记用，绝不弹授权。"""
    if provider not in PROVIDERS:
        raise ValueError(f"未知凭证：{provider}")
    if env := os.environ.get(ENV_KEYS[provider]):
        return env.strip()
    if value := _read_file().get(provider):
        return value
    legacy = LEGACY_FILES.get(provider)
    try:
        return (legacy.read_text(encoding="utf-8").strip() or None) if legacy and legacy.exists() \
            else None
    except OSError:
        return None


def set(provider: str, value: str) -> str:
    """写入凭证，返回实际使用的后端（keyring / file）。"""
    if provider not in PROVIDERS:
        raise ValueError(f"未知凭证：{provider}")
    value = value.strip()
    if not value:
        raise ValueError("凭证不能为空")
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, provider, value)
            return "keyring"
        except Exception:  # noqa: BLE001
            pass
    data = _read_file()
    data[provider] = value
    _write_file(data)
    return "file"


def delete(provider: str) -> None:
    """从钥匙串和凭证文件里删掉 Key，并确认真的删掉了（环境变量 / 旧版文件不归这里管）。"""
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, provider)
        except Exception:  # noqa: BLE001 - 本来就没有也会抛；下面统一核实
            pass
        try:
            still = kr.get_password(SERVICE, provider)
        except Exception as exc:  # noqa: BLE001
            raise SecretDeleteError("无法确认钥匙串里的 Key 已删除") from exc
        if still:
            raise SecretDeleteError("钥匙串拒绝删除这个 Key（可能被锁定），请在「钥匙串访问」里手动删除")
    data = _read_file()
    if data.pop(provider, None) is not None:
        _write_file(data)
    if provider in _read_file():
        raise SecretDeleteError("凭证文件里的 Key 没删掉")


def status() -> dict[str, dict]:
    """给界面用：是否配置、来源、掩码值。"""
    out: dict[str, dict] = {}
    for provider in PROVIDERS:
        value = get(provider)
        if not value:
            source = ""
        elif os.environ.get(ENV_KEYS[provider]):
            source = "env"
        elif provider in _read_file():
            source = "file"
        elif LEGACY_FILES.get(provider) and LEGACY_FILES[provider].exists():
            source = "legacy"
        else:
            source = "keyring"
        out[provider] = {
            "configured": bool(value),
            "source": source,
            "masked": mask(value),
        }
    return out

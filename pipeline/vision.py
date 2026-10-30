# -*- coding: utf-8 -*-
"""画面理解（AI 多模态）的项目设置：开不开、用哪一档。

按项目存进 project.json 的 vision 字段（每条素材的隐私情况不同，不做全局开关）；
进分析输入指纹（fingerprints.analysis_inputs），改了之后 ② 标「需要更新」。
档位用英文 key，界面另行映射中文，第 3 阶段再映射到 MediaKit 的抽帧参数。
"""
from __future__ import annotations

TIERS = ("economy", "balanced", "quality")
DEFAULT_TIER = "economy"
DEFAULT = {"enabled": False, "tier": DEFAULT_TIER}  # 与 schema.DEFAULTS["vision"] 一致（测试锁定）
OFF = "off"
BAD_SETTING_MSG = "画面理解设置不对：enabled 要是开 / 关，档位只能是省钱 / 均衡 / 精细"


def normalize(raw: object) -> dict:
    """逐字段回落默认：不是对象、enabled 不是 True、档位不认识都按默认处理；返回新 dict。"""
    data = raw if isinstance(raw, dict) else {}
    tier = data.get("tier")
    return {"enabled": data.get("enabled") is True, "tier": tier if tier in TIERS else DEFAULT_TIER}


def fingerprint(setting: dict) -> str:
    """关闭时档位不影响结果，统一记 off。"""
    return f"on:{setting['tier']}" if setting["enabled"] else OFF


def check(body: dict) -> dict:
    """接口入参校验：enabled 必须是布尔（1 / "true" 都不算），tier 必须认识；不合法抛 ValueError。"""
    enabled, tier = body.get("enabled"), body.get("tier")
    if not isinstance(enabled, bool) or not isinstance(tier, str) or tier not in TIERS:
        raise ValueError(BAD_SETTING_MSG)
    return {"enabled": enabled, "tier": tier}

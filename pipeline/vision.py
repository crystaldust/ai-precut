# -*- coding: utf-8 -*-
"""画面理解（AI 多模态）的项目设置：开不开、用哪一档。

按项目存进 project.json 的 vision 字段（每条素材的隐私情况不同，不做全局开关）；
进分析输入指纹（fingerprints.analysis_inputs），改了之后 ② 标「需要更新」。
档位用英文 key，界面另行映射中文；TIER_FPS 映射到 MediaKit video-understand-router 的抽帧参数。
档位只按手动 fps 区分：第 1 阶段实测手动 2 fps 时间最准、费用与 Economy 相当；
level 与 manual_option 同传虽被接受，但看不出哪个生效，所以不传 level。
"""
from __future__ import annotations

TIERS = ("economy", "balanced", "quality")
DEFAULT_TIER = "economy"
DEFAULT = {"enabled": False, "tier": DEFAULT_TIER}  # 与 schema.DEFAULTS["vision"] 一致（测试锁定）
OFF = "off"
TIER_FPS = {"economy": 2.0, "balanced": 2.5, "quality": 3.0}
CHUNK_S = 300        # 每段 5 分钟
MIN_TAIL_S = 20      # 最后一段不足这么长就并进前一段
MAX_FRAMES = 1000    # 接口单视频帧数上限
PROMPT_VERSION = 1   # 提示词或解析规则变了就加 1：旧段结果作废
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


def from_choice(choice: str | None) -> dict:
    """命令行 --vision off|economy|balanced|quality → project.json 的 vision 字段。"""
    return {"enabled": True, "tier": choice} if choice in TIERS else dict(DEFAULT)


def is_on(cfg: dict) -> bool:
    return normalize(cfg.get("vision")).get("enabled") is True


def tier_params(tier: str) -> dict:
    """提交给接口的抽帧参数（新 dict）。不传音轨：画面代理本来就没有声音。"""
    return {"manual_option": {"fps": TIER_FPS[tier], "need_audio": False}}

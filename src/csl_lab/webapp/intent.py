from __future__ import annotations

import re
from typing import Any


INTENT_YES = "有意向"
INTENT_NO = "没意向"

# 仍在求购、未成交的新车买家信号（不含泛化「求购」，避免二手帖误伤）
_BUYER_HINTS = (
    "蹲销售",
    "求销售",
    "想买",
    "想入手",
    "准备买",
    "打算买",
    "询价",
    "来个销售",
    "有没有销售",
    "私我",
    "滴我",
    "蹲一个",
    "来个靠谱",
)

# 已成交 / 已提车 / 已下定 / 已购复盘
_COMPLETED_PATTERNS = (
    r"提车啦",
    r"提车记",
    r"喜提",
    r"终于提车",
    r"顺利.*开回家",
    r"把新车开回家",
    r"交车",
    r"已经订车",
    r"本周已经订",
    r"已订车",
    r"已经下定",
    r"已下定",
    r"立马.*定下来",
    r"直接.*下单",
    r"心动下单",
    r"盲订了",
    r"已经盲订",
    r"定下来了",
    r"期待早日提车",
    r"等.*提车",
    r"刚提",
    r"真实车主",
    r"新车主实测",
    r"买亏了吗",
    r"落地买的",
    r"买.+只花了",
    r"\bOTD\b",
    r"出门价",
)

# 二手车求购 / 收车
_USED_CAR_PATTERNS = (
    r"二手",
    r"车商收购",
    r"收车",
    r"个人求购",
    r"真心求购",
    r"真心求够",  # 常见错别字
    r"\d{2}年及?之后",
    r"\d{2}年的?\w{0,12}(?:帕萨特|迈腾|雅阁|凯美瑞|天籁|宝马|奥迪|奔驰)",
    r"求购.+\d{2}年",
    r"\d{2}年.+(?:豪华|尊贵|舒适).*(?:求|收|买)",
)

# 明确新车语境（相对二手场景应排除）
_NEW_CAR_EXCLUDE_PATTERNS = (
    r"提新车",
    r"新车主",
    r"喜提",
    r"盲订",
    r"下定了",
    r"已经订车",
    r"4S",
    r"蹲销售",
    r"求销售",
    r"来个靠谱销售",
)

# 营销种草 / 门店话术
_AD_HINTS = (
    "直降",
    "落地价",
    "现车充足",
    "到店详谈",
    "联系销售",
    "全国可提",
    "先说结论",
    "给想买车的朋友",
)


def _text_has_completed_purchase(text: str) -> bool:
    if not text:
        return False
    return any(re.search(p, text, flags=re.IGNORECASE) for p in _COMPLETED_PATTERNS)


def _text_is_used_car_request(text: str) -> bool:
    if not text:
        return False
    return any(re.search(p, text) for p in _USED_CAR_PATTERNS)


def _text_looks_like_new_car_buyer(text: str) -> bool:
    if not text:
        return False
    if any(re.search(p, text, flags=re.IGNORECASE) for p in _NEW_CAR_EXCLUDE_PATTERNS):
        # 若同时强二手信号，仍以二手为准（由 used_car 分支先判）
        return True
    if "新车" in text and any(h in text for h in _BUYER_HINTS):
        return True
    return False


def _text_looks_like_ad(text: str) -> bool:
    if not text:
        return False
    hits = sum(1 for h in _AD_HINTS if h in text)
    if hits >= 2:
        return True
    if "试驾" in text and ("直降" in text or "值不值得冲" in text) and len(text) > 200:
        return True
    return False


def _map_new_car_intent(
    judgement: dict[str, Any], *, title: str, body: str
) -> tuple[str, str]:
    """主机厂新车：二手求购/已成交/营销 → 没意向；未成交新车求购 → 有意向。"""
    role = judgement.get("content_role") or ""
    polarity = judgement.get("sentiment_polarity") or ""
    reason = (judgement.get("reason") or "").strip()
    text = f"{title or ''} {body or ''}"

    if _text_is_used_car_request(text):
        return INTENT_NO, reason or "二手车求购/收车，非新车待跟进线索，判为没意向。"

    if _text_has_completed_purchase(text):
        return INTENT_NO, reason or "已订车/已提车/已购复盘，非待跟进线索，判为没意向。"

    if role == "dealer_ad" or _text_looks_like_ad(text):
        return INTENT_NO, reason or "经销商/营销种草帖，判为没意向。"

    if role == "unrelated":
        return INTENT_NO, reason or "与新车求购无关，判为没意向。"
    if role == "media":
        return INTENT_NO, reason or "媒体评测口吻，非买家求购，判为没意向。"

    if role == "owner_review":
        if any(h in text for h in _BUYER_HINTS) and not _text_has_completed_purchase(text):
            return INTENT_YES, reason or "车主语境但含未成交新车求购/找销售信号，判为有意向。"
        return INTENT_NO, reason or "车主晒单/复盘/已提车，非求购意向。"

    if role == "prospect_research":
        return INTENT_YES, reason or "潜在买家调研/求购且未见成交完成态，判为有意向。"

    if any(h in text for h in _BUYER_HINTS):
        return INTENT_YES, reason or "正文含新车求购/找销售信号，判为有意向。"
    if polarity == "positive" and role == "unknown":
        return INTENT_NO, reason or "角色不明的正面内容，保守判为没意向。"
    return INTENT_NO, reason or "证据不足，保守判为没意向。"


def _map_used_car_intent(
    judgement: dict[str, Any], *, title: str, body: str
) -> tuple[str, str]:
    """二手车：二手求购/收车 → 有意向；新车蹲销售/提新车/已成交复盘 → 没意向。"""
    role = judgement.get("content_role") or ""
    polarity = judgement.get("sentiment_polarity") or ""
    reason = (judgement.get("reason") or "").strip()
    text = f"{title or ''} {body or ''}"

    # 1) 明确新车求购/提车：非二手线索
    if _text_looks_like_new_car_buyer(text) and not _text_is_used_car_request(text):
        return INTENT_NO, reason or "新车求购/提车晒单，非二手待跟进线索，判为没意向。"

    # 2) 已成交复盘（含新车/二手已买）
    if _text_has_completed_purchase(text) and not _text_is_used_car_request(text):
        return INTENT_NO, reason or "已订车/已提车/已购复盘，非待跟进线索，判为没意向。"

    # 3) 营销种草
    if role == "dealer_ad" or _text_looks_like_ad(text):
        return INTENT_NO, reason or "经销商/营销种草帖，判为没意向。"

    if role == "media":
        return INTENT_NO, reason or "媒体评测口吻，非买家求购，判为没意向。"

    # 4) 二手求购 / 收车：有意向
    if _text_is_used_car_request(text):
        return INTENT_YES, reason or "二手车求购/收车，判为有意向。"

    if role == "prospect_research":
        # skill 已把新车排除为 unrelated；此处信任角色，但再挡一层新车信号
        if _text_looks_like_new_car_buyer(text):
            return INTENT_NO, reason or "新车语境潜客，相对二手场景判为没意向。"
        return INTENT_YES, reason or "二手潜客调研/求购，判为有意向。"

    if role == "owner_review":
        return INTENT_NO, reason or "已购复盘/晒单，非待跟进二手线索，判为没意向。"

    if role == "unrelated":
        return INTENT_NO, reason or "与二手求购无关，判为没意向。"

    if polarity == "positive" and role == "unknown":
        return INTENT_NO, reason or "角色不明的正面内容，保守判为没意向。"
    return INTENT_NO, reason or "证据不足，保守判为没意向。"


def _map_default_intent(
    judgement: dict[str, Any], *, title: str, body: str
) -> tuple[str, str]:
    """未知场景：仅依赖 content_role 保守映射。"""
    role = judgement.get("content_role") or ""
    reason = (judgement.get("reason") or "").strip()
    if role == "prospect_research":
        return INTENT_YES, reason or "潜客调研角色，判为有意向。"
    if role in ("dealer_ad", "owner_review", "media", "unrelated"):
        return INTENT_NO, reason or f"角色为 {role}，保守判为没意向。"
    return INTENT_NO, reason or "未知场景且证据不足，保守判为没意向。"


def map_agent_intent(
    judgement: dict[str, Any] | None,
    *,
    title: str = "",
    body: str = "",
    scenario_id: str = "new_car",
) -> tuple[str, str]:
    """把情感初判映射为「有意向 / 没意向」，并给出简短理由。

    按 scenario_id 分支：
    - new_car：排除二手/已成交等
    - used_car：二手求购为有意向；新车蹲销售/提新车为没意向
    - 其他：保守默认
    """
    j = judgement or {}
    sid = (scenario_id or "new_car").strip() or "new_car"
    if sid == "new_car":
        return _map_new_car_intent(j, title=title, body=body)
    if sid == "used_car":
        return _map_used_car_intent(j, title=title, body=body)
    return _map_default_intent(j, title=title, body=body)

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from csl_lab.crawl.merge_note import PostRecord
from csl_lab.paths import ScenarioPack


@dataclass(frozen=True)
class LlmResponse:
    scores: list[dict[str, Any]]
    usage: dict[str, Any]
    raw_content: str | None = None


class LlmError(RuntimeError):
    pass


def build_prompt(scenario: ScenarioPack, posts: list[PostRecord]) -> tuple[str, str]:
    system = scenario.skill_md
    product_ctx = {
        "brand": scenario.product.brand,
        "series": scenario.product.series,
        "aliases": scenario.product.aliases,
    }
    competitors_ctx = [
        {"brand": c.brand, "series": c.series} for c in scenario.competitors
    ]
    payload = []
    for post in posts:
        crawled_city = (post.city or post.ip_location or "").strip() or None
        payload.append(
            {
                "item_id": post.note_id,
                "title": post.title,
                "body": post.body,
                "published_at": post.published_at,
                "author_nickname": post.author_nickname,
                "city": crawled_city,
                "city_missing": crawled_city is None,
                "like_count": post.like_count,
                "comment_count": post.comment_count,
                "share_count": post.share_count,
                "collected_count": post.collected_count,
                "content_type": post.content_type,
                "scenario_id": scenario.scenario_id,
                "product_id": scenario.product_id,
                "product": product_ctx,
                "competitors": competitors_ctx,
            }
        )
    user = (
        "请对下列帖子逐条评分，只输出 JSON array，元素顺序与输入一致。"
        "规则对主机厂新车通用；本品以每条中的 product 字段为准。"
        "若 city 非空：inferred_city 必须为 null；"
        "若 city 为空（city_missing=true）：可根据标题+正文推断 inferred_city，无法判断则 null。\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return system, user


def normalize_inferred_city(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "未知", "不确定"}:
        return None
    return text[:32]


def resolve_display_city(
    *,
    crawled_city: str | None,
    judgement: dict[str, Any] | None,
) -> str | None:
    """爬取城市优先；缺失时才用 agent 的 inferred_city；都没有则留空。"""
    crawled = (crawled_city or "").strip() or None
    if crawled:
        return crawled
    if not judgement:
        return None
    return normalize_inferred_city(judgement.get("inferred_city"))


def _parse_json_array(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    data = json.loads(text)
    if isinstance(data, dict):
        return [data]
    if not isinstance(data, list):
        raise ValueError("LLM output is not a JSON array")
    return data


class FakeSentimentClient:
    """Deterministic offline scorer for dry-run / tests."""

    def __init__(self, *, model: str = "fake-sentiment-model"):
        self.model = model

    def score_posts(
        self, *, scenario: ScenarioPack, posts: list[PostRecord]
    ) -> LlmResponse:
        return LlmResponse(
            scores=[self._score(post) for post in posts],
            usage={"total_tokens": 0},
        )

    def _score(self, post: PostRecord) -> dict[str, Any]:
        text = f"{post.title or ''} {post.body or ''}"
        nick = post.author_nickname or ""
        lower = text.lower()

        if any(k in text for k in ("现车", "优惠", "私信报价", "到店")) or "汽车" in nick:
            role = "dealer_ad"
            polarity = "neutral"
            risk = "low"
            confidence = 0.7
            reason = "疑似经销商导流文案。"
        elif any(k in text for k in ("后悔", "虚标", "推诿", "故障", "自燃")):
            role = "owner_review"
            polarity = "negative"
            risk = "high" if "自燃" in text else "mid"
            confidence = 0.8
            reason = "正文含明确负面体验证据。"
        elif any(k in text for k in ("好看", "好用", "香", "达标", "推荐")):
            role = "owner_review"
            polarity = "positive"
            risk = "low"
            confidence = 0.75
            reason = "正文含明确正面体验证据。"
        elif "对比" in text or "比" in text:
            role = "prospect_research"
            polarity = "mixed"
            risk = "low"
            confidence = 0.65
            reason = "存在对比表述，情感混合。"
        elif "mona" not in lower and "L03" not in text and "小鹏" not in text:
            role = "unrelated"
            polarity = "neutral"
            risk = "low"
            confidence = 0.4
            reason = "与本品关联弱。"
        else:
            role = "unknown"
            polarity = "neutral"
            risk = "low"
            confidence = 0.5
            reason = "证据有限，保守中性。"

        aspects = []
        if "续航" in text or "掉电" in text:
            aspects.append(
                {
                    "name": "range",
                    "polarity": "negative" if polarity == "negative" else polarity,
                    "evidence": "正文提及续航/掉电",
                }
            )
        if "智驾" in text:
            aspects.append(
                {
                    "name": "smart_drive",
                    "polarity": polarity if polarity != "neutral" else "positive",
                    "evidence": "正文提及智驾",
                }
            )
        if "外观" in text:
            aspects.append(
                {
                    "name": "exterior",
                    "polarity": "positive",
                    "evidence": "正文提及外观",
                }
            )
        if "售后" in text:
            aspects.append(
                {
                    "name": "service",
                    "polarity": "negative",
                    "evidence": "正文提及售后",
                }
            )
        if "秦PLUS" in text or "对比" in text:
            aspects.append(
                {
                    "name": "competitor",
                    "polarity": "mixed",
                    "evidence": "正文含竞品对比",
                }
            )

        competitors = []
        if "秦PLUS" in text:
            competitors.append(
                {
                    "brand": "比亚迪",
                    "series": "秦PLUS",
                    "stance": "prefer_competitor"
                    if polarity == "negative"
                    else "unclear",
                }
            )

        intensity = {"positive": 4, "negative": 4, "mixed": 3, "neutral": 2}[polarity]
        crawled_city = (post.city or post.ip_location or "").strip()
        inferred_city = None
        if not crawled_city:
            blob = f"{post.title or ''} {post.body or ''}"
            # fake 仅做演示级规则；真实 DeepSeek 走 skill 推断
            m = re.search(
                r"坐标\s*([\u4e00-\u9fff]{2,3})(?=[\s，,。！!？?\d求蹲看提在的到去来]|$)",
                blob,
            )
            if not m:
                m = re.search(
                    r"(?:求|蹲)\s*([\u4e00-\u9fff]{2,3})\s*(?:的)?\s*(?:销售|门店|店)",
                    blob,
                )
            if not m:
                m = re.search(
                    r"([\u4e00-\u9fff]{2,3})\s*(?:提车|看车)",
                    blob,
                )
            if m:
                inferred_city = m.group(1)[:32]
        return {
            "item_id": post.note_id,
            "sentiment_polarity": polarity,
            "sentiment_intensity": intensity,
            "aspects": aspects,
            "competitor_mentions": competitors,
            "brand_stance": {
                "own": polarity if polarity != "neutral" else "unclear",
                "overall": polarity,
            },
            "content_role": role,
            "opinion_risk": risk,
            "summary": (post.body or post.title or "")[:120],
            "reason": reason[:80],
            "confidence": confidence,
            "inferred_city": None if crawled_city else inferred_city,
        }


class DeepSeekSentimentClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.deepseek.com",
        temperature: float = 0.0,
        timeout: float = 60.0,
        retry_count: int = 2,
    ):
        if not api_key:
            raise LlmError("DEEPSEEK_API_KEY is empty")
        self.model = model
        self.temperature = temperature
        self.retry_count = retry_count
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            trust_env=False,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
        )
        self.api_key = api_key

    def close(self) -> None:
        self._client.close()

    def score_posts(
        self, *, scenario: ScenarioPack, posts: list[PostRecord]
    ) -> LlmResponse:
        system, user = build_prompt(scenario, posts)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        last_err: Exception | None = None
        for attempt in range(self.retry_count + 1):
            try:
                response = self._client.post(
                    "/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if response.status_code == 429:
                    raise LlmError(f"DeepSeek 429 rate limited: {response.text[:200]}")
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                scores = _parse_json_array(content)
                usage = body.get("usage") or {}
                return LlmResponse(
                    scores=scores,
                    usage={
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                    raw_content=content,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt >= self.retry_count:
                    break
                # 429 / 网络抖动时退避更久
                delay = 2.0 * (attempt + 1)
                if "429" in str(exc):
                    delay = 5.0 * (attempt + 1)
                time.sleep(delay)
        raise LlmError(f"DeepSeek scoring failed: {last_err}")

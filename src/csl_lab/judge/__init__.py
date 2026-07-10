from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from csl_lab.crawl.merge_note import PostRecord
from csl_lab.crawl.store import read_jsonl, write_jsonl
from csl_lab.judge.llm import DeepSeekSentimentClient, FakeSentimentClient, LlmResponse, resolve_display_city
from csl_lab.paths import DATA_DIR, ScenarioPack, ensure_data_dirs, utc_now_iso


@dataclass
class JudgeResult:
    run_id: str
    judgements_path: Path
    count: int
    provider: str
    scores: list[dict[str, Any]]


def load_posts(path: Path) -> list[PostRecord]:
    return [PostRecord(**row) for row in read_jsonl(path)]


def build_llm_client(
    *,
    provider: str,
    model: str,
    api_key: str | None = None,
    base_url: str = "https://api.deepseek.com",
    temperature: float = 0.0,
) -> Any:
    if provider == "fake":
        return FakeSentimentClient(model=model or "fake-sentiment-model")
    if provider == "deepseek":
        return DeepSeekSentimentClient(
            api_key=api_key or "",
            model=model,
            base_url=base_url,
            temperature=temperature,
        )
    raise ValueError(f"unsupported CSL_LLM_PROVIDER: {provider}")


def run_judge(
    scenario: ScenarioPack,
    *,
    posts: list[PostRecord],
    llm_client: Any,
    run_id: str | None = None,
    provider: str = "fake",
) -> JudgeResult:
    ensure_data_dirs()
    run_id = run_id or f"judge_{utc_now_iso().replace(':', '').replace('-', '')[:15]}"
    response: LlmResponse = llm_client.score_posts(scenario=scenario, posts=posts)
    by_id = {s.get("item_id"): s for s in response.scores if s.get("item_id")}

    rows: list[dict[str, Any]] = []
    for post in posts:
        score = by_id.get(post.note_id)
        crawled_city = (post.city or post.ip_location or "").strip() or None
        display_city = resolve_display_city(
            crawled_city=crawled_city,
            judgement=score,
        )
        rows.append(
            {
                "run_id": run_id,
                "scenario_id": scenario.scenario_id,
                "product_id": scenario.product_id,
                "skill_version": scenario.skill_version,
                "provider": provider,
                "model": getattr(llm_client, "model", None),
                "judged_at": utc_now_iso(),
                "post_snapshot": {
                    "note_id": post.note_id,
                    "title": post.title,
                    "body": post.body,
                    "body_complete": post.body_complete,
                    "published_at": post.published_at,
                    "author_id": post.author_id,
                    "author_nickname": post.author_nickname,
                    "city": display_city,
                    "crawled_city": crawled_city,
                    "inferred_city": None
                    if crawled_city
                    else (
                        (score or {}).get("inferred_city")
                        if isinstance(score, dict)
                        else None
                    ),
                    "canonical_url": post.canonical_url,
                    "view_count": post.view_count,
                    "like_count": post.like_count,
                    "comment_count": post.comment_count,
                    "share_count": post.share_count,
                    "collected_count": post.collected_count,
                    "content_type": post.content_type,
                    "source_keyword": post.source_keyword,
                },
                "judgement": score,
                "missing_judgement": score is None,
            }
        )

    out = DATA_DIR / "judgements" / f"{run_id}.jsonl"
    write_jsonl(out, rows)
    return JudgeResult(
        run_id=run_id,
        judgements_path=out,
        count=len(rows),
        provider=provider,
        scores=response.scores,
    )

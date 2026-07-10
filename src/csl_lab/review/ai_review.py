from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from csl_lab.crawl.store import read_jsonl, write_jsonl
from csl_lab.paths import DATA_DIR, ensure_data_dirs, utc_now_iso


DEALER_HINTS = ("现车", "优惠", "私信", "到店", "报价")
NEGATIVE_HINTS = ("后悔", "虚标", "推诿", "故障", "自燃", "维权")


@dataclass
class ReviewQueueResult:
    run_id: str
    queue_path: Path
    flagged: int
    total: int


def _flags_for_row(row: dict[str, Any]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    judgement = row.get("judgement") or {}
    snap = row.get("post_snapshot") or {}
    text = f"{snap.get('title') or ''} {snap.get('body') or ''}"

    if row.get("missing_judgement"):
        flags.append({"code": "missing_judgement", "detail": "初判缺失"})
        return flags

    conf = judgement.get("confidence")
    if isinstance(conf, (int, float)) and conf < 0.55:
        flags.append({"code": "low_confidence", "detail": f"confidence={conf}"})

    role = judgement.get("content_role")
    if role == "dealer_ad" and judgement.get("sentiment_polarity") in (
        "positive",
        "negative",
    ):
        try:
            intensity = float(judgement.get("sentiment_intensity") or 0)
        except (TypeError, ValueError):
            intensity = 0.0
        if intensity >= 4:
            flags.append(
                {
                    "code": "role_polarity_conflict",
                    "detail": "广告角色却强情感",
                }
            )

    if any(h in text for h in DEALER_HINTS) and role not in ("dealer_ad", "unknown"):
        flags.append({"code": "possible_ad_mislabel", "detail": "文案像导流但角色非广告"})

    if any(h in text for h in NEGATIVE_HINTS):
        if judgement.get("sentiment_polarity") == "positive":
            flags.append(
                {"code": "negative_text_positive_label", "detail": "负面词与正极性冲突"}
            )
        if judgement.get("opinion_risk") == "low" and "自燃" in text:
            flags.append({"code": "risk_underestimated", "detail": "自燃类应提高风险"})

    if not snap.get("body"):
        flags.append({"code": "empty_body", "detail": "正文为空"})

    return flags


def build_review_queue(
    *,
    judgements_path: Path,
    run_id: str | None = None,
) -> ReviewQueueResult:
    ensure_data_dirs()
    rows = read_jsonl(judgements_path)
    run_id = run_id or judgements_path.stem
    queue: list[dict[str, Any]] = []
    for row in rows:
        flags = _flags_for_row(row)
        if not flags:
            continue
        priority = "high" if any(
            f["code"]
            in {
                "missing_judgement",
                "negative_text_positive_label",
                "risk_underestimated",
            }
            for f in flags
        ) else "mid"
        if all(f["code"] == "low_confidence" for f in flags):
            priority = "low"
        queue.append(
            {
                "run_id": run_id,
                "note_id": (row.get("post_snapshot") or {}).get("note_id"),
                "scenario_id": row.get("scenario_id"),
                "skill_version": row.get("skill_version"),
                "priority": priority,
                "flags": flags,
                "judgement": row.get("judgement"),
                "post_snapshot": row.get("post_snapshot"),
                "queued_at": utc_now_iso(),
            }
        )

    # high first
    order = {"high": 0, "mid": 1, "low": 2}
    queue.sort(key=lambda x: order.get(x["priority"], 9))
    out = DATA_DIR / "review_queue" / f"{run_id}.jsonl"
    write_jsonl(out, queue)
    return ReviewQueueResult(
        run_id=run_id,
        queue_path=out,
        flagged=len(queue),
        total=len(rows),
    )

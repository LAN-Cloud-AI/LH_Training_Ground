from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from csl_lab.crawl.merge_note import PostRecord
from csl_lab.crawl.store import read_jsonl, write_jsonl
from csl_lab.judge import build_llm_client, run_judge
from csl_lab.paths import DATA_DIR, ScenarioPack, ensure_data_dirs, utc_now_iso


@dataclass
class EvalReport:
    report_path: Path
    total: int
    polarity_accuracy: float | None
    role_accuracy: float | None
    risk_accuracy: float | None


def _load_seed_or_gold(path: Path) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    if rows:
        return rows
    # allow single JSON array file
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    raise ValueError(f"unsupported eval file: {path}")


def _gold_polarity(row: dict[str, Any]) -> str | None:
    if "gold" in row and isinstance(row["gold"], dict):
        return row["gold"].get("sentiment_polarity")
    label = row.get("human_label") or {}
    return label.get("sentiment_polarity")


def _gold_role(row: dict[str, Any]) -> str | None:
    if "gold" in row and isinstance(row["gold"], dict):
        return row["gold"].get("content_role")
    label = row.get("human_label") or {}
    return label.get("content_role")


def _gold_risk(row: dict[str, Any]) -> str | None:
    if "gold" in row and isinstance(row["gold"], dict):
        return row["gold"].get("opinion_risk")
    label = row.get("human_label") or {}
    return label.get("opinion_risk")


def run_eval(
    scenario: ScenarioPack,
    *,
    eval_path: Path,
    llm_client: Any,
    provider: str = "fake",
) -> EvalReport:
    ensure_data_dirs()
    rows = _load_seed_or_gold(eval_path)
    posts: list[PostRecord] = []
    for row in rows:
        note_id = str(row.get("item_id") or row.get("note_id") or "")
        snap = row.get("post_snapshot") or {}
        posts.append(
            PostRecord(
                note_id=note_id,
                canonical_url=snap.get("canonical_url")
                or f"https://www.xiaohongshu.com/explore/{note_id}",
                title=row.get("title") or snap.get("title"),
                body=row.get("body") or snap.get("body"),
                body_complete=True,
                author_nickname=snap.get("author_nickname"),
                city=snap.get("city"),
                content_type=snap.get("content_type") or "note",
                scenario_id=scenario.scenario_id,
            )
        )

    judge = run_judge(
        scenario,
        posts=posts,
        llm_client=llm_client,
        provider=provider,
        run_id=f"eval_{utc_now_iso().replace(':', '').replace('-', '')[:15]}",
    )
    by_id = {
        (r.get("post_snapshot") or {}).get("note_id"): (r.get("judgement") or {})
        for r in read_jsonl(judge.judgements_path)
    }

    pol_ok = pol_n = role_ok = role_n = risk_ok = risk_n = 0
    details = []
    for row in rows:
        note_id = str(row.get("item_id") or row.get("note_id") or "")
        pred = by_id.get(note_id) or {}
        g_pol = _gold_polarity(row)
        g_role = _gold_role(row)
        g_risk = _gold_risk(row)
        if g_pol:
            pol_n += 1
            if pred.get("sentiment_polarity") == g_pol:
                pol_ok += 1
        if g_role:
            role_n += 1
            if pred.get("content_role") == g_role:
                role_ok += 1
        if g_risk:
            risk_n += 1
            if pred.get("opinion_risk") == g_risk:
                risk_ok += 1
        details.append(
            {
                "item_id": note_id,
                "gold_polarity": g_pol,
                "pred_polarity": pred.get("sentiment_polarity"),
                "gold_role": g_role,
                "pred_role": pred.get("content_role"),
                "gold_risk": g_risk,
                "pred_risk": pred.get("opinion_risk"),
            }
        )

    def _rate(ok: int, n: int) -> float | None:
        return None if n == 0 else round(ok / n, 4)

    report = {
        "scenario_id": scenario.scenario_id,
        "skill_version": scenario.skill_version,
        "eval_path": str(eval_path),
        "provider": provider,
        "total": len(rows),
        "polarity_accuracy": _rate(pol_ok, pol_n),
        "role_accuracy": _rate(role_ok, role_n),
        "risk_accuracy": _rate(risk_ok, risk_n),
        "generated_at": utc_now_iso(),
        "details": details,
    }
    out = DATA_DIR / "eval_reports" / f"{scenario.scenario_id}_{utc_now_iso().replace(':', '').replace('-', '')[:15]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # also keep a jsonl mirror of details for diffing
    write_jsonl(out.with_suffix(".jsonl"), details)
    return EvalReport(
        report_path=out,
        total=len(rows),
        polarity_accuracy=report["polarity_accuracy"],
        role_accuracy=report["role_accuracy"],
        risk_accuracy=report["risk_accuracy"],
    )

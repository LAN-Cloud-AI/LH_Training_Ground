from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from csl_lab.crawl.merge_note import (
    PostRecord,
    extract_note_from_detail_body,
    extract_notes_from_search_body,
    merge_keyword_hits,
    merge_search_and_detail,
)
from csl_lab.crawl.store import append_jsonl, write_jsonl
from csl_lab.crawl.tikhub_client import TikHubClient
from csl_lab.paths import DATA_DIR, FIXTURES_DIR, ScenarioPack, ensure_data_dirs, utc_now_iso


@dataclass
class CrawlResult:
    run_id: str
    posts_path: Path
    log_path: Path
    post_count: int
    detail_ok: int
    detail_failed: int
    search_pages: int
    posts: list[PostRecord] = field(default_factory=list)
    keyword: str | None = None
    started_at: str | None = None
    hit_count: int = 0
    duplicate_count: int = 0
    new_count: int = 0


def _log(log_path: Path, event: str, **payload: Any) -> None:
    append_jsonl(log_path, {"ts": utc_now_iso(), "event": event, **payload})


def crawl_from_fixture(
    scenario: ScenarioPack,
    *,
    fixture_path: Path | None = None,
    run_id: str | None = None,
) -> CrawlResult:
    """Offline crawl using a search_notes sample JSON (no TikHub calls)."""
    ensure_data_dirs()
    run_id = run_id or f"fixture_{utc_now_iso().replace(':', '').replace('-', '')[:15]}"
    fixture_path = fixture_path or (FIXTURES_DIR / "search_notes_sample.json")
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    keyword = payload.get("keyword") or (scenario.keywords[0] if scenario.keywords else "")
    notes = extract_notes_from_search_body(payload.get("body"))
    posts_path = DATA_DIR / "posts" / f"{run_id}.jsonl"
    log_path = DATA_DIR / "crawl_logs" / f"{run_id}.jsonl"
    _log(log_path, "fixture_start", fixture=str(fixture_path), keyword=keyword)

    by_id: dict[str, PostRecord] = {}
    for note in notes:
        # Fixture mode: treat search body as complete enough for dry-run demos
        post = merge_search_and_detail(
            search_note=note,
            detail_note=note,
            source_keyword=keyword,
            scenario_id=scenario.scenario_id,
            crawled_at=utc_now_iso(),
        )
        existing = by_id.get(post.note_id)
        by_id[post.note_id] = (
            merge_keyword_hits(existing, post) if existing else post
        )

    posts = list(by_id.values())
    write_jsonl(posts_path, [p.model_dump() for p in posts])
    _log(log_path, "fixture_done", post_count=len(posts))
    return CrawlResult(
        run_id=run_id,
        posts_path=posts_path,
        log_path=log_path,
        post_count=len(posts),
        detail_ok=len(posts),
        detail_failed=0,
        search_pages=1,
        posts=posts,
    )


def crawl_scenario(
    scenario: ScenarioPack,
    *,
    client: TikHubClient,
    run_id: str | None = None,
    keywords: list[str] | None = None,
) -> CrawlResult:
    ensure_data_dirs()
    started_at = utc_now_iso()
    run_id = run_id or f"crawl_{started_at.replace(':', '').replace('-', '')[:15]}"
    posts_path = DATA_DIR / "posts" / f"{run_id}.jsonl"
    log_path = DATA_DIR / "crawl_logs" / f"{run_id}.jsonl"
    keywords = keywords or scenario.keywords
    cfg = scenario.crawl
    primary_keyword = keywords[0] if keywords else None

    _log(
        log_path,
        "crawl_start",
        scenario_id=scenario.scenario_id,
        keywords=keywords,
        max_pages=cfg.max_search_pages_per_keyword,
        max_detail=cfg.max_note_detail_per_run,
        started_at=started_at,
    )

    by_id: dict[str, dict[str, Any]] = {}
    search_pages = 0
    hit_count = 0
    search_errors: list[str] = []
    for keyword in keywords:
        page = 1
        pages_done = 0
        while pages_done < cfg.max_search_pages_per_keyword:
            try:
                resp = client.search_notes_page(keyword=keyword, page=page)
            except Exception as exc:  # noqa: BLE001 — log and continue keywords
                err = f"{keyword} page={page}: {exc}"
                search_errors.append(err)
                _log(log_path, "search_error", keyword=keyword, page=page, error=str(exc))
                break
            search_pages += 1
            pages_done += 1
            body = resp.get("body")
            notes = extract_notes_from_search_body(body)
            hit_count += len(notes)
            _log(
                log_path,
                "search_page",
                keyword=keyword,
                page=page,
                notes=len(notes),
                http_status=resp.get("http_status"),
            )
            for note in notes:
                note_id = str(note.get("id"))
                entry = by_id.get(note_id)
                if entry:
                    kws = entry.setdefault("keywords", [])
                    if keyword not in kws:
                        kws.append(keyword)
                else:
                    by_id[note_id] = {"search_note": note, "keywords": [keyword]}

            next_page = TikHubClient.next_search_page(body)
            if not next_page:
                break
            page = next_page

    if search_pages == 0 and search_errors:
        raise RuntimeError(
            "TikHub 搜索失败，未拉到任何页：" + " | ".join(search_errors[:3])
        )

    detail_ok = 0
    detail_failed = 0
    posts: list[PostRecord] = []
    detail_budget = cfg.max_note_detail_per_run

    for note_id, entry in by_id.items():
        search_note = entry["search_note"]
        keyword = (entry.get("keywords") or [None])[0]
        detail_note = None
        detail_error = None

        if cfg.require_note_detail and detail_budget > 0:
            token = search_note.get("xsec_token")
            if not token:
                detail_error = "missing_xsec_token"
                detail_failed += 1
                _log(log_path, "detail_skip", note_id=note_id, reason=detail_error)
            else:
                detail_budget -= 1
                try:
                    detail_resp = client.note_detail(
                        note_id=note_id, xsec_token=str(token)
                    )
                    detail_note = extract_note_from_detail_body(detail_resp.get("body"))
                    if not detail_note:
                        detail_error = "detail_empty_or_biz_error"
                        detail_failed += 1
                        _log(
                            log_path,
                            "detail_failed",
                            note_id=note_id,
                            reason=detail_error,
                            body_snippet=str(detail_resp.get("body"))[:300],
                        )
                    else:
                        detail_ok += 1
                        _log(log_path, "detail_ok", note_id=note_id)
                except Exception as exc:  # noqa: BLE001
                    detail_error = f"detail_exception:{exc}"
                    detail_failed += 1
                    _log(log_path, "detail_failed", note_id=note_id, reason=detail_error)
        elif cfg.require_note_detail and detail_budget <= 0:
            detail_error = "detail_budget_exhausted"

        post = merge_search_and_detail(
            search_note=search_note,
            detail_note=detail_note,
            source_keyword=keyword,
            scenario_id=scenario.scenario_id,
            detail_error=detail_error,
            crawled_at=utc_now_iso(),
        )
        for kw in entry.get("keywords") or []:
            if kw and kw not in post.source_keywords:
                post.source_keywords.append(kw)

        if not post.body_complete and not cfg.keep_incomplete_body:
            _log(log_path, "drop_incomplete", note_id=note_id)
            continue
        posts.append(post)

    new_count = len(posts)
    duplicate_count = max(0, hit_count - len(by_id))
    write_jsonl(posts_path, [p.model_dump() for p in posts])
    _log(
        log_path,
        "crawl_done",
        post_count=len(posts),
        detail_ok=detail_ok,
        detail_failed=detail_failed,
        search_pages=search_pages,
        keyword=primary_keyword,
        started_at=started_at,
        hit_count=hit_count,
        unique_count=len(by_id),
        duplicate_count=duplicate_count,
        new_count=new_count,
    )
    return CrawlResult(
        run_id=run_id,
        posts_path=posts_path,
        log_path=log_path,
        post_count=len(posts),
        detail_ok=detail_ok,
        detail_failed=detail_failed,
        search_pages=search_pages,
        posts=posts,
        keyword=primary_keyword,
        started_at=started_at,
        hit_count=hit_count,
        duplicate_count=duplicate_count,
        new_count=new_count,
    )

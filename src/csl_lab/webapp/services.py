from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from csl_lab.crawl import crawl_scenario
from csl_lab.crawl.merge_note import PostRecord
from csl_lab.crawl.store import read_jsonl, write_jsonl
from csl_lab.crawl.tikhub_client import TikHubClient
from csl_lab.judge import build_llm_client, load_posts, run_judge
from csl_lab.judge.llm import resolve_display_city
from csl_lab.paths import DATA_DIR, ensure_data_dirs, ensure_scenario, load_scenario, utc_now_iso
from csl_lab.webapp.config_store import load_config
from csl_lab.webapp.db import dumps_json, get_comment, upsert_comment
from csl_lab.webapp.intent import map_agent_intent


def _client_from_config() -> TikHubClient:
    cfg = load_config()
    token = cfg.get("tikhub_api_token") or ""
    if not token:
        raise RuntimeError("请先在配置页填写 TikHub API Token")
    return TikHubClient(
        token=token,
        base_url=cfg.get("tikhub_base_url") or "https://api.tikhub.io",
        rpm=int(cfg.get("tikhub_rpm") or 30),
    )


def run_crawl_job(
    *,
    keyword: str,
    max_pages: int = 10,
    scenario_id: str = "new_car",
    product_id: str = "mona_l03",
    fetch_detail: bool = True,
) -> dict[str, Any]:
    ensure_data_dirs()
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("关键词不能为空")
    scenario_id = (scenario_id or "new_car").strip() or "new_car"
    scenario_id = ensure_scenario(scenario_id, create_if_missing=True)
    scenario = load_scenario(
        scenario_id,
        product_id=product_id,
        ensure_product_exists=True,
        keyword=keyword,
    )
    scenario.crawl.max_search_pages_per_keyword = max(1, min(int(max_pages), 50))
    scenario.crawl.max_note_detail_per_run = 400 if fetch_detail else 0
    scenario.crawl.require_note_detail = bool(fetch_detail)
    scenario.crawl.keep_incomplete_body = True

    client = _client_from_config()
    try:
        result = crawl_scenario(
            scenario,
            client=client,
            keywords=[keyword],
        )
    finally:
        client.close()

    complete = 0
    try:
        for row in read_jsonl(result.posts_path):
            if row.get("body_complete"):
                complete += 1
    except OSError:
        pass

    return {
        "run_id": result.run_id,
        "posts_path": str(result.posts_path),
        "log_path": str(result.log_path),
        "post_count": result.post_count,
        "detail_ok": result.detail_ok,
        "detail_failed": result.detail_failed,
        "search_pages": result.search_pages,
        "body_complete": complete,
        "keyword": result.keyword or keyword,
        "started_at": result.started_at,
        "hit_count": result.hit_count,
        "duplicate_count": result.duplicate_count,
        "new_count": result.new_count or result.post_count,
        "scenario_id": scenario.scenario_id,
        "product_id": scenario.product_id or product_id,
    }


def run_judge_and_ingest(
    *,
    posts_path: str,
    scenario_id: str = "new_car",
    product_id: str = "mona_l03",
    crawl_run_id: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    api_key = cfg.get("deepseek_api_key") or ""
    if not api_key:
        raise RuntimeError("请先在配置页填写 DeepSeek API Key")
    model = cfg.get("deepseek_model") or "deepseek-v4-flash"
    scenario_id = (scenario_id or "new_car").strip() or "new_car"
    scenario_id = ensure_scenario(scenario_id, create_if_missing=True)
    scenario = load_scenario(
        scenario_id,
        product_id=product_id,
        ensure_product_exists=True,
    )
    posts = load_posts(Path(posts_path))
    if not posts:
        raise ValueError("帖子文件为空")

    # 分批调用，避免一次 prompt 过大；多批并行打 DeepSeek
    batch_size = int(os.environ.get("CSL_JUDGE_BATCH_SIZE", "8"))
    max_workers = int(os.environ.get("CSL_JUDGE_CONCURRENCY", "64"))
    base_url = cfg.get("deepseek_base_url") or "https://api.deepseek.com"
    judge_run_id = f"judge_{utc_now_iso().replace(':', '').replace('-', '')[:15]}"

    batches: list[tuple[int, list[PostRecord]]] = []
    for i in range(0, len(posts), batch_size):
        batches.append((i // batch_size, posts[i : i + batch_size]))
    workers = max(1, min(max_workers, len(batches)))

    def _score_batch(batch_idx: int, chunk: list[PostRecord]) -> tuple[int, list[dict[str, Any]]]:
        # 每线程独立 client，避免共享 httpx.Client 的连接池争用
        client = build_llm_client(
            provider="deepseek",
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
        try:
            part = run_judge(
                scenario,
                posts=chunk,
                llm_client=client,
                run_id=f"{judge_run_id}_b{batch_idx}",
                provider="deepseek",
            )
            return batch_idx, read_jsonl(part.judgements_path)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    scored: dict[int, list[dict[str, Any]]] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_score_batch, idx, chunk): idx for idx, chunk in batches
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                batch_idx, rows = fut.result()
                scored[batch_idx] = rows
            except Exception as exc:  # noqa: BLE001
                errors.append(f"batch {idx}: {exc}")

    if errors and not scored:
        raise RuntimeError("判断全部失败：" + " | ".join(errors[:3]))
    if errors:
        raise RuntimeError(
            f"判断部分失败（{len(errors)}/{len(batches)}）：" + " | ".join(errors[:3])
        )

    all_rows: list[dict[str, Any]] = []
    for idx, _ in batches:
        all_rows.extend(scored.get(idx) or [])

    # 合并写一份总 judgements
    out_judge = DATA_DIR / "judgements" / f"{judge_run_id}.jsonl"
    write_jsonl(out_judge, all_rows)

    ingested = 0
    intent_yes = 0
    for row in all_rows:
        snap = row.get("post_snapshot") or {}
        judgement = row.get("judgement") or {}
        intent, reason = map_agent_intent(
            judgement,
            title=snap.get("title") or "",
            body=snap.get("body") or "",
            scenario_id=scenario.scenario_id,
        )
        if intent == "有意向":
            intent_yes += 1
        note_id = snap.get("note_id") or judgement.get("item_id")
        if not note_id:
            continue
        # run_judge 已按「爬取优先 / 否则 inferred_city」写入 snap.city
        city = snap.get("city")
        if not city:
            city = resolve_display_city(
                crawled_city=snap.get("crawled_city"),
                judgement=judgement,
            )
        upsert_comment(
            {
                "note_id": note_id,
                "title": snap.get("title"),
                "body": snap.get("body"),
                "published_at": snap.get("published_at"),
                "city": city,
                "view_count": snap.get("view_count"),
                "like_count": snap.get("like_count"),
                "comment_count": snap.get("comment_count"),
                "canonical_url": snap.get("canonical_url")
                or f"https://www.xiaohongshu.com/explore/{note_id}",
                "agent_intent": intent,
                "agent_reason": reason,
                "human_correction": None,
                "correction_reason": None,
                "raw_judgement": dumps_json(judgement),
                "crawl_run_id": crawl_run_id,
                "judge_run_id": judge_run_id,
                "scenario_id": scenario.scenario_id,
                "product_id": scenario.product_id or product_id,
            }
        )
        ingested += 1

    return {
        "judge_run_id": judge_run_id,
        "judgements_path": str(out_judge),
        "ingested": ingested,
        "intent_yes": intent_yes,
        "intent_no": ingested - intent_yes,
        "model": model,
        "posts_path": posts_path,
        "batch_size": batch_size,
        "concurrency": workers,
        "batches": len(batches),
        "scenario_id": scenario.scenario_id,
        "product_id": scenario.product_id or product_id,
    }


def _summarize_post_file(path: Path) -> dict[str, Any]:
    """从 posts + crawl_logs 汇总列表展示字段（兼容旧文件）。"""
    keyword = ""
    started_at = ""
    hit_count = 0
    new_count = 0
    scenario_id = ""
    try:
        rows = list(read_jsonl(path))
        new_count = len(rows)
        for row in rows:
            if not scenario_id and row.get("scenario_id"):
                scenario_id = str(row.get("scenario_id"))
            if not keyword:
                keyword = str(row.get("source_keyword") or "")
                if not keyword:
                    kws = row.get("source_keywords") or []
                    if kws:
                        keyword = str(kws[0])
            if not started_at and row.get("crawled_at"):
                started_at = str(row.get("crawled_at"))
    except OSError:
        pass

    log_path = DATA_DIR / "crawl_logs" / f"{path.stem}.jsonl"
    if log_path.is_file():
        try:
            for line in log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("event") == "crawl_start":
                    started_at = str(ev.get("started_at") or ev.get("ts") or started_at)
                    kws = ev.get("keywords") or []
                    if kws and not keyword:
                        keyword = str(kws[0])
                    if ev.get("scenario_id") and not scenario_id:
                        scenario_id = str(ev["scenario_id"])
                elif ev.get("event") == "search_page":
                    hit_count += int(ev.get("notes") or 0)
                elif ev.get("event") == "crawl_done":
                    if ev.get("keyword"):
                        keyword = str(ev["keyword"])
                    if ev.get("started_at"):
                        started_at = str(ev["started_at"])
                    if ev.get("hit_count") is not None:
                        hit_count = int(ev["hit_count"])
                    if ev.get("new_count") is not None:
                        new_count = int(ev["new_count"])
                    elif ev.get("post_count") is not None:
                        new_count = int(ev["post_count"])
                    if ev.get("scenario_id") and not scenario_id:
                        scenario_id = str(ev["scenario_id"])
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    if hit_count <= 0:
        hit_count = new_count
    duplicate_count = max(0, hit_count - new_count)
    return {
        "path": str(path),
        "name": path.name,
        "count": new_count,
        "mtime": path.stat().st_mtime,
        "keyword": keyword,
        "started_at": started_at,
        "hit_count": hit_count,
        "duplicate_count": duplicate_count,
        "new_count": new_count,
        "scenario_id": scenario_id or "new_car",
    }


def list_post_files() -> list[dict[str, Any]]:
    ensure_data_dirs()
    files = sorted(
        (DATA_DIR / "posts").glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [_summarize_post_file(p) for p in files[:30]]


def preview_posts_file(posts_path: str, *, limit: int = 500) -> dict[str, Any]:
    """读取指定爬取 JSONL，并按 note_id 合并已入库的判断结果（可为空）。"""
    path = Path(posts_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"posts file not found: {path}")
    if path.suffix.lower() != ".jsonl":
        raise ValueError("only .jsonl posts files are supported")

    summary = _summarize_post_file(path)
    rows = list(read_jsonl(path))
    truncated = False
    if limit > 0 and len(rows) > limit:
        rows = rows[:limit]
        truncated = True

    items: list[dict[str, Any]] = []
    judged = 0
    for row in rows:
        note_id = str(row.get("note_id") or "")
        comment = get_comment(note_id) if note_id else None
        if comment and comment.get("agent_intent"):
            judged += 1
        items.append(
            {
                "note_id": note_id,
                "title": row.get("title"),
                "body": row.get("body"),
                "published_at": row.get("published_at"),
                "city": row.get("city") or row.get("ip_location"),
                "view_count": row.get("view_count"),
                "like_count": row.get("like_count"),
                "comment_count": row.get("comment_count"),
                "canonical_url": row.get("canonical_url")
                or (f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else None),
                "body_complete": bool(row.get("body_complete")),
                "source_keyword": row.get("source_keyword"),
                "agent_intent": (comment or {}).get("agent_intent"),
                "agent_reason": (comment or {}).get("agent_reason"),
                "human_correction": (comment or {}).get("human_correction"),
                "correction_reason": (comment or {}).get("correction_reason"),
                "judged": bool(comment and comment.get("agent_intent")),
            }
        )

    return {
        "path": str(path),
        "name": path.name,
        "summary": summary,
        "count": len(items),
        "judged_count": judged,
        "truncated": truncated,
        "items": items,
    }

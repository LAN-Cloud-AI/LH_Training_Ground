from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from csl_lab.paths import LAB_ROOT

DB_PATH = LAB_ROOT / "data" / "webapp" / "comments.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    conn = connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              note_id TEXT NOT NULL UNIQUE,
              title TEXT,
              body TEXT,
              published_at TEXT,
              city TEXT,
              view_count INTEGER,
              like_count INTEGER,
              comment_count INTEGER,
              canonical_url TEXT,
              agent_intent TEXT NOT NULL,
              agent_reason TEXT,
              human_correction TEXT,
              correction_reason TEXT,
              raw_judgement TEXT,
              crawl_run_id TEXT,
              judge_run_id TEXT,
              scenario_id TEXT,
              product_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "comments", "scenario_id", "scenario_id TEXT")
        _ensure_column(conn, "comments", "product_id", "product_id TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS correction_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              note_id TEXT NOT NULL,
              before_intent TEXT,
              after_intent TEXT,
              correction_reason TEXT,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def upsert_comment(row: dict[str, Any]) -> None:
    now = _utc_now()
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO comments (
              note_id, title, body, published_at, city, view_count, like_count,
              comment_count, canonical_url, agent_intent, agent_reason,
              human_correction, correction_reason, raw_judgement,
              crawl_run_id, judge_run_id, scenario_id, product_id,
              created_at, updated_at
            ) VALUES (
              :note_id, :title, :body, :published_at, :city, :view_count, :like_count,
              :comment_count, :canonical_url, :agent_intent, :agent_reason,
              :human_correction, :correction_reason, :raw_judgement,
              :crawl_run_id, :judge_run_id, :scenario_id, :product_id,
              :created_at, :updated_at
            )
            ON CONFLICT(note_id) DO UPDATE SET
              title=excluded.title,
              body=excluded.body,
              published_at=excluded.published_at,
              city=excluded.city,
              view_count=excluded.view_count,
              like_count=excluded.like_count,
              comment_count=excluded.comment_count,
              canonical_url=excluded.canonical_url,
              agent_intent=excluded.agent_intent,
              agent_reason=excluded.agent_reason,
              raw_judgement=excluded.raw_judgement,
              crawl_run_id=COALESCE(excluded.crawl_run_id, comments.crawl_run_id),
              judge_run_id=excluded.judge_run_id,
              scenario_id=COALESCE(excluded.scenario_id, comments.scenario_id),
              product_id=COALESCE(excluded.product_id, comments.product_id),
              updated_at=excluded.updated_at
            """,
            {
                **row,
                "human_correction": row.get("human_correction"),
                "correction_reason": row.get("correction_reason"),
                "scenario_id": row.get("scenario_id") or "new_car",
                "product_id": row.get("product_id"),
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()
    finally:
        conn.close()


def list_comments(
    *,
    limit: int = 200,
    offset: int = 0,
    scenario_id: str | None = None,
) -> list[dict[str, Any]]:
    conn = connect()
    try:
        if scenario_id:
            cur = conn.execute(
                """
                SELECT * FROM comments
                WHERE COALESCE(scenario_id, 'new_car') = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (scenario_id, limit, offset),
            )
        else:
            cur = conn.execute(
                """
                SELECT * FROM comments
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_comment(note_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        cur = conn.execute("SELECT * FROM comments WHERE note_id = ?", (note_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def apply_human_correction(
    *,
    note_id: str,
    human_correction: str,
    correction_reason: str,
) -> dict[str, Any]:
    if human_correction not in ("有意向", "没意向"):
        raise ValueError("human_correction must be 有意向 or 没意向")
    existing = get_comment(note_id)
    if not existing:
        raise KeyError(f"note not found: {note_id}")
    now = _utc_now()
    conn = connect()
    try:
        conn.execute(
            """
            UPDATE comments
            SET human_correction = ?, correction_reason = ?, updated_at = ?
            WHERE note_id = ?
            """,
            (human_correction, correction_reason, now, note_id),
        )
        conn.execute(
            """
            INSERT INTO correction_log (
              note_id, before_intent, after_intent, correction_reason, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                note_id,
                existing.get("human_correction") or existing.get("agent_intent"),
                human_correction,
                correction_reason,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_comment(note_id) or {}


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)

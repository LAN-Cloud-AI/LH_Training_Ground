from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _pick(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _to_iso(ts: Any) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, str) and ts.strip():
        return ts
    try:
        num = float(ts)
    except (TypeError, ValueError):
        return None
    # 秒级时间戳
    if num > 1e12:
        num = num / 1000.0
    return datetime.fromtimestamp(num, tz=timezone.utc).isoformat()


def _content_type(note: dict[str, Any]) -> str:
    note_type = str(note.get("type") or "").lower()
    if note_type == "video" or note.get("video_info_v2"):
        return "video_note"
    return "note"


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_note_card(card: dict[str, Any], *, fallback_id: str | None = None) -> dict[str, Any]:
    """把 web_v3 note_card 归一成与搜索 note 相近的字段，供 note_to_partial 使用。"""
    interact = card.get("interact_info") if isinstance(card.get("interact_info"), dict) else {}
    user_in = card.get("user") if isinstance(card.get("user"), dict) else {}
    note_id = _pick(card.get("note_id"), card.get("id"), fallback_id)
    user = {
        "userid": _pick(user_in.get("user_id"), user_in.get("userid"), user_in.get("id")),
        "user_id": _pick(user_in.get("user_id"), user_in.get("userid"), user_in.get("id")),
        "nickname": _pick(user_in.get("nickname"), user_in.get("nick_name")),
        "images": _pick(user_in.get("avatar"), user_in.get("images"), user_in.get("image")),
        "avatar": _pick(user_in.get("avatar"), user_in.get("images"), user_in.get("image")),
        "red_id": _pick(user_in.get("red_id")),
        "xsec_token": _pick(user_in.get("xsec_token")),
    }
    return {
        "id": str(note_id) if note_id is not None else None,
        "note_id": str(note_id) if note_id is not None else None,
        "title": _pick(card.get("title"), card.get("display_title")),
        "desc": _pick(card.get("desc"), card.get("description")),
        "type": _pick(card.get("type")),
        "timestamp": _pick(card.get("time"), card.get("timestamp"), card.get("last_update_time")),
        "create_time": _pick(card.get("time"), card.get("create_time")),
        "ip_location": _pick(card.get("ip_location")),
        "liked_count": _as_int(_pick(interact.get("liked_count"), card.get("liked_count"), card.get("likes"))),
        "comments_count": _as_int(
            _pick(interact.get("comment_count"), card.get("comments_count"), card.get("comment_count"))
        ),
        "shared_count": _as_int(
            _pick(interact.get("share_count"), card.get("shared_count"), card.get("share_count"))
        ),
        "collected_count": _as_int(
            _pick(interact.get("collected_count"), card.get("collected_count"))
        ),
        "view_count": _as_int(_pick(card.get("view_count"))),
        "xsec_token": _pick(card.get("xsec_token")),
        "user": user,
        "tag_list": card.get("tag_list"),
        "image_list": card.get("image_list"),
        "_source": "note_card",
        "_raw_note_card": card,
    }


def extract_note_from_detail_body(body: dict[str, Any] | None) -> dict[str, Any] | None:
    """从 TikHub note_detail 响应 body 中抽出 note 对象；失败返回 None。

    兼容形态：
    - 旧：data.data.detail.note / note_info（含 id）
    - 新 web_v3：data.data.items[].note_card（含 note_id / desc / interact_info）
    """
    if not body:
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        return None
    # 业务失败常见：data.data is null，或 ok/success 为假且无 items
    inner = data.get("data")
    if inner is None:
        return None
    if not isinstance(inner, dict):
        return None

    # web_v3: items[].note_card
    items = inner.get("items")
    if isinstance(items, list) and items:
        first = items[0] if isinstance(items[0], dict) else None
        if first:
            card = first.get("note_card") if isinstance(first.get("note_card"), dict) else None
            if card:
                normalized = normalize_note_card(
                    card, fallback_id=_pick(first.get("id"), first.get("note_id"))
                )
                if normalized.get("id"):
                    return normalized
            # 偶发直接把 note 放在 item 上
            if first.get("id") or first.get("note_id") or first.get("desc"):
                if first.get("note_id") and not first.get("id"):
                    return normalize_note_card(first, fallback_id=first.get("note_id"))
                if first.get("id"):
                    return first

    note = (
        (inner.get("detail") or {}).get("note")
        if isinstance(inner.get("detail"), dict)
        else None
    )
    if not note and isinstance(inner.get("detail"), dict):
        note = inner["detail"].get("note_info") or inner.get("detail")
    if not note:
        note = inner.get("note")
    if isinstance(note, dict):
        if note.get("id"):
            return note
        if note.get("note_id") or note.get("desc"):
            return normalize_note_card(note)
    return None


def extract_notes_from_search_body(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not body:
        return []
    data = body.get("data")
    if not isinstance(data, dict):
        return []
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    items = inner.get("items") if isinstance(inner, dict) else None
    if not isinstance(items, list):
        return []
    notes: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        note = item.get("note") if isinstance(item.get("note"), dict) else item
        if note.get("id"):
            notes.append(note)
    return notes


class PostRecord(BaseModel):
    note_id: str
    canonical_url: str
    xsec_token: str | None = None
    title: str | None = None
    body: str | None = None
    body_complete: bool = False
    published_at: str | None = None
    author_id: str | None = None
    author_nickname: str | None = None
    author_avatar_url: str | None = None
    author_red_id: str | None = None
    city: str | None = None
    ip_location: str | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    collected_count: int | None = None
    view_count: int | None = None
    content_type: str = "note"
    source_keyword: str | None = None
    source_keywords: list[str] = Field(default_factory=list)
    scenario_id: str | None = None
    crawled_at: str | None = None
    detail_error: str | None = None
    raw_search: dict[str, Any] | None = None
    raw_detail: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None

    @property
    def item_id(self) -> str:
        return self.note_id


def note_to_partial(note: dict[str, Any], *, source_keyword: str | None = None) -> dict[str, Any]:
    user = note.get("user") if isinstance(note.get("user"), dict) else {}
    return {
        "note_id": str(note.get("id")),
        "canonical_url": f"https://www.xiaohongshu.com/explore/{note.get('id')}",
        "xsec_token": _pick(note.get("xsec_token")),
        "title": _pick(note.get("title"), note.get("display_title")),
        "body": _pick(note.get("desc")),
        "published_at": _to_iso(
            _pick(note.get("timestamp"), note.get("create_time"), note.get("time"))
        ),
        "author_id": _pick(user.get("userid"), user.get("user_id"), user.get("id")),
        "author_nickname": _pick(user.get("nickname"), user.get("nick_name")),
        "author_avatar_url": _pick(user.get("images"), user.get("image"), user.get("avatar")),
        "author_red_id": _pick(user.get("red_id")),
        "city": _pick(note.get("ip_location"), user.get("ip_location")),
        "ip_location": _pick(note.get("ip_location"), user.get("ip_location")),
        "like_count": _pick(note.get("liked_count"), note.get("likes")),
        "comment_count": _pick(note.get("comments_count"), note.get("comment_count")),
        "share_count": _pick(note.get("shared_count"), note.get("share_count")),
        "collected_count": _pick(note.get("collected_count")),
        "view_count": _pick(note.get("view_count")),
        "content_type": _content_type(note),
        "source_keyword": source_keyword,
    }


def merge_search_and_detail(
    *,
    search_note: dict[str, Any],
    detail_note: dict[str, Any] | None,
    source_keyword: str | None,
    scenario_id: str | None,
    detail_error: str | None = None,
    crawled_at: str | None = None,
) -> PostRecord:
    """详情非空字段优先；正文以详情为准才算 body_complete。"""
    base = note_to_partial(search_note, source_keyword=source_keyword)
    body_complete = False
    if detail_note:
        detail_partial = note_to_partial(detail_note, source_keyword=source_keyword)
        for key, value in detail_partial.items():
            if value is None or value == "":
                continue
            if key == "source_keyword":
                continue
            base[key] = value
        if detail_partial.get("body"):
            body_complete = True
            base["body"] = detail_partial["body"]

    keywords = [source_keyword] if source_keyword else []
    raw = dict(search_note)
    if detail_note:
        raw = {**raw, **detail_note}

    return PostRecord(
        **base,
        body_complete=body_complete,
        source_keywords=keywords,
        scenario_id=scenario_id,
        crawled_at=crawled_at,
        detail_error=detail_error,
        raw_search=search_note,
        raw_detail=detail_note,
        raw=raw,
    )


def merge_keyword_hits(existing: PostRecord, incoming: PostRecord) -> PostRecord:
    """同一 note 多关键词命中时合并 source_keywords，优先保留 body_complete 的版本。"""
    data = existing.model_dump()
    other = incoming.model_dump()
    prefer = incoming if incoming.body_complete and not existing.body_complete else existing
    prefer_data = prefer.model_dump()
    keywords = list(
        dict.fromkeys(
            (data.get("source_keywords") or [])
            + (other.get("source_keywords") or [])
            + ([data.get("source_keyword")] if data.get("source_keyword") else [])
            + ([other.get("source_keyword")] if other.get("source_keyword") else [])
        )
    )
    prefer_data["source_keywords"] = [k for k in keywords if k]
    if prefer_data["source_keywords"] and not prefer_data.get("source_keyword"):
        prefer_data["source_keyword"] = prefer_data["source_keywords"][0]
    return PostRecord(**prefer_data)

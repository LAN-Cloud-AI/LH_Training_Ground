from __future__ import annotations

from csl_lab.crawl.merge_note import (
    extract_note_from_detail_body,
    extract_notes_from_search_body,
    merge_search_and_detail,
    normalize_note_card,
)


def test_extract_notes_from_fixture():
    import json
    from csl_lab.paths import FIXTURES_DIR

    payload = json.loads(
        (FIXTURES_DIR / "search_notes_sample.json").read_text(encoding="utf-8")
    )
    notes = extract_notes_from_search_body(payload["body"])
    assert len(notes) == 2
    assert notes[0]["id"]


def test_merge_prefers_detail_body():
    search = {
        "id": "n1",
        "desc": "截断正文",
        "title": "t",
        "xsec_token": "tok",
        "liked_count": 1,
        "comments_count": 2,
        "user": {"userid": "u1", "nickname": "nick"},
        "timestamp": 1700000000,
        "ip_location": "上海",
    }
    detail = {
        "id": "n1",
        "desc": "完整正文更长更完整",
        "title": "t2",
        "liked_count": 10,
        "comments_count": 20,
        "user": {"userid": "u1", "nickname": "nick2"},
        "timestamp": 1700000001,
        "ip_location": "北京",
    }
    post = merge_search_and_detail(
        search_note=search,
        detail_note=detail,
        source_keyword="小鹏Mona L03",
        scenario_id="mona_l03_new_car",
    )
    assert post.body_complete is True
    assert post.body == "完整正文更长更完整"
    assert post.like_count == 10
    assert post.city == "北京"
    assert post.author_nickname == "nick2"
    assert post.source_keyword == "小鹏Mona L03"


def test_merge_without_detail_incomplete():
    search = {
        "id": "n2",
        "desc": "只有搜索截断",
        "user": {"userid": "u2", "nickname": "x"},
        "timestamp": 1700000000,
    }
    post = merge_search_and_detail(
        search_note=search,
        detail_note=None,
        source_keyword="k",
        scenario_id="mona_l03_new_car",
        detail_error="detail_empty_or_biz_error",
    )
    assert post.body_complete is False
    assert post.body == "只有搜索截断"
    assert post.detail_error == "detail_empty_or_biz_error"


def test_extract_note_card_from_web_v3_detail():
    body = {
        "code": 200,
        "data": {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": "6a4722d0000000001702e2c4",
                        "model_type": "note",
                        "note_card": {
                            "note_id": "6a4722d0000000001702e2c4",
                            "title": "蹲一个山东的小鹏L03销售",
                            "desc": "完整详情正文，比搜索更长。",
                            "type": "normal",
                            "time": 1783046864000,
                            "ip_location": "山东",
                            "user": {
                                "user_id": "61865f14000000001000f4c2",
                                "nickname": "qwe",
                                "avatar": "https://example.com/a.jpg",
                            },
                            "interact_info": {
                                "liked_count": "3",
                                "comment_count": "27",
                                "collected_count": "1",
                                "share_count": "",
                            },
                        },
                    }
                ]
            },
        },
    }
    note = extract_note_from_detail_body(body)
    assert note is not None
    assert note["id"] == "6a4722d0000000001702e2c4"
    assert note["desc"].startswith("完整详情正文")
    assert note["liked_count"] == 3
    assert note["comments_count"] == 27
    assert note["user"]["nickname"] == "qwe"
    assert note["ip_location"] == "山东"

    post = merge_search_and_detail(
        search_note={
            "id": "6a4722d0000000001702e2c4",
            "desc": "截断",
            "xsec_token": "tok",
            "user": {"userid": "u", "nickname": "old"},
            "liked_count": 1,
            "comments_count": 1,
            "timestamp": 1700000000,
        },
        detail_note=note,
        source_keyword="小鹏 l03 蹲销售",
        scenario_id="new_car",
    )
    assert post.body_complete is True
    assert post.body.startswith("完整详情正文")
    assert post.city == "山东"
    assert post.like_count == 3
    assert post.comment_count == 27


def test_normalize_note_card_requires_id():
    card = normalize_note_card({"desc": "x"}, fallback_id="abc")
    assert card["id"] == "abc"

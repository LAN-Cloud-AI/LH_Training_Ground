from csl_lab.crawl.merge_note import PostRecord
from csl_lab.judge.llm import FakeSentimentClient, resolve_display_city


def test_resolve_display_city_prefers_crawled():
    assert (
        resolve_display_city(
            crawled_city="上海",
            judgement={"inferred_city": "北京"},
        )
        == "上海"
    )


def test_resolve_display_city_uses_inferred_when_missing():
    assert (
        resolve_display_city(
            crawled_city=None,
            judgement={"inferred_city": "成都"},
        )
        == "成都"
    )


def test_resolve_display_city_stays_empty():
    assert resolve_display_city(crawled_city="", judgement={"inferred_city": None}) is None
    assert resolve_display_city(crawled_city=None, judgement=None) is None


def test_fake_client_infers_city_only_when_missing():
    client = FakeSentimentClient()
    with_city = PostRecord(
        note_id="1",
        canonical_url="https://www.xiaohongshu.com/explore/1",
        title="蹲销售",
        body="坐标广州求靠谱销售",
        city="山东",
    )
    without = PostRecord(
        note_id="2",
        canonical_url="https://www.xiaohongshu.com/explore/2",
        title="蹲销售",
        body="坐标广州求靠谱销售",
        city=None,
    )
    # FakeSentimentClient.score_posts needs scenario; call _score directly
    s1 = client._score(with_city)
    s2 = client._score(without)
    assert s1["inferred_city"] is None
    assert s2["inferred_city"] == "广州"
    assert resolve_display_city(crawled_city=with_city.city, judgement=s1) == "山东"
    assert resolve_display_city(crawled_city=without.city, judgement=s2) == "广州"

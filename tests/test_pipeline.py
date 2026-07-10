from __future__ import annotations

from csl_lab.crawl import crawl_from_fixture
from csl_lab.eval import run_eval
from csl_lab.judge import build_llm_client, run_judge
from csl_lab.paths import list_products, load_scenario, resolve_scenario_ref
from csl_lab.review.ai_review import build_review_queue


def test_resolve_legacy_alias():
    base, product = resolve_scenario_ref("mona_l03_new_car", None)
    assert base == "new_car"
    assert product == "mona_l03"


def test_load_new_car_with_mona_product():
    pack = load_scenario("new_car", product_id="mona_l03")
    assert pack.scenario_id == "new_car"
    assert pack.product_id == "mona_l03"
    assert pack.product.brand == "小鹏"
    assert pack.product.series == "Mona L03"
    assert "小鹏Mona L03" in pack.keywords
    assert pack.skill_version.startswith("content_sentiment_new_car")


def test_legacy_scenario_loads_as_new_car_mona():
    pack = load_scenario("mona_l03_new_car")
    assert pack.scenario_id == "new_car"
    assert pack.product_id == "mona_l03"
    assert pack.product.series == "Mona L03"


def test_list_products():
    assert "mona_l03" in list_products("new_car")


def test_dry_run_pipeline():
    scenario = load_scenario("new_car", product_id="mona_l03")
    crawl = crawl_from_fixture(scenario, run_id="test_fixture_run")
    assert crawl.post_count == 2
    assert crawl.posts[0].body_complete is True
    assert crawl.posts[0].author_nickname

    client = build_llm_client(provider="fake", model="fake")
    judge = run_judge(
        scenario,
        posts=crawl.posts,
        llm_client=client,
        run_id="test_judge_run",
        provider="fake",
    )
    assert judge.count == 2
    assert judge.judgements_path.exists()

    queue = build_review_queue(
        judgements_path=judge.judgements_path,
        run_id="test_judge_run",
    )
    assert queue.total == 2
    assert queue.queue_path.exists()


def test_seed_eval_with_fake():
    scenario = load_scenario("new_car", product_id="mona_l03")
    client = build_llm_client(provider="fake", model="fake")
    report = run_eval(
        scenario,
        eval_path=scenario.root / "seed_eval.jsonl",
        llm_client=client,
        provider="fake",
    )
    assert report.total == 7
    assert report.polarity_accuracy is not None
    assert report.polarity_accuracy >= 0.6
    assert report.report_path.exists()

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency). Does not override existing env."""
    from csl_lab.paths import LAB_ROOT

    for name in (".env.local", ".env"):
        path = LAB_ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def _add_scenario_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scenario",
        default="new_car",
        help="scenario pack id (default: new_car). legacy: mona_l03_new_car",
    )
    parser.add_argument(
        "--product",
        default=None,
        help="product case under scenarios/{scenario}/products/ (e.g. mona_l03)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="csl-lab")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="crawl XHS notes for a scenario/product")
    _add_scenario_args(crawl)
    crawl.add_argument(
        "--fixture",
        action="store_true",
        help="use offline fixture (no TikHub)",
    )
    crawl.add_argument("--fixture-path", default=None)
    crawl.add_argument("--run-id", default=None)
    crawl.add_argument(
        "--keywords",
        default=None,
        help="comma-separated keyword override",
    )

    judge = sub.add_parser("judge", help="run sentiment judge on a posts jsonl")
    _add_scenario_args(judge)
    judge.add_argument("--posts", required=True, help="path to posts jsonl")
    judge.add_argument("--run-id", default=None)
    judge.add_argument(
        "--provider",
        default=None,
        help="fake|deepseek (default CSL_LLM_PROVIDER)",
    )

    review = sub.add_parser("review-queue", help="build AI review queue from judgements")
    review.add_argument("--judgements", required=True)
    review.add_argument("--run-id", default=None)

    dry = sub.add_parser(
        "dry-run",
        help="fixture crawl + fake judge + review queue (offline demo)",
    )
    _add_scenario_args(dry)

    ev = sub.add_parser("eval", help="evaluate against seed_eval or gold jsonl")
    _add_scenario_args(ev)
    ev.add_argument(
        "--eval-file",
        default=None,
        help="default: scenarios/{id}/seed_eval.jsonl",
    )
    ev.add_argument("--provider", default=None)

    products = sub.add_parser("list-products", help="list product cases for a scenario")
    products.add_argument("--scenario", default="new_car")

    return parser


def _llm_from_args(args: argparse.Namespace) -> tuple[Any, str]:
    from csl_lab.judge import build_llm_client

    provider = args.provider or os.getenv("CSL_LLM_PROVIDER", "fake")
    model = os.getenv("CSL_LLM_MODEL", "deepseek-v4-pro")
    client = build_llm_client(
        provider=provider,
        model=model,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        temperature=float(os.getenv("CSL_LLM_TEMPERATURE", "0") or 0),
    )
    return client, provider


def _load_pack(args: argparse.Namespace):
    from csl_lab.paths import load_scenario

    product = getattr(args, "product", None)
    return load_scenario(args.scenario, product_id=product)


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list-products":
        from csl_lab.paths import list_products, resolve_scenario_ref

        scenario_id, _ = resolve_scenario_ref(args.scenario, None)
        items = list_products(scenario_id)
        print(f"scenario={scenario_id} products={items or '(none)'}")
        return 0

    if args.command == "crawl":
        scenario = _load_pack(args)
        if not args.fixture and not scenario.keywords and not args.keywords:
            raise SystemExit(
                "crawl needs keywords: pass --product <id> "
                "(e.g. mona_l03) or --keywords '...'"
            )
        if args.fixture:
            from csl_lab.crawl import crawl_from_fixture

            result = crawl_from_fixture(
                scenario,
                fixture_path=Path(args.fixture_path) if args.fixture_path else None,
                run_id=args.run_id,
            )
        else:
            from csl_lab.crawl import crawl_scenario
            from csl_lab.crawl.tikhub_client import TikHubClient

            token = os.getenv("TIKHUB_API_TOKEN", "")
            client = TikHubClient(
                token=token,
                base_url=os.getenv("TIKHUB_BASE_URL", "https://api.tikhub.io"),
                rpm=int(os.getenv("TIKHUB_RPM", "20") or 20),
            )
            keywords = (
                [k.strip() for k in args.keywords.split(",") if k.strip()]
                if args.keywords
                else None
            )
            try:
                result = crawl_scenario(
                    scenario,
                    client=client,
                    run_id=args.run_id,
                    keywords=keywords,
                )
            finally:
                client.close()
        print(
            "crawl completed "
            f"label={scenario.run_label} "
            f"run_id={result.run_id} posts={result.post_count} "
            f"detail_ok={result.detail_ok} detail_failed={result.detail_failed} "
            f"path={result.posts_path}"
        )
        return 0

    if args.command == "judge":
        scenario = _load_pack(args)
        from csl_lab.judge import load_posts, run_judge

        posts = load_posts(Path(args.posts))
        client, provider = _llm_from_args(args)
        result = run_judge(
            scenario,
            posts=posts,
            llm_client=client,
            run_id=args.run_id,
            provider=provider,
        )
        print(
            "judge completed "
            f"label={scenario.run_label} "
            f"run_id={result.run_id} count={result.count} "
            f"provider={result.provider} path={result.judgements_path}"
        )
        return 0

    if args.command == "review-queue":
        from csl_lab.review.ai_review import build_review_queue

        result = build_review_queue(
            judgements_path=Path(args.judgements),
            run_id=args.run_id,
        )
        print(
            "review-queue completed "
            f"run_id={result.run_id} flagged={result.flagged}/{result.total} "
            f"path={result.queue_path}"
        )
        return 0

    if args.command == "dry-run":
        # 默认用 mona 案例演示；可 --product 换车型
        if getattr(args, "product", None) is None and args.scenario == "new_car":
            args.product = "mona_l03"
        scenario = _load_pack(args)
        from csl_lab.crawl import crawl_from_fixture
        from csl_lab.judge import build_llm_client, run_judge
        from csl_lab.review.ai_review import build_review_queue

        crawl = crawl_from_fixture(scenario)
        client = build_llm_client(provider="fake", model="fake-sentiment-model")
        judge = run_judge(
            scenario,
            posts=crawl.posts,
            llm_client=client,
            run_id=f"dry_{crawl.run_id}",
            provider="fake",
        )
        queue = build_review_queue(
            judgements_path=judge.judgements_path,
            run_id=judge.run_id,
        )
        print(
            "dry-run completed "
            f"label={scenario.run_label} "
            f"posts={crawl.post_count} judgements={judge.count} "
            f"flagged={queue.flagged} "
            f"posts_path={crawl.posts_path} "
            f"judgements_path={judge.judgements_path} "
            f"queue_path={queue.queue_path}"
        )
        return 0

    if args.command == "eval":
        scenario = _load_pack(args)
        from csl_lab.eval import run_eval

        eval_file = (
            Path(args.eval_file)
            if args.eval_file
            else scenario.root / "seed_eval.jsonl"
        )
        client, provider = _llm_from_args(args)
        report = run_eval(
            scenario,
            eval_path=eval_file,
            llm_client=client,
            provider=provider,
        )
        print(
            "eval completed "
            f"label={scenario.run_label} "
            f"total={report.total} "
            f"polarity_accuracy={report.polarity_accuracy} "
            f"role_accuracy={report.role_accuracy} "
            f"risk_accuracy={report.risk_accuracy} "
            f"report={report.report_path}"
        )
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

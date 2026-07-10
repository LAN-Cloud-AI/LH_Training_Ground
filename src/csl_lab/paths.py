from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


LAB_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = LAB_ROOT / "scenarios"
DATA_DIR = LAB_ROOT / "data"
GOLD_DIR = LAB_ROOT / "gold"
FIXTURES_DIR = LAB_ROOT / "fixtures"

# 旧场景 ID → (新场景, 产品案例)
LEGACY_SCENARIO_ALIASES: dict[str, tuple[str, str]] = {
    "mona_l03_new_car": ("new_car", "mona_l03"),
}


class CrawlConfig(BaseModel):
    max_search_pages_per_keyword: int = 2
    max_note_detail_per_run: int = 40
    require_note_detail: bool = True
    keep_incomplete_body: bool = True


class ProductConfig(BaseModel):
    brand: str = ""
    series: str = ""
    aliases: list[str] = Field(default_factory=list)


class CompetitorConfig(BaseModel):
    brand: str
    series: str | None = None


class ScenarioPack(BaseModel):
    scenario_id: str
    platform: str = "xiaohongshu"
    skill_version: str
    display_name: str | None = None
    product: ProductConfig = Field(default_factory=ProductConfig)
    product_id: str | None = None
    competitors: list[CompetitorConfig] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    aspects: list[str] = Field(default_factory=list)
    root: Path
    skill_md: str
    output_schema: dict[str, Any]

    @property
    def run_label(self) -> str:
        if self.product_id:
            return f"{self.scenario_id}:{self.product_id}"
        return self.scenario_id


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_scenario_ref(
    scenario_id: str, product_id: str | None = None
) -> tuple[str, str | None]:
    """Map legacy IDs; allow --scenario new_car --product mona_l03."""
    if scenario_id in LEGACY_SCENARIO_ALIASES:
        base, prod = LEGACY_SCENARIO_ALIASES[scenario_id]
        return base, product_id or prod
    return scenario_id, product_id


def normalize_scenario_id(raw: str) -> str:
    """把用户输入规范成场景目录名（小写 slug）。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("scenario_id 不能为空")
    if re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z_\-]{0,63}", text):
        return text.lower()
    import hashlib

    ascii_part = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()
    ascii_part = re.sub(r"_+", "_", ascii_part)
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    if ascii_part and len(ascii_part) >= 2:
        slug = f"{ascii_part}_{digest}"
    else:
        slug = f"s_{digest}"
    return slug[:64].rstrip("_-")


def list_scenarios(*, include_legacy: bool = False) -> list[str]:
    """扫描 scenarios/*/scenario.yaml；默认跳过遗留别名目录。"""
    if not SCENARIOS_DIR.is_dir():
        return []
    out: list[str] = []
    for path in sorted(SCENARIOS_DIR.iterdir()):
        if not path.is_dir():
            continue
        if not include_legacy and path.name in LEGACY_SCENARIO_ALIASES:
            continue
        if (path / "scenario.yaml").is_file():
            out.append(path.name)
    return out


def get_scenario_meta(scenario_id: str) -> dict[str, Any]:
    scenario_id, _ = resolve_scenario_ref(scenario_id, None)
    root = SCENARIOS_DIR / scenario_id
    yaml_path = root / "scenario.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(f"scenario not found: {root}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    display = raw.get("display_name") or scenario_id
    return {
        "scenario_id": raw.get("scenario_id") or scenario_id,
        "display_name": display,
        "skill_version": raw.get("skill_version"),
        "platform": raw.get("platform", "xiaohongshu"),
        "path": str(root),
    }


def list_scenario_metas(*, include_legacy: bool = False) -> list[dict[str, Any]]:
    metas: list[dict[str, Any]] = []
    for sid in list_scenarios(include_legacy=include_legacy):
        try:
            metas.append(get_scenario_meta(sid))
        except (OSError, ValueError, FileNotFoundError):
            continue
    return metas


_DEFAULT_ASPECTS = [
    "exterior",
    "driving",
    "range",
    "smart_drive",
    "price",
    "delivery",
    "service",
    "quality",
    "space",
    "competitor",
]


def ensure_scenario(
    scenario_id: str,
    *,
    display_name: str | None = None,
    create_if_missing: bool = True,
) -> str:
    """确保 scenarios/{id}/ 存在；不存在则创建最小骨架，返回规范化 scenario_id。"""
    raw_input = (scenario_id or "").strip()
    sid = normalize_scenario_id(raw_input)
    # 中文展示名：若输入非 slug，优先用作 display_name
    label = (display_name or "").strip()
    if not label and raw_input and raw_input != sid:
        label = raw_input
    if not label:
        label = sid

    root = SCENARIOS_DIR / sid
    yaml_path = root / "scenario.yaml"
    if yaml_path.is_file():
        return sid
    if not create_if_missing:
        raise FileNotFoundError(
            f"scenario not found: {root}. available={list_scenarios()}"
        )

    import json
    import shutil

    root.mkdir(parents=True, exist_ok=True)
    (root / "products").mkdir(parents=True, exist_ok=True)

    skill_version = f"content_sentiment_{sid}_v0.1"
    payload = {
        "scenario_id": sid,
        "display_name": label,
        "platform": "xiaohongshu",
        "skill_version": skill_version,
        "product": {"brand": "", "series": "", "aliases": []},
        "competitors": [],
        "keywords": [],
        "crawl": {
            "max_search_pages_per_keyword": 2,
            "max_note_detail_per_run": 40,
            "require_note_detail": True,
            "keep_incomplete_body": True,
        },
        "aspects": list(_DEFAULT_ASPECTS),
    }
    yaml_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    skill_path = root / "skill.md"
    if not skill_path.is_file():
        skill_path.write_text(
            (
                f"# {skill_version}\n\n"
                f"你是「小红书帖子情感评分器」，当前行业场景为：**{label}**（`{sid}`）。\n\n"
                "## 任务边界\n\n"
                "- 只根据单条帖子（标题、正文、昵称、城市、互动量）判断。\n"
                "- 不编造未出现的事实；只输出 JSON array，顺序与输入一致。\n"
                "- 下游会映射为销售线索「有意向/没意向」；请先把 `content_role` 判准。\n\n"
                "## 角色原则（请按本行业改写）\n\n"
                "- `prospect_research`：仍在求购、未成交的潜客。\n"
                "- `owner_review`：已成交/已提车/用后复盘。\n"
                "- `dealer_ad`：经销商/营销种草。\n"
                "- `media` / `unrelated` / `unknown`：按证据使用。\n\n"
                "## 输出要求\n\n"
                "- 必须返回 schema 中每一个 required 字段；`inferred_city` 可为 string 或 null。\n"
                "- 输入已有 `city` 时 `inferred_city` 必须为 null。\n"
            ),
            encoding="utf-8",
        )

    schema_path = root / "schema.json"
    if not schema_path.is_file():
        template = SCENARIOS_DIR / "new_car" / "schema.json"
        if template.is_file():
            shutil.copyfile(template, schema_path)
            # 轻量改 title，避免误导
            try:
                data = json.loads(schema_path.read_text(encoding="utf-8"))
                data["title"] = f"ContentSentimentResult_{sid}"
                schema_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except (OSError, ValueError, TypeError):
                pass
        else:
            schema_path.write_text("{}\n", encoding="utf-8")

    return sid


def list_products(scenario_id: str) -> list[str]:
    products_dir = SCENARIOS_DIR / scenario_id / "products"
    if not products_dir.is_dir():
        return []
    return sorted(p.stem for p in products_dir.glob("*.yaml"))


def normalize_product_id(raw: str) -> str:
    """把用户输入规范成可用的产品文件名（小写 slug）。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("product_id 不能为空")
    # 已是合法 slug：直接小写
    if re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z_\-]{0,63}", text):
        return text.lower()

    import hashlib

    ascii_part = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()
    ascii_part = re.sub(r"_+", "_", ascii_part)
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    if ascii_part and len(ascii_part) >= 2:
        slug = f"{ascii_part}_{digest}"
    else:
        slug = f"p_{digest}"
    return slug[:64].rstrip("_-")


def _infer_brand_series(
    product_id: str, *, display_name: str | None = None
) -> tuple[str, str]:
    label = (display_name or product_id).strip() or product_id
    # 中文/展示名：尽量拆成「品牌 + 车系」
    if not re.fullmatch(r"[0-9A-Za-z_\-]+", label):
        m = re.match(r"^([\u4e00-\u9fff]+)(.+)$", label)
        if m:
            brand = m.group(1).strip()
            series = m.group(2).strip() or label
            return brand, series
        return label, label

    parts = [p for p in product_id.split("_") if p]
    if len(parts) >= 2:
        # 去掉末尾 hash 段（8 位 hex）
        if re.fullmatch(r"[0-9a-f]{8}", parts[-1]):
            parts = parts[:-1]
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:])
        if parts:
            return parts[0], parts[0]
    return product_id, product_id


def ensure_product(
    scenario_id: str,
    product_id: str,
    *,
    keyword: str | None = None,
    brand: str | None = None,
    series: str | None = None,
    create_if_missing: bool = True,
) -> str:
    """确保 products/{id}.yaml 存在；不存在则按输入自动新建，返回规范化 product_id。"""
    scenario_id, _ = resolve_scenario_ref(scenario_id, None)
    raw_input = (product_id or "").strip()
    pid = normalize_product_id(raw_input)
    root = SCENARIOS_DIR / scenario_id
    products_dir = root / "products"
    products_dir.mkdir(parents=True, exist_ok=True)
    path = products_dir / f"{pid}.yaml"
    if path.is_file():
        return pid
    if not create_if_missing:
        available = list_products(scenario_id)
        raise FileNotFoundError(f"product not found: {path}. available={available}")

    inferred_brand, inferred_series = _infer_brand_series(
        pid, display_name=raw_input if raw_input != pid else None
    )
    brand_v = (brand or "").strip() or inferred_brand
    series_v = (series or "").strip() or inferred_series
    kw = (keyword or "").strip()
    aliases = [series_v, brand_v, f"{brand_v}{series_v}", f"{brand_v} {series_v}", pid]
    if raw_input and raw_input not in aliases:
        aliases.insert(0, raw_input)
    if kw and kw not in aliases:
        aliases.append(kw)
    # 去重保序
    aliases = list(dict.fromkeys(a.strip() for a in aliases if a and str(a).strip()))
    keywords = [kw] if kw else [series_v, f"{brand_v} {series_v}", pid]
    keywords = list(dict.fromkeys(k.strip() for k in keywords if k and str(k).strip()))

    payload = {
        "product_id": pid,
        "product": {
            "brand": brand_v,
            "series": series_v,
            "aliases": aliases,
        },
        "competitors": [],
        "keywords": keywords,
    }
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return pid


def _load_product_overlay(scenario_root: Path, product_id: str) -> dict[str, Any]:
    path = scenario_root / "products" / f"{product_id}.yaml"
    if not path.is_file():
        available = list_products(scenario_root.name)
        raise FileNotFoundError(
            f"product not found: {path}. available={available}"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw


def load_scenario(
    scenario_id: str,
    *,
    product_id: str | None = None,
    ensure_product_exists: bool = False,
    keyword: str | None = None,
) -> ScenarioPack:
    scenario_id, product_id = resolve_scenario_ref(scenario_id, product_id)
    root = SCENARIOS_DIR / scenario_id
    if not root.is_dir():
        raise FileNotFoundError(f"scenario not found: {root}")

    if product_id and ensure_product_exists:
        product_id = ensure_product(scenario_id, product_id, keyword=keyword)

    raw = yaml.safe_load((root / "scenario.yaml").read_text(encoding="utf-8")) or {}
    skill_md = (root / "skill.md").read_text(encoding="utf-8")
    import json

    schema = json.loads((root / "schema.json").read_text(encoding="utf-8"))

    product = ProductConfig(**(raw.get("product") or {}))
    competitors = [CompetitorConfig(**c) for c in raw.get("competitors") or []]
    keywords = list(raw.get("keywords") or [])
    crawl = CrawlConfig(**(raw.get("crawl") or {}))

    if product_id:
        overlay = _load_product_overlay(root, product_id)
        if overlay.get("product"):
            product = ProductConfig(**overlay["product"])
        if overlay.get("competitors") is not None:
            competitors = [
                CompetitorConfig(**c) for c in overlay.get("competitors") or []
            ]
        if overlay.get("keywords") is not None:
            keywords = list(overlay.get("keywords") or [])
        if overlay.get("crawl"):
            crawl = CrawlConfig(**{**crawl.model_dump(), **overlay["crawl"]})

    if product_id and not product.brand:
        raise ValueError(f"product overlay missing brand/series: {product_id}")

    return ScenarioPack(
        scenario_id=raw.get("scenario_id") or scenario_id,
        platform=raw.get("platform", "xiaohongshu"),
        skill_version=raw["skill_version"],
        display_name=raw.get("display_name") or scenario_id,
        product=product,
        product_id=product_id,
        competitors=competitors,
        keywords=keywords,
        crawl=crawl,
        aspects=list(raw.get("aspects") or []),
        root=root,
        skill_md=skill_md,
        output_schema=schema,
    )


def ensure_data_dirs() -> None:
    for sub in ("posts", "judgements", "review_queue", "crawl_logs", "eval_reports"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)

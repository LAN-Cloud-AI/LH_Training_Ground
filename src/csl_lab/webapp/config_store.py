from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from csl_lab.paths import LAB_ROOT

CONFIG_PATH = LAB_ROOT / "data" / "webapp" / "runtime_config.json"

DEEPSEEK_MODELS = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-chat",
    "deepseek-reasoner",
]


def _mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}"


def load_config() -> dict[str, Any]:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    # fallback to env / lab .env values if empty
    if not data.get("tikhub_api_token"):
        data["tikhub_api_token"] = os.getenv("TIKHUB_API_TOKEN", "")
    if not data.get("deepseek_api_key"):
        data["deepseek_api_key"] = os.getenv("DEEPSEEK_API_KEY", "")
    if not data.get("deepseek_model"):
        data["deepseek_model"] = os.getenv("CSL_LLM_MODEL") or os.getenv(
            "LH_LLM_MODEL", "deepseek-v4-flash"
        )
    if not data.get("deepseek_base_url"):
        data["deepseek_base_url"] = os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        )
    if not data.get("tikhub_base_url"):
        data["tikhub_base_url"] = os.getenv("TIKHUB_BASE_URL", "https://api.tikhub.io")
    data.setdefault("tikhub_rpm", int(os.getenv("TIKHUB_RPM", "30") or 30))
    return data


def save_config(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_config()
    for key in (
        "tikhub_api_token",
        "tikhub_base_url",
        "tikhub_rpm",
        "deepseek_api_key",
        "deepseek_model",
        "deepseek_base_url",
    ):
        if key in patch and patch[key] is not None:
            # 空字符串表示清空；带 … 的掩码不覆盖
            val = patch[key]
            if isinstance(val, str) and "…" in val:
                continue
            current[key] = val
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # sync into process env for crawl/judge helpers
    if current.get("tikhub_api_token"):
        os.environ["TIKHUB_API_TOKEN"] = str(current["tikhub_api_token"])
    if current.get("deepseek_api_key"):
        os.environ["DEEPSEEK_API_KEY"] = str(current["deepseek_api_key"])
    if current.get("deepseek_model"):
        os.environ["CSL_LLM_MODEL"] = str(current["deepseek_model"])
    return current


def public_config() -> dict[str, Any]:
    cfg = load_config()
    return {
        "tikhub_api_token_set": bool(cfg.get("tikhub_api_token")),
        "tikhub_api_token_masked": _mask(cfg.get("tikhub_api_token") or ""),
        "tikhub_base_url": cfg.get("tikhub_base_url"),
        "tikhub_rpm": cfg.get("tikhub_rpm", 30),
        "deepseek_api_key_set": bool(cfg.get("deepseek_api_key")),
        "deepseek_api_key_masked": _mask(cfg.get("deepseek_api_key") or ""),
        "deepseek_model": cfg.get("deepseek_model"),
        "deepseek_base_url": cfg.get("deepseek_base_url"),
        "deepseek_models": DEEPSEEK_MODELS,
    }

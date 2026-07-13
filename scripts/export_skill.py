#!/usr/bin/env python3
"""导出训练场某场景 skill，生成可供生产 Agent 导入的 manifest。

用法：
    python scripts/export_skill.py <scenario_id> \
        [--target post] [--intent-module new_car] [--out data/skill_exports/<id>.json]

manifest 内容（JSON）供生产 Agent 的 scripts/import_skill.py 消费：
    scenario_id / skill_version / scoring_target / platform / intent_module /
    skill_md_path / schema_path / display_name

该脚本只读训练场文件，不改动生产 Agent。生产接入由 Agent 侧 import_skill.py 完成。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 训练场环境应已安装 pyyaml
    print("需要 pyyaml：pip install pyyaml 或在训练场虚拟环境内运行", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"


def build_manifest(
    scenario_id: str,
    *,
    scoring_target: str = "post",
    intent_module: str | None = None,
) -> dict:
    root = SCENARIOS_DIR / scenario_id
    scenario_yaml = root / "scenario.yaml"
    skill_md = root / "skill.md"
    schema_json = root / "schema.json"

    if not scenario_yaml.is_file():
        raise SystemExit(f"scenario not found: {scenario_yaml}")
    if not skill_md.is_file():
        raise SystemExit(f"skill.md missing: {skill_md}")
    if not schema_json.is_file():
        raise SystemExit(f"schema.json missing: {schema_json}")

    meta = yaml.safe_load(scenario_yaml.read_text(encoding="utf-8")) or {}
    skill_version = meta.get("skill_version")
    if not skill_version:
        raise SystemExit(f"scenario.yaml missing skill_version: {scenario_yaml}")

    # 校验 schema.json 可解析
    json.loads(schema_json.read_text(encoding="utf-8"))

    return {
        "scenario_id": meta.get("scenario_id") or scenario_id,
        "display_name": meta.get("display_name") or scenario_id,
        "skill_version": skill_version,
        "scoring_target": scoring_target,
        "platform": meta.get("platform"),
        "intent_module": intent_module or scenario_id,
        "skill_md_path": str(skill_md),
        "schema_path": str(schema_json),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a training-ground skill manifest")
    parser.add_argument("scenario_id")
    parser.add_argument("--target", default="post", choices=["post", "comment"])
    parser.add_argument("--intent-module", default=None)
    parser.add_argument("--out", default=None, help="写入 manifest 的路径；缺省仅打印")
    args = parser.parse_args(argv)

    manifest = build_manifest(
        args.scenario_id,
        scoring_target=args.target,
        intent_module=args.intent_module,
    )
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"exported manifest -> {out_path}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

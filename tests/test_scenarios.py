from pathlib import Path

from csl_lab.paths import (
    SCENARIOS_DIR,
    ensure_scenario,
    get_scenario_meta,
    list_scenarios,
    load_scenario,
)


def test_list_scenarios_includes_new_and_used_car():
    ids = list_scenarios()
    assert "new_car" in ids
    assert "used_car" in ids
    assert "mona_l03_new_car" not in ids


def test_get_scenario_meta_display_name():
    meta = get_scenario_meta("new_car")
    assert meta["scenario_id"] == "new_car"
    assert meta["display_name"] == "新车"
    used = get_scenario_meta("used_car")
    assert used["display_name"] == "二手车"


def test_ensure_scenario_creates_skeleton(tmp_path, monkeypatch):
    # 指向临时 scenarios 根，避免污染仓库
    fake_root = tmp_path / "scenarios"
    fake_root.mkdir()
    # 提供 new_car schema 模板供复制
    template = fake_root / "new_car"
    template.mkdir()
    (template / "scenario.yaml").write_text(
        "scenario_id: new_car\ndisplay_name: 新车\nskill_version: t\n",
        encoding="utf-8",
    )
    (template / "schema.json").write_text(
        '{"title": "ContentSentimentResult_NewCar", "type": "object"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("csl_lab.paths.SCENARIOS_DIR", fake_root)

    sid = ensure_scenario("动力电池", display_name="动力电池")
    root = fake_root / sid
    assert root.is_dir()
    assert (root / "scenario.yaml").is_file()
    assert (root / "skill.md").is_file()
    assert (root / "schema.json").is_file()
    assert (root / "products").is_dir()
    # 再次 ensure 幂等
    assert ensure_scenario(sid) == sid


def test_load_used_car_scenario():
    pack = load_scenario("used_car")
    assert pack.scenario_id == "used_car"
    assert pack.display_name == "二手车"
    assert "二手" in pack.skill_md or "used" in pack.skill_version
    assert Path(pack.root).name == "used_car"

from csl_lab.webapp.intent import INTENT_NO, INTENT_YES, map_agent_intent


def _map(title: str, body: str, role: str, polarity: str = "positive", scenario_id: str = "new_car"):
    return map_agent_intent(
        {"content_role": role, "sentiment_polarity": polarity, "reason": ""},
        title=title,
        body=body,
        scenario_id=scenario_id,
    )


def test_delivery_posts_are_no_intent():
    cases = [
        ("成都零跑A10提车啦", "6.18订车 比原计划提早提车，有哪些必买的车载好物啊", "owner_review"),
        ("盲订了零跑A10-观望了4年，一直没下手……", "盲订了，价格如果太高就退了……等待中", "prospect_research"),
        ("喜提零跑A10！顺利把新车开回家啦🥳", "终于提车了！从试驾到下定再到提车", "owner_review"),
        ("零跑A10提车记", "蹲了半年的零跑A10，今天终于提车了！", "owner_review"),
        (
            "寻找南宁零跑销售",
            "想买零跑a10。后续：本周已经订车，感谢某某店销售",
            "owner_review",
        ),
        (
            "零跑A10价格太惊喜，直接心动下单",
            "预算10万，到店后立马就找销售定下来了，期待早日提车",
            "prospect_research",
        ),
    ]
    for title, body, role in cases:
        intent, _ = _map(title, body, role)
        assert intent == INTENT_NO, (title, intent)


def test_marketing_seed_is_no_intent():
    title = "试驾奥迪A4L，纠结还值不值得冲？"
    body = (
        "先说结论：奥迪A4L直降10万。给想买车的朋友提供建议。"
        + ("参数和优缺点总结。" * 20)
    )
    intent, _ = _map(title, body, "prospect_research", polarity="neutral")
    assert intent == INTENT_NO


def test_used_car_and_post_purchase_are_no_intent():
    cases = [
        ("", "真心求够一辆22年帕萨特330豪华\n价格合适直接提", "prospect_research"),
        (
            "个人求购22年及之后的帕萨特330",
            "真实个人求购，车商收购价适当加点",
            "prospect_research",
        ),
        (
            "大家的Q05多钱落地买的，看看我的买亏了吗#启源Q05",
            "大家的Q05多钱落地买的，看看我的买亏了吗",
            "prospect_research",
        ),
        (
            "纠结元UP活力版能不能买？5月新车主实测",
            "作为5月刚提真实车主，不恰饭、不吹不黑",
            "owner_review",
        ),
        (
            "买BYD元UP只花了20分钟 | 给爸整个老头乐",
            "老豆打算增购一部电车，让我去办",
            "prospect_research",
        ),
        (
            "加州湾区Camry 2026 Nightshade OTD",
            "2026丰田凯美瑞 SE Nightshade，在湾区 dealers",
            "prospect_research",
        ),
    ]
    for title, body, role in cases:
        intent, _ = _map(title, body, role, polarity="neutral")
        assert intent == INTENT_NO, (title, intent)


def test_active_buyer_still_yes():
    intent, _ = _map(
        "蹲一个广州小鹏销售",
        "准备买L03，来个靠谱销售私我，还没订",
        "prospect_research",
    )
    assert intent == INTENT_YES


def test_same_samples_flip_between_new_car_and_used_car():
    """同一样例在新车/二手车场景下意向应相反（典型边界）。"""
    used_title = "个人求购22年及之后的帕萨特330"
    used_body = "真实个人求购，车商收购价适当加点，价格合适直接提"
    new_title = "蹲一个广州小鹏销售"
    new_body = "准备买L03，来个靠谱销售私我，还没订"

    used_as_new, _ = _map(used_title, used_body, "prospect_research", scenario_id="new_car")
    used_as_used, _ = _map(used_title, used_body, "prospect_research", scenario_id="used_car")
    assert used_as_new == INTENT_NO
    assert used_as_used == INTENT_YES

    new_as_new, _ = _map(new_title, new_body, "prospect_research", scenario_id="new_car")
    new_as_used, _ = _map(new_title, new_body, "prospect_research", scenario_id="used_car")
    assert new_as_new == INTENT_YES
    assert new_as_used == INTENT_NO


def test_unknown_scenario_is_conservative():
    intent, _ = _map(
        "随便看看",
        "今天天气不错",
        "unknown",
        scenario_id="ev_battery",
    )
    assert intent == INTENT_NO

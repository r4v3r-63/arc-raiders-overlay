from arc_overlay import items
from arc_overlay.progress import shopping_list
from arc_overlay.quest_db import QuestDB


def db():
    return QuestDB.load()


def test_match_item_prefers_tooltip_title_near_cursor():
    base = db()
    lines = [
        ("ПРОВОДА", 500, 300, 120, 30),  # заголовок подсказки — крупный
        ("Разбирается на: Резиновые детали", 500, 340, 300, 16),
        ("Резиновые детали", 900, 900, 160, 16),
        ("Металлические детали", 1500, 100, 200, 30),  # такой же крупный, но далеко от курсора
    ]
    assert items.match_item(base, lines, (480, 320)).id == "wires"
    assert items.match_item(base, [("Провода", 0, 0, 10, 10)], (0, 0)).id == "wires"
    assert items.match_item(base, [("Wires", 0, 0, 10, 10)], (0, 0)).id == "wires"
    typo = items.match_item(base, [("Металлические детапи", 0, 0, 10, 10)], (0, 0))  # опечатка распознавания
    assert typo is not None and typo.name == "Металлические детали"
    assert items.match_item(base, [("Инвентарь", 0, 0, 10, 10)], (0, 0)) is None


def test_item_report_for_quest_and_workshops():
    base = db()
    quest = base.find_by_id("a_dead_end")
    reel = next(i for i in base.items.values() if i.name == "Пыльная катушка с пленкой")
    report = items.item_report(base, reel, [quest], [], {})
    assert report.keep and report.quests == [(quest.name, 1)]
    report = items.item_report(base, reel, [], [], {})
    assert not report.keep and quest.name in report.later_quests
    report = items.item_report(base, reel, [], [quest.id], {})
    assert quest.name not in report.later_quests

    cable = base.items["power_cable"]
    report = items.item_report(base, cable, [], [], {"equipment_bench": 1})
    assert ("Верстак для снаряжения", 2, 3) in report.workshops and report.keep
    report = items.item_report(base, cable, [], [], {"equipment_bench": 3})
    assert all(w[0] != "Верстак для снаряжения" for w in report.workshops + report.later_workshops)
    report = items.item_report(base, base.items["wires"], [], [], {})
    assert report.recycles == [("Резиновые детали", 2)]


def test_item_with_no_use_can_be_sold():
    base = db()
    guitar = base.items["acoustic_guitar"]
    report = items.item_report(base, guitar, [], [q.id for q in base.quests], {w.id: w.max_level for w in base.workshops})
    assert report.verdict == "Можно продать или разобрать" and guitar.value > 0


def test_shopping_includes_next_workshop_level():
    base = db()
    extra = items.workshop_shopping(base, {"equipment_bench": 1, "scrappy": 5})
    assert ("Кабель питания", 3, "Верстак для снаряжения → ур. 2") in extra
    rows = shopping_list([base.find_by_id("a_dead_end")], extra)
    purposes = [p for _, _, ps in rows for p in ps]
    assert "Верстак для снаряжения → ур. 2" in purposes and base.find_by_id("a_dead_end").name in purposes
    assert not any("Плюшкин" in p for p in purposes)  # максимальный уровень — улучшать нечего


def test_where_to_find_ranks_maps_by_matching_spots():
    base = db()
    where = items.where_to_find(base, base.items["water_pump"])
    assert where.types == ["механические (Mechanical)", "промышленные (Industrial)"]
    counts = [len(m.rooms) for m in where.maps]
    assert counts == sorted(counts, reverse=True) and counts[0] > 0
    assert all({"Mechanical", "Industrial"} & set(r["types"]) for m in where.maps for r in m.rooms)
    assert "Акустическая гитара" in items.where_to_find(base, base.items["wires"]).sources


def test_item_search_by_name():
    base = db()
    assert base.find_item("водяной насос").id == "water_pump"
    assert base.find_item("Water Pump").id == "water_pump"
    assert base.find_item("насос") is None  # насосов несколько
    assert "Водяной насос" in base.similar_items("мини- насос")
    assert base.suggest_items("вод")[0].lower().startswith("вод")


def test_craft_vendors_and_blueprints():
    base = db()
    anvil = base.items["anvil_i"]
    report = items.item_report(base, anvil, [], [], {})
    assert report.craft and "Оружейный верстак" in report.craft[0]
    assert report.blueprint.startswith("Нужен чертёж") and "изучен" not in report.blueprint
    report = items.item_report(base, anvil, [], [], {}, {"anvil_blueprint"})
    assert report.blueprint.endswith("— изучен")

    mag = base.items["extended_medium_mag_i"]
    assert any("Тянь Вэнь" in v and "монет" in v for v in items.item_report(base, mag, [], [], {}).vendors)

    blueprint = base.items["anvil_blueprint"]
    unknown = items.item_report(base, blueprint, [], [], {})
    assert "Отметьте" in unknown.verdict and not unknown.keep
    other = next(i.id for i in base.items.values() if i.unlocks and i.id != "anvil_blueprint")
    fresh = items.item_report(base, blueprint, [], [], {}, {other})
    assert fresh.keep and "не изучен" in fresh.verdict
    done = items.item_report(base, blueprint, [], [], {}, {"anvil_blueprint"})
    assert not done.keep and "уже изучен" in done.verdict

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

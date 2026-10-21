from arc_overlay.core.quest_db import QuestDB
from arc_overlay.core.recognition import match_quests


def test_matches_quest_lines_and_ignores_other_text():
    db = QuestDB.load()
    lines = [  # примерно так распознаётся лобби: достижения, квесты, интерфейс
        "ДОСТИЖЕНИЯ", "Обыскан доставщик ARC", "0/1", "Уничтожено «Ос»", "0/3",
        "КВЕСТЫ", "Что посеешь, то и пожнешь", "Взяточные запчасти",
        "ИГРАТЬ", "Inventory",
    ]
    names = [q.name for q in match_quests(db, lines)]
    assert "Взяточные запчасти" in names
    assert all(n not in ("ИГРАТЬ", "КВЕСТЫ") for n in names)


def test_tolerates_ocr_typos_and_english():
    db = QuestDB.load()
    found = match_quests(db, ["Чистое нeбо", "Greasing Her Palms", "What Goes Around"])
    names = [q.english_name for q in found]
    assert names[:1] == ["Clearer Skies"]
    assert "Greasing Her Palms" in names and "What Goes Around" in names


def test_no_duplicates_and_short_lines_skipped():
    db = QuestDB.load()
    assert len(match_quests(db, ["Чистое небо", "чистое небо", "ok", ""])) == 1


def test_short_names_need_exact_match():
    db = QuestDB.load()
    short = next(q for q in db.quests if 4 <= len(q.name) < 8)
    assert match_quests(db, [short.name + "ии"]) == []  # «тупики» не превращается в «Тупик»
    assert match_quests(db, [short.name]) == [short]

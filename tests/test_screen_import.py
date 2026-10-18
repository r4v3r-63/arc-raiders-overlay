from arc_overlay.quest_db import QuestDB
from arc_overlay.screen_import import match_quests


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

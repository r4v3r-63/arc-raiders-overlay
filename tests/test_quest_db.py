from arc_overlay.quest_db import GameMap, Quest, QuestDB


def make_db():
    return QuestDB(
        [
            Quest(name="Чистое небо", aliases=["Clearer Skies"], steps=["c"]),
            Quest(name="Уход в тень", aliases=["Off The Radar"], steps=["a", "b"]),
            Quest(name="Тупик", aliases=["A Dead End"], steps=["d"], locations=["the_blue_gate"]),
            Quest(name="Ещё один тупик", aliases=["Another Dead End"], steps=["e"]),
        ],
        [
            GameMap(id="the_blue_gate", name="The Blue Gate", aliases=["синие врата"]),
            GameMap(id="the_spaceport", name="The Spaceport", aliases=["космопорт"]),
        ],
    )


def test_bundled_db_loads():
    db = QuestDB.load()
    assert len(db.quests) >= 50
    assert all(q.steps for q in db.quests)
    assert db.find("Чистое небо").english_name == "Clearer Skies"


def test_russian_name_ignores_case_spaces_and_yo():
    assert make_db().find("  чистое   НЕБО ").name == "Чистое небо"
    assert make_db().find("еще один тупик").name == "Ещё один тупик"


def test_english_name_still_works():
    assert make_db().find("off the radar").name == "Уход в тень"


def test_partial_match():
    assert make_db().find("уход").name == "Уход в тень"


def test_typo_match():
    assert make_db().find("Чистоe нбо").name == "Чистое небо"


def test_no_match():
    assert make_db().find("совсем не квест") is None
    assert make_db().find("") is None


def test_available_at():
    db = make_db()
    dead_end = db.find("Тупик")
    assert db.available_at(dead_end, "Синие врата")
    assert db.available_at(dead_end, "blue gate")
    assert not db.available_at(dead_end, "космопорт")
    assert db.available_at(dead_end, "")
    assert db.available_at(dead_end, "неизвестная карта")
    assert db.available_at(db.find("Чистое небо"), "космопорт")

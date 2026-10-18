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


def test_bundled_db_has_guides_and_links():
    db = QuestDB.load()
    assert len(db.quests) >= 115
    # Новый квест может появиться раньше, чем в руководстве Steam — это не повод блокировать обновление.
    assert sum(1 for q in db.quests if q.steam_url) >= 0.75 * len(db.quests)
    assert sum(1 for q in db.quests if q.guide) >= 50
    assert db.find("В Небеса").english_name == "To The Skies"
    assert db.find_map_exact("Перевал Пендола").id == "pendola_pass"
    assert db.find_map_exact("поле битвы у дамбы").id == "dam_battlegrounds"


def test_bundled_guide_images_exist():
    from arc_overlay.quest_db import DATA_DIR
    db = QuestDB.load()
    for q in db.quests:
        for image in (q.guide or {}).get("images", []):
            assert (DATA_DIR / image["file"]).exists(), image["file"]


def test_suggest_ranks_prefix_first_and_ignores_yo():
    db = QuestDB([
        Quest(name="Небо в огне", steps=[]),
        Quest(name="Чистое небо", aliases=["Clearer Skies"], steps=[]),
        Quest(name="Ещё один тупик", steps=[]),
        Quest(name="Тупик", steps=[]),
    ])
    assert db.suggest("небо") == ["Небо в огне", "Чистое небо"]
    assert db.suggest("clear") == ["Чистое небо"]
    assert db.suggest("еще") == ["Ещё один тупик"]
    assert db.suggest("тупик") == ["Тупик", "Ещё один тупик"]
    assert db.suggest("") == []

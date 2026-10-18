from arc_overlay.quest_db import Quest, QuestDB


def make_db():
    return QuestDB([
        Quest(name="Picking Up The Pieces", steps=["a", "b"], locations=["Any"]),
        Quest(name="Clearer Skies", steps=["c"], locations=["Any"]),
        Quest(name="Marked For Death", steps=["d"], locations=["Buried City"]),
    ])


def test_bundled_db_loads():
    db = QuestDB.load()
    assert len(db.quests) >= 5
    assert all(q.steps for q in db.quests)


def test_exact_match_ignores_case_and_spaces():
    assert make_db().find("  clearer   SKIES ").name == "Clearer Skies"


def test_partial_match():
    assert make_db().find("picking").name == "Picking Up The Pieces"


def test_typo_match():
    assert make_db().find("Clerer Skys").name == "Clearer Skies"


def test_no_match():
    assert make_db().find("совсем не квест") is None
    assert make_db().find("") is None


def test_available_at():
    db = make_db()
    marked = db.find("Marked For Death")
    assert marked.available_at("buried city")
    assert not marked.available_at("Spaceport")
    assert marked.available_at("")
    assert db.find("Clearer Skies").available_at("Spaceport")

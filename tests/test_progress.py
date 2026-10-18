from arc_overlay.progress import Progress
from arc_overlay.quest_db import Quest, QuestDB


def make_db():
    return QuestDB([
        Quest(id="a", name="Первый", steps=["1", "2"], next=["b", "c"]),
        Quest(id="b", name="Второй", steps=["1"]),
        Quest(id="c", name="Третий", steps=["1"], next=["d", "e", "f", "g"]),
        Quest(id="d", name="Д", steps=[]), Quest(id="e", name="Е", steps=[]),
        Quest(id="f", name="Ф", steps=[]), Quest(id="g", name="Г", steps=[]),
    ])


def test_add_switch_and_persist(tmp_path):
    db = make_db()
    path = tmp_path / "прогресс.json"
    p = Progress.load(path)
    p.add(db.find_by_id("a"))
    p.set_step(1)
    p.add(db.find_by_id("b"))
    p.add(db.find_by_id("a"))  # повторно — не дублируется, становится текущим
    assert [e.id for e in p.active] == ["a", "b"] and p.current == 0
    assert p.switch().id == "b"
    assert p.switch().id == "a"
    p.save()
    again = Progress.load(path)
    assert [(e.id, e.step) for e in again.active] == [("a", 1), ("b", 0)]
    assert again.resolve(db, again.current_entry()).name == "Первый"


def test_complete_adds_next_quests(tmp_path):
    db = make_db()
    p = Progress.load(tmp_path / "p.json")
    p.add(db.find_by_id("a"))
    done, added, skipped = p.complete_current(db)
    assert done.id == "a" and [q.id for q in added] == ["b", "c"] and skipped == []
    assert [e.id for e in p.active] == ["b", "c"] and p.completed == ["a"]


def test_complete_with_many_next_does_not_flood_list(tmp_path):
    db = make_db()
    p = Progress.load(tmp_path / "p.json")
    p.add(db.find_by_id("c"))
    done, added, skipped = p.complete_current(db)
    assert added == [] and len(skipped) == 4 and p.active == []


def test_broken_file_starts_clean(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{не json", encoding="utf-8")
    assert Progress.load(path).active == []


def test_remove_current(tmp_path):
    db = make_db()
    p = Progress.load(tmp_path / "p.json")
    p.add(db.find_by_id("a"))
    p.add(db.find_by_id("b"))
    assert p.remove_current().id == "b"
    assert p.current_entry().id == "a"


def test_shopping_list_sums_items_across_quests():
    from arc_overlay.progress import shopping_list

    quests = [
        Quest(name="И хлам богатство", steps=[], required_items=["6× Провода", "1× Батарея"]),
        Quest(name="Другой", steps=[], required_items=["2× провода", "Ключ"]),
        Quest(name="Пустой", steps=[]),
    ]
    assert shopping_list(quests) == [
        ("Батарея", 1, ["И хлам богатство"]),
        ("Ключ", 1, ["Другой"]),
        ("Провода", 8, ["И хлам богатство", "Другой"]),
    ]


def test_bad_entries_skipped_and_broken_file_kept(tmp_path):
    path = tmp_path / "p.json"
    path.write_text('{"active": [{"id": "a", "name": "А"}, {"id": "b"}], "current": 0}', encoding="utf-8")
    assert [a.id for a in Progress.load(path).active] == ["a"]
    path.write_text("[]", encoding="utf-8")  # не словарь — не падаем
    assert Progress.load(path).active == []
    assert (tmp_path / "p.json.bad").exists()  # испорченный файл не потерян


def test_save_survives_locked_file(tmp_path, monkeypatch):
    from pathlib import Path

    progress = Progress.load(tmp_path / "p.json")

    def locked(*args, **kwargs):
        raise PermissionError("занят")

    monkeypatch.setattr(Path, "replace", locked)
    progress.save()  # не бросает исключение

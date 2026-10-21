from PyQt6.QtCore import QPoint, QPointF, QSettings, Qt
from PyQt6.QtGui import QMouseEvent

from arc_overlay.core.quest_db import QuestDB
from arc_overlay.ui.overlay import MAX_SCALE, MIN_SCALE, OverlayCard


def make_card(tmp_path):
    settings = QSettings(str(tmp_path / "overlay.ini"), QSettings.Format.IniFormat)
    return OverlayCard(QuestDB.load(), settings=settings), settings


def test_scale_changes_size_and_is_saved(qapp, tmp_path):
    card, settings = make_card(tmp_path)
    width = card.width()
    card.change_scale(0.5)
    assert card.scale == 1.5
    assert card.width() > width
    assert float(settings.value("scale")) == 1.5
    for _ in range(30):
        card.change_scale(0.1)
    assert card.scale == MAX_SCALE
    for _ in range(30):
        card.change_scale(-0.1)
    assert card.scale == MIN_SCALE
    again, _ = make_card(tmp_path)
    assert again.scale == MIN_SCALE


def test_drag_moves_card_and_saves_anchor(qapp, tmp_path):
    card, settings = make_card(tmp_path)
    card.show()
    card.set_editing(True)
    start = card.pos()

    def mouse(kind, pos):
        global_pos = QPointF(card.mapToGlobal(pos))
        return QMouseEvent(kind, QPointF(pos), global_pos, Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    card.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, QPoint(10, 10)))
    card.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, QPoint(-90, 60)))
    card.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, QPoint(-90, 60)))
    assert card.pos() == start + QPoint(-100, 50)
    assert settings.value("anchor") == QPoint(card.x() + card.width(), card.y())
    card.set_editing(False)
    assert not card.editing


def test_help_toggles_back(qapp, tmp_path):
    card, _ = make_card(tmp_path)
    card.show_quest(QuestDB.load().find("Чистое небо"))
    card.toggle_help()
    assert "Сочетания клавиш" in card._label.text()
    card.toggle_help()
    assert "Чистое небо" in card._label.text()


def test_reset_geometry(qapp, tmp_path):
    card, settings = make_card(tmp_path)
    card.change_scale(0.3)
    card.reset_geometry()
    assert card.scale == 1.0
    assert settings.value("scale") is None


def test_newer_remote_db_replaces_bundled(qapp, tmp_path):
    import json

    from arc_overlay.app import OverlayApp
    from arc_overlay.core.quest_db import DEFAULT_DB_PATH

    app = OverlayApp(qapp)
    data = json.loads(DEFAULT_DB_PATH.read_text(encoding="utf-8"))
    data["quests"].append({**data["quests"][0], "id": "new", "name": "Совсем новый квест", "aliases": []})

    older = tmp_path / "older.json"
    older.write_text(json.dumps({**data, "generated_at": "2000-01-01T00:00:00Z"}), encoding="utf-8")
    app._remote_db_loaded(older)
    assert app.db.find_exact("Совсем новый квест") is None

    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps({**data, "generated_at": "2999-01-01T00:00:00Z"}), encoding="utf-8")
    app._remote_db_loaded(newer)
    assert app.db.find_exact("Совсем новый квест") is not None
    assert app.card._db is app.db

    broken = tmp_path / "broken.json"
    broken.write_text("<html>не база</html>", encoding="utf-8")
    app._remote_db_loaded(broken)
    assert app.db.find_exact("Совсем новый квест") is not None


def test_opacity_is_clamped_saved_and_reset(qapp, tmp_path):
    card, settings = make_card(tmp_path)
    assert card.opacity == 100
    card.set_opacity(40)
    assert int(settings.value("opacity")) == 40
    card.set_opacity(5)
    assert card.opacity == 20
    again, _ = make_card(tmp_path)
    assert again.opacity == 20
    again.reset_geometry()
    assert again.opacity == 100 and settings.value("opacity") is None


def test_panel_over_guide_keeps_screenshot(qapp, tmp_path):
    from PyQt6.QtGui import QPixmap

    from arc_overlay.core.guide import GuidePage

    card, _ = make_card(tmp_path)
    card.show_quest(card._db.quests[0])
    card.show_guide_page(GuidePage("вики", "", "текст", "x.jpg"), 0, 1)
    pixmap = QPixmap(10, 10)
    card.set_image(pixmap)
    card.toggle_help()
    assert card.current_pixmap is None
    late = QPixmap(20, 20)
    card.set_image(late)  # догрузился, пока открыта справка — не показываем поверх справки
    card.toggle_help()
    assert card.current_pixmap is not None and card.current_pixmap.width() == 20

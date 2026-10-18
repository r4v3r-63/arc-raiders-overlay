import json
import os

import pytest
from PyQt6.QtCore import QSettings, Qt


@pytest.fixture
def app(qapp, tmp_path, monkeypatch):
    from arc_overlay import paths

    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "settings", lambda: QSettings(str(tmp_path / "n.ini"), QSettings.Format.IniFormat))
    from arc_overlay.app import OverlayApp

    overlay = OverlayApp(qapp)
    overlay.onboarding.hide()
    overlay.input.close_and_return_focus()
    overlay._game_timer.stop()
    return overlay


def test_shopping_panel_toggles(app):
    app.on_submitted("И хлам богатство")
    app.show_shopping()
    assert "Что собрать" in app.card._label.text() and "Провода" in app.card._label.text()
    app.show_shopping()
    assert "И хлам" in app.card._label.text() and "Что собрать" not in app.card._label.text()


def test_card_hides_outside_game(app, monkeypatch):
    from arc_overlay import winapi

    state = {"fg": (100, 999, True), "alive": True}
    monkeypatch.setattr(winapi, "foreground_info", lambda: state["fg"])
    monkeypatch.setattr(winapi, "window_alive", lambda hwnd: state["alive"] and hwnd == 100)
    monkeypatch.setattr(winapi, "find_game_window", lambda: 100 if state["alive"] else 0)
    app.card.show()
    app._check_game()
    assert app.card.isVisible()  # в игре — видна
    state["fg"] = (200, 998, False)  # переключились в браузер
    app._check_game()
    assert not app.card.isVisible()
    state["fg"] = (300, os.getpid(), False)  # окно самой программы — ничего не меняем
    app._check_game()
    assert not app.card.isVisible()
    state["fg"] = (100, 999, True)  # вернулись в игру
    app._check_game()
    assert app.card.isVisible()
    state.update(fg=(200, 998, False), alive=False)  # игра закрыта — карточка не прячется
    app._game_hwnd = 0
    app._check_game()
    assert app.card.isVisible()


def test_auto_hide_can_be_disabled(app, monkeypatch):
    from arc_overlay import winapi

    monkeypatch.setattr(winapi, "foreground_info", lambda: (200, 998, False))
    monkeypatch.setattr(winapi, "window_alive", lambda hwnd: True)
    app._game_hwnd = 100
    app._auto_hide_action.setChecked(False)
    app.card.show()
    app._check_game()
    assert app.card.isVisible()


def test_update_notice_when_release_is_newer(app, tmp_path):
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"target_commitish": "new-sha"}), encoding="utf-8")
    app._release_loaded(release, "old-sha")
    assert app._update_action.isVisible()


def test_no_update_notice_for_same_build(app, tmp_path):
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"target_commitish": "same"}), encoding="utf-8")
    app._release_loaded(release, "same")
    assert not app._update_action.isVisible()


def test_zoom_shows_guide_screenshot(app):
    app.on_submitted("Первый плацдарм")
    app.toggle_zoom()  # сам включает гайд
    app.page_index = next(i for i, p in enumerate(app.pages) if p.source == "вики")
    app.render_page()
    assert app.zoom.isVisible()
    app.toggle_zoom()
    assert not app.zoom.isVisible()
    app.toggle_zoom()
    app.toggle_guide()  # выход из гайда закрывает просмотр
    assert not app.zoom.isVisible()


def test_hotkeys_saved_refreshes_hints(app):
    from arc_overlay import shortcuts

    bindings = shortcuts.bindings()
    bindings["help"] = "Alt+H"
    app._hotkeys_saved(bindings)
    app.card.show_welcome()
    assert "Alt+H" in app.card._footer.text()
    app._hotkeys_saved(dict(shortcuts.DEFAULTS))


def test_map_shows_quest_places(app):
    app.on_submitted("Снова на вершине")
    quest = app.card.quest
    assert len(app.quest_maps()) > 1
    app.toggle_map()
    assert app.map_view.isVisible() and app.map_view._markers
    first = app.map_view._caption
    app.next_page()  # при открытой карте листаются карты квеста
    assert app.map_view._caption != first
    highlighted = [m for m in app.map_view._markers if m[3]]
    assert all(m[2].startswith(f"{app.card.step + 1} ") for m in highlighted)
    app.toggle_zoom()  # крупный скриншот и карта не открываются одновременно
    assert not app.map_view.isVisible()
    app.toggle_map()
    assert app.map_view.isVisible() and not app.zoom.isVisible()
    app.switch_quest() if len(app.progress.active) > 1 else app.show_current()
    assert not app.map_view.isVisible()
    assert quest.places


def test_map_without_places_and_without_location(app):
    app.on_submitted("Применение получше")
    app.toggle_map()
    assert app.map_view.isVisible() and not app.map_view._markers
    assert "не отмечены" in app.map_view._caption
    app.toggle_map()
    app.on_submitted("Дурное предчувствие")
    app.toggle_map()
    assert not app.map_view.isVisible()
    assert "нет карты" in app.card._label.text()


def test_zoom_uses_full_size_wiki_image(app, tmp_path):
    from PyQt6.QtGui import QPixmap

    app.on_submitted("Первый плацдарм")
    app.toggle_zoom()
    app.page_index = next(i for i, p in enumerate(app.pages) if p.source == "вики" and p.full)
    page = app.pages[app.page_index]
    app.render_page()
    big = QPixmap(3000, 2000)
    big.fill()
    path = tmp_path / "full.png"
    big.save(str(path))
    app._full_image_ready(page, path)
    assert app.zoom._pixmap.width() == 3000


def test_item_check_shows_panel_and_workshop_levels(app):
    app._item_cursor = (100, 100)
    app._item_recognized([("Провода", 80, 80, 100, 30)])
    assert app.card.panel == "item" and "Провода" in app.card._label.text()
    app._close_item_panel()
    assert app.card.panel == ""
    app._item_recognized([("Пустой экран", 0, 0, 10, 10)])
    assert "Не нашёл" in app.card._label.text()

    app.set_workshop_level("equipment_bench", 1)
    app._fill_workshops_menu()
    assert any("ур. 1" in a.text() for a in app._workshops_menu.actions())
    app.show_shopping()
    assert "Верстак для снаряжения → ур. 2" in app.card._label.text()
    app.show_shopping()
    app.set_workshop_level("equipment_bench", None)
    assert "equipment_bench" not in app.progress.workshops


def test_workshop_levels_saved(tmp_path):
    from arc_overlay.progress import Progress

    progress = Progress.load(tmp_path / "p.json")
    progress.workshops["scrappy"] = 3
    progress.save()
    assert Progress.load(tmp_path / "p.json").workshops == {"scrappy": 3}


def test_item_search_and_item_map(app):
    app.on_item_submitted("мини- насос")
    assert "Водяной насос" in app.item_input.error_label.text()
    app.on_item_submitted("водяной насос")
    assert app.card.panel == "item" and "Поле битвы у дамбы" in app.card._label.text()
    app.toggle_map()
    assert app.map_view.isVisible() and app.map_view._markers
    first = app.map_view._caption
    app.next_page()  # другая карта, где искать
    assert app.map_view._caption != first and "Водяной насос" in app.map_view._caption
    app.toggle_map()
    assert not app.map_view.isVisible()
    app.on_item_submitted("батарейка")  # единственный похожий предмет находится сам
    assert "Батарея" in app.card._label.text()


def test_whats_new_after_update(qapp, tmp_path, monkeypatch):
    from arc_overlay import onboarding, paths
    from arc_overlay.app import OverlayApp

    ini = str(tmp_path / "n.ini")
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "settings", lambda: QSettings(ini, QSettings.Format.IniFormat))
    old = QSettings(ini, QSettings.Format.IniFormat)
    old.setValue("onboarding_done", True)  # игрок с прошлой версии: обзор прошёл, новостей не видел
    old.setValue("news_seen", onboarding.LATEST_NEWS - 1)
    old.sync()

    overlay = OverlayApp(qapp)
    overlay._game_timer.stop()
    overlay.input.close_and_return_focus()
    assert overlay.news.isVisible() and not overlay.onboarding.isVisible()
    assert onboarding.NEWS[0][1] in overlay.news._text.text()
    assert onboarding.NEWS[1][1] not in overlay.news._text.text()  # уже видел
    overlay.news._next.click()
    assert not overlay.news.isVisible()
    assert QSettings(ini, QSettings.Format.IniFormat).value("news_seen", type=int) == onboarding.LATEST_NEWS
    overlay.show_news(only_unseen=True)
    assert not overlay.news.isVisible()  # второй раз сам не показывается
    overlay.show_news(only_unseen=False)  # из меню трея — все новости
    assert overlay.news.isVisible() and onboarding.NEWS[-1][1] in overlay.news._text.text()
    overlay.news.finish()


def test_new_user_sees_tour_not_news(app):
    assert not app.news.isVisible()


def test_release_commit_marker_in_notes(app, tmp_path):
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"target_commitish": "same", "body": "текст\n<!-- commit: abcdef1234 -->"}),
                       encoding="utf-8")
    app._release_loaded(release, "abcdef1234")
    assert not app._update_action.isVisible()
    app._release_loaded(release, "0000000")
    assert app._update_action.isVisible()


def test_second_capture_waits_for_first(app, monkeypatch):
    from PyQt6.QtCore import QTimer

    calls = []
    monkeypatch.setattr(QTimer, "singleShot", lambda ms, fn: calls.append(fn))
    app.import_from_screen()
    app.check_item()  # пока идёт первое распознавание, второе не запускается
    assert len(calls) == 1
    app._capture_finished()
    app.check_item()
    assert len(calls) == 2


def test_hourly_steam_sync_keeps_open_panel(app, tmp_path):
    app.on_submitted("Первый плацдарм")
    page = tmp_path / "steam.html"
    page.write_text("<div class='subSectionTitle'>x</div>", encoding="utf-8")
    app._steam_guide_loaded(page)
    app.toggle_guide()
    app.show_help()
    app._steam_guide_loaded(page)  # то же руководство — справка остаётся открытой
    assert app.card.panel == "help"


def test_blueprint_hotkey_and_window(app):
    app.on_item_submitted(app.db.items["anvil_blueprint"].name)
    app.toggle_blueprint()
    assert "anvil_blueprint" in app.progress.blueprints
    assert "уже изучен" in app.card._label.text()
    app.toggle_blueprint()
    assert "anvil_blueprint" not in app.progress.blueprints

    app.open_blueprints_window()
    window = app._blueprints_window
    assert window._list.count() >= 80
    window._list.item(0).setCheckState(Qt.CheckState.Checked)
    assert len(app.progress.blueprints) == 1
    window._filter.setText("наковальн")
    visible = [window._list.item(i) for i in range(window._list.count()) if not window._list.item(i).isHidden()]
    assert visible and all("аковальн" in r.text().lower() for r in visible)
    window.close()

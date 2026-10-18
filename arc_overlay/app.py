"""Точка входа: связывает базу квестов, карточку, окно ввода, горячие клавиши и трей."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile, QRect, QStandardPaths, Qt, QTimer, QUrl
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QCursor, QDesktopServices, QFont, QGuiApplication, QIcon,
                         QPainter, QPixmap)
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import autostart, guide, items, paths, shortcuts, winapi
from .hotkeys_window import HotkeysWindow
from .zoom import ZoomWindow
from .progress import Progress, shopping_list
from . import screen_import
from .input_window import InputWindow
from . import net
from .net import CachedDownloader
from .onboarding import LATEST_NEWS, NEWS, OnboardingWindow, news_pages
from .overlay import OverlayCard
from .quest_db import DATA_DIR, REMOTE_DATA_URL, Quest, QuestDB

RELEASE_API_URL = "https://api.github.com/repos/r4v3r-63/arc-raiders-overlay/releases/latest"
DOWNLOAD_URL = "https://github.com/r4v3r-63/arc-raiders-overlay/releases/latest/download/ARC-Raiders-Overlay.zip"
GAME_CHECK_INTERVAL_MS = 700
STEAM_GUIDE_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id=3672641520"
STEAM_MAX_AGE = 24 * 60 * 60  # руководство перекачивается раз в сутки
REMOTE_DB_URL = REMOTE_DATA_URL + "quests.json"
DB_MAX_AGE = 24 * 60 * 60  # свежая база с GitHub скачивается раз в сутки
UPDATE_CHECK_MAX_AGE = 6 * 60 * 60  # проверка новой версии программы — раз в 6 часов
SYNC_CHECK_INTERVAL_MS = 60 * 60 * 1000  # раз в час проверяем, не пора ли обновить
ITEM_PANEL_MS = 20 * 1000  # панель «брать или продавать» закрывается сама
ITEM_SEARCH_PANEL_MS = 90 * 1000  # найденный поиском предмет читают дольше
ITEM_GRAB_SIZE = (1600, 1100)  # область вокруг курсора, где ищем подсказку с названием предмета


def _is_json(data: bytes) -> bool:
    try:
        return isinstance(json.loads(data.decode("utf-8")), dict)
    except ValueError:
        return False


def make_tray_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#f2c94c"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setPen(QColor("#15181e"))
    painter.setFont(QFont("Arial", 30, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    painter.end()
    return QIcon(pixmap)


class OverlayApp:
    def __init__(self, app: QApplication):
        self.app = app
        self.db = QuestDB.load()
        self.settings = paths.settings()
        shortcuts.load(self.settings)
        self.card = OverlayCard(self.db)
        self.card.editing_changed.connect(lambda _editing: self._apply_visibility())
        self._capturing = False  # идёт снимок экрана и распознавание
        self._recognizer = None
        self.zoom = ZoomWindow()
        self._zoom_on = False  # игрок открыл скриншот на весь экран
        self.map_view = ZoomWindow()
        self._map_on = False  # игрок открыл карту с точками квеста
        self._map_index = 0  # какая из карт квеста показана
        self._map_item = None  # карта открыта для предмета: места, где его искать (ItemReport)
        self._full_images: dict[str, QPixmap] = {}  # скриншоты вики в полном размере
        self._item_timer = QTimer()
        self._item_timer.setSingleShot(True)
        self._item_timer.timeout.connect(self._close_item_panel)
        self.downloader = CachedDownloader()
        self.progress = Progress.load(paths.user_data_dir() / "прогресс.json")
        self.downloader.cleanup()
        self.guide_mode = False
        self._close_zoom()
        self.pages: list[guide.GuidePage] = []
        self.page_index = 0
        self.steam_pages: dict[str, list[guide.GuidePage]] = {}  # id раздела → страницы
        self.steam_status = ""
        self.steam_html: str | None = None
        self._steam_sync_done = False
        self.input = InputWindow()
        self.input.submitted.connect(self.on_submitted)
        self.input.help_requested.connect(self.show_help)
        self.input.set_suggester(lambda text: self.db.suggest(text))
        self.item_input = InputWindow("Поиск предмета", "Предмет:", "например, Водяной насос")
        self.item_input.submitted.connect(self.on_item_submitted)
        self.item_input.help_requested.connect(self.show_help)
        self.item_input.set_suggester(lambda text: self.db.suggest_items(text))

        self.hotkeys = winapi.HotkeyManager()
        app.installNativeEventFilter(self.hotkeys)
        failed = self.register_hotkeys()
        app.aboutToQuit.connect(self.hotkeys.unregister_all)
        app.aboutToQuit.connect(self._stop_recognizer)

        self.tray = self._make_tray()
        try:
            autostart.refresh()
        except OSError:
            pass  # реестр закрыт политикой — программа работает и без этого
        self.show_current()
        self.sync()

        self.onboarding = OnboardingWindow()
        self.onboarding.finished.connect(self._onboarding_finished)
        self.news = OnboardingWindow(title="Что нового", finish_text="Понятно")
        self.news.finished.connect(self._news_seen)
        if not self.settings.value("onboarding_done", False, type=bool):
            self.onboarding.open()  # в обзоре уже всё новое — «Что нового» новичку не нужен
            self._news_seen()
        else:
            self.show_news(only_unseen=True)
        self._sync_timer = QTimer()
        self._sync_timer.timeout.connect(self.sync)
        self._sync_timer.start(SYNC_CHECK_INTERVAL_MS)
        self._game_timer = QTimer()
        self._game_timer.timeout.connect(self._check_game)
        self._game_timer.start(GAME_CHECK_INTERVAL_MS)
        self._user_visible = True  # видимость, которую выбрал игрок (спрятать / показать карточку)
        self._hidden_outside_game = False  # игра запущена, но игрок переключился из неё
        self._game_hwnd = 0
        self._game_ticks = 0
        self._update_notified = False
        self._apply_visibility()

        if not winapi.IS_WINDOWS:
            # Без Windows глобальных клавиш нет — сразу открываем ввод для проверки.
            self.input.open()
        elif failed:
            QMessageBox.warning(
                None,
                "Горячие клавиши",
                "Не удалось занять клавиши: " + ", ".join(failed)
                + ".\nВозможно, их уже использует другая программа. Поменять их можно в меню значка в трее: "
                  "«Горячие клавиши…».",
            )

    def _make_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(make_tray_icon(), self.app)
        tray.setToolTip("ARC Raiders — подсказчик")
        menu = QMenu()
        enter = QAction("Ввести квест", menu)
        enter.triggered.connect(self.open_quest_input)
        tour_action = QAction("Как пользоваться", menu)
        tour_action.triggered.connect(lambda: self.onboarding.open())
        news_action = QAction("Что нового", menu)
        news_action.triggered.connect(lambda: self.show_news(only_unseen=False))
        hotkeys_action = QAction("Горячие клавиши…", menu)
        hotkeys_action.triggered.connect(self.open_hotkeys_window)
        help_action = QAction("Сочетания клавиш (?)", menu)
        help_action.triggered.connect(self.show_help)
        edit_action = QAction("Переместить / изменить масштаб", menu)
        edit_action.triggered.connect(self.toggle_editing)
        self._toggle_action = QAction("Спрятать карточку", menu)
        self._toggle_action.triggered.connect(self.toggle_card)
        self._quest_actions = []
        for title, handler in [
            ("Гайд со скриншотами", self.toggle_guide),
            ("Карта с точками", self.toggle_map),
            ("Открыть гайд в Steam", lambda: self._open(self.card.quest and self.card.quest.steam_url)),
            ("Найти видео на YouTube", lambda: self._open(self.card.quest and self.card.quest.video_url)),
            ("Открыть страницу на вики", lambda: self._open(self.card.quest and self.card.quest.wiki_url)),
        ]:
            action = QAction(title, menu)
            action.triggered.connect(handler)
            action.setEnabled(False)
            self._quest_actions.append(action)
        self._autostart_action = QAction("Запускать вместе с Windows", menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.setEnabled(autostart.available())
        self._autostart_action.setChecked(autostart.is_enabled())
        self._autostart_action.toggled.connect(self.set_autostart)
        self._auto_hide_action = QAction("Прятать карточку вне игры", menu)
        self._auto_hide_action.setCheckable(True)
        self._auto_hide_action.setChecked(paths.settings().value("auto_hide", True, type=bool))
        self._auto_hide_action.toggled.connect(self.set_auto_hide)
        self._update_action = QAction("Скачать новую версию программы", menu)
        self._update_action.triggered.connect(lambda: self._open(DOWNLOAD_URL))
        self._update_action.setVisible(False)
        shopping_action = QAction("Что собрать", menu)
        shopping_action.triggered.connect(self.show_shopping)
        self._clear_cache_action = QAction("Очистить кэш", menu)
        self._clear_cache_action.triggered.connect(self.clear_cache)
        menu.aboutToShow.connect(self._update_cache_label)
        quit_action = QAction("Выход", menu)
        quit_action.triggered.connect(self.app.quit)
        menu.addAction(self._update_action)
        menu.addAction(enter)
        self._active_menu = menu.addMenu("Активные квесты")
        self._active_menu.aboutToShow.connect(self._fill_active_menu)
        menu.addAction(shopping_action)
        self._workshops_menu = menu.addMenu("Мастерские")
        self._workshops_menu.aboutToShow.connect(self._fill_workshops_menu)
        import_action = QAction("Найти квесты на экране", menu)
        import_action.triggered.connect(self.import_from_screen)
        menu.addAction(import_action)
        menu.addAction(self._toggle_action)
        menu.addAction(edit_action)
        menu.addAction(help_action)
        menu.addAction(hotkeys_action)
        menu.addAction(tour_action)
        menu.addAction(news_action)
        menu.addSeparator()
        for action in self._quest_actions:
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self._auto_hide_action)
        menu.addAction(self._autostart_action)
        menu.addAction(self._clear_cache_action)
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray_menu = menu  # держим ссылку, иначе меню удалит сборщик мусора
        return tray

    def set_autostart(self, enabled: bool):
        try:
            autostart.set_enabled(enabled)
        except OSError as error:
            self.tray.showMessage("ARC Raiders — подсказчик", f"Не удалось изменить автозапуск: {error}")
        self._autostart_action.setChecked(autostart.is_enabled())

    def _update_cache_label(self):
        megabytes = self.downloader.size() / 1024 / 1024
        self._clear_cache_action.setText(f"Очистить кэш ({megabytes:.0f} МБ)")

    def clear_cache(self):
        freed = self.downloader.clear() / 1024 / 1024
        self.tray.showMessage("ARC Raiders — подсказчик",
                              f"Кэш очищен: {freed:.0f} МБ. Нужное скачается заново при открытии гайда.")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # обычный клик по значку
            self.toggle_card()

    def set_card_visible(self, visible: bool):
        self._user_visible = visible
        self._toggle_action.setText("Спрятать карточку" if visible else "Показать карточку")
        self._apply_visibility()

    def _apply_visibility(self):
        visible = self.card.editing or (self._user_visible and not self._hidden_outside_game)
        if visible != self.card.isVisible():
            self.card.setVisible(visible)
        if not visible and self.zoom.isVisible():
            self.zoom.hide()
        elif visible and self._zoom_on and not self.zoom.isVisible():
            self._update_zoom()
        if not visible and self.map_view.isVisible():
            self.map_view.hide()
        elif visible and self._map_on and not self.map_view.isVisible():
            self._update_map()

    def toggle_card(self):
        if self.card.editing:
            self.card.set_editing(False)
        self.set_card_visible(not self._user_visible)

    # --- карточка только в игре -------------------------------------------

    def _check_game(self):
        """Прячет карточку, когда игра запущена, но активно другое окно (браузер, рабочий стол)."""
        info = winapi.foreground_info()
        if info is None:
            return  # не Windows
        hwnd, pid, is_game = info
        if pid == os.getpid():
            return  # активно окно самой программы (ввод квеста, настройка)
        if is_game:
            self._game_hwnd = hwnd
        elif not winapi.window_alive(self._game_hwnd):
            self._game_ticks += 1
            # Полный перебор окон — реже: раз в несколько секунд.
            self._game_hwnd = winapi.find_game_window() if self._game_ticks % 8 == 0 else 0
        hide = self._auto_hide_action.isChecked() and bool(self._game_hwnd) and not is_game
        if hide != self._hidden_outside_game:
            self._hidden_outside_game = hide
            self._apply_visibility()

    def set_auto_hide(self, enabled: bool):
        self.settings.setValue("auto_hide", enabled)
        if not enabled and self._hidden_outside_game:
            self._hidden_outside_game = False
            self._apply_visibility()

    # --- что собрать ------------------------------------------------------

    def _active_quests(self) -> list[Quest]:
        quests = [self.progress.resolve(self.db, entry) for entry in self.progress.active]
        return [q for q in quests if q]

    def show_shopping(self):
        extra = items.workshop_shopping(self.db, self.progress.workshops)
        note = ""
        if self.db.workshops and not self.progress.workshops:
            note = "Мастерские не учтены: отметьте их уровни в меню значка в трее → «Мастерские»."
        self.card.toggle_shopping(shopping_list(self._active_quests(), extra), note)
        self.set_card_visible(True)

    # --- новая версия программы -------------------------------------------

    def check_update(self):
        """Сверяет сборку программы с последним релизом на GitHub (не чаще раза в 6 часов)."""
        build = paths.build_info()
        if build.get("commit"):
            self.downloader.get(RELEASE_API_URL, lambda path: self._release_loaded(path, build["commit"]),
                                max_age=UPDATE_CHECK_MAX_AGE)

    def _release_loaded(self, path, commit: str):
        if not path:
            return
        try:
            release = json.loads(path.read_text(encoding="utf-8"))
            # Коммит сборки — скрытой строкой в описании релиза (релиз обновляется на месте).
            marker = re.search(r"<!-- commit: ([0-9a-f]{7,40}) -->", release.get("body") or "")
            latest = marker.group(1) if marker else release.get("target_commitish", "")
        except (OSError, ValueError, AttributeError, TypeError):
            return
        if latest and latest != commit:
            self._update_action.setVisible(True)
            if not self._update_notified:
                self._update_notified = True
                self.tray.showMessage("ARC Raiders — подсказчик",
                                      "Вышла новая версия программы. Скачать — в меню значка в трее.")

    def toggle_editing(self):
        self.set_card_visible(True)
        self.card.toggle_editing()

    def show_help(self):
        self.card.toggle_help()
        self.set_card_visible(True)

    def next_step(self):
        self.guide_mode = False
        self._close_zoom()
        self.card.next_step()
        self._save_step()
        self._update_map()  # на открытой карте выделится точка нового шага
        self.set_card_visible(True)

    def prev_step(self):
        self.guide_mode = False
        self._close_zoom()
        self.card.prev_step()
        self._save_step()
        self._update_map()  # на открытой карте выделится точка нового шага
        self.set_card_visible(True)

    def _save_step(self):
        if self.card.quest is not None:
            self.progress.set_step(self.card.step)
            self.progress.save()

    # --- активные квесты --------------------------------------------------

    # --- горячие клавиши --------------------------------------------------

    def _hotkey_callbacks(self) -> dict:
        return {
            "input": self.open_quest_input, "next_step": self.next_step, "prev_step": self.prev_step,
            "switch_quest": self.switch_quest, "complete": self.complete_quest,
            "import": self.import_from_screen, "shopping": self.show_shopping,
            "item": self.check_item, "find_item": self.open_item_search, "guide": self.toggle_guide,
            "page_down": self.next_page, "page_up": self.prev_page, "zoom": self.toggle_zoom,
            "map": self.toggle_map,
            "open_browser": self.open_guide_in_browser, "toggle_card": self.toggle_card,
            "edit": self.toggle_editing, "help": self.show_help,
        }

    def register_hotkeys(self) -> list[str]:
        """Регистрирует сочетания из настроек; возвращает те, что занять не удалось."""
        self.hotkeys.unregister_all()
        failed = []
        used = set()
        for action, callback in self._hotkey_callbacks().items():
            native = shortcuts.to_native(shortcuts.bindings()[action])
            if native in used:  # новое сочетание по умолчанию совпало с тем, что игрок выбрал сам
                failed.append(f"{shortcuts.key(action)} (назначено на два действия)")
                continue
            used.add(native)
            if native is None or not self.hotkeys.register(*native, callback):
                failed.append(shortcuts.key(action))
        return failed

    def open_hotkeys_window(self):
        if getattr(self, "_hotkeys_window", None) is None:
            self._hotkeys_window = HotkeysWindow()
            self._hotkeys_window.saved.connect(self._hotkeys_saved)
            self._hotkeys_window.closed.connect(self.register_hotkeys)
        # Пока окно открыто, свои сочетания отключены: иначе нажатие перехватилось бы, а не записалось.
        self.hotkeys.unregister_all()
        self._hotkeys_window.open(shortcuts.bindings())

    def _hotkeys_saved(self, bindings: dict):
        shortcuts.save(self.settings, bindings)
        failed = self.register_hotkeys()
        self.card.refresh()
        if failed and winapi.IS_WINDOWS:
            QMessageBox.warning(None, "Горячие клавиши",
                                "Не удалось занять: " + ", ".join(failed)
                                + ".\nИх уже использует другая программа — выберите другие сочетания.")

    def show_news(self, only_unseen: bool):
        """«Что нового»: после обновления — только непрочитанное, из меню трея — последние новости."""
        seen = self.settings.value("news_seen", 0, type=int) if only_unseen else LATEST_NEWS - len(NEWS)
        pages = news_pages(seen)
        if pages:
            self.news.set_pages(pages)
            self.news.open()

    def _news_seen(self):
        self.settings.setValue("news_seen", LATEST_NEWS)
        self.settings.sync()

    def _onboarding_finished(self):
        self.settings.setValue("onboarding_done", True)
        self.settings.sync()

    def show_current(self, notice: str = ""):
        """Показывает текущий активный квест (или приглашение ввести квест, если список пуст)."""
        entry = self.progress.current_entry()
        quest = self.progress.resolve(self.db, entry)
        self.guide_mode = False
        self._close_zoom()
        self._close_map()
        self._map_index = 0
        self.page_index = 0
        if quest is None:
            self.card.show_welcome(notice)
        else:
            self.card.show_quest(quest, entry.step, (self.progress.current, len(self.progress.active)), notice)
            self.load_steam_guide()
            self.rebuild_pages()
        for action in self._quest_actions:
            action.setEnabled(quest is not None)

    def switch_quest(self):
        if len(self.progress.active) > 1:
            self.progress.switch()
            self.progress.save()
        self.show_current()
        self.set_card_visible(True)

    def select_quest(self, index: int):
        self.progress.select(index)
        self.progress.save()
        self.show_current()
        self.set_card_visible(True)

    def complete_quest(self):
        done, added, skipped = self.progress.complete_current(self.db)
        if done is None and not added:
            return
        self.progress.save()
        lines = [f"✓ «{done.name if done else 'Квест'}» выполнен."]
        if added:
            lines.append("Добавлены: " + ", ".join(f"«{q.name}»" for q in added) + ".")
        if skipped:
            lines.append("Открылись: " + ", ".join(f"«{q.name}»" for q in skipped)
                         + f". Нужные возьми через {shortcuts.key('input')}.")
        self.show_current("\n".join(lines))
        self.set_card_visible(True)

    def remove_quest(self):
        entry = self.progress.remove_current()
        if entry is not None:
            self.progress.save()
            self.show_current(f"«{entry.name}» убран из списка.")
            self.set_card_visible(True)

    # --- импорт квестов с экрана --------------------------------------------

    def _open_input(self, window: InputWindow, other: InputWindow):
        """Открывает окно ввода; второе окно ввода закрывается, а фокус потом вернётся игре, а не ему."""
        previous = None
        if other.isVisible():
            previous = other._previous_window
            other.hide()
        window.open()
        if previous is not None:
            window._previous_window = previous

    def open_quest_input(self):
        self._open_input(self.input, self.item_input)

    def open_item_search(self):
        self._open_input(self.item_input, self.input)

    # --- снимок экрана и распознавание ----------------------------------------

    def _capture(self, grab, delay_ms: int):
        """Прячет свои окна (их не должно быть на снимке) и через delay_ms делает снимок."""
        if self._capturing:
            return  # предыдущее распознавание ещё идёт
        self._capturing = True
        for window in (self.card, self.input, self.item_input, self.zoom, self.map_view):
            window.hide()  # вернёт _apply_visibility
        QTimer.singleShot(delay_ms, grab)

    def _recognize(self, image, file_name: str, on_done, boxes: bool = False):
        thread = screen_import.RecognizeThread(image, paths.cache_dir() / file_name, boxes)
        thread.recognized.connect(on_done)
        thread.failed.connect(self._show_notice)
        thread.finished.connect(self._capture_finished)
        self._recognizer = thread  # ссылка живёт, пока поток не закончит: следующий снимок только после
        thread.start()

    def _capture_finished(self):
        self._capturing = False

    def _stop_recognizer(self):
        if self._recognizer is not None and self._recognizer.isRunning():
            self._recognizer.wait(5000)

    def import_from_screen(self):
        """Снимок экрана → распознавание → найденные квесты в список активных."""
        self._capture(self._grab_screen, 200)

    def _grab_screen(self):
        image = QGuiApplication.primaryScreen().grabWindow(0).toImage()
        self._apply_visibility()
        self._show_notice("Ищу квесты на экране…")
        self._recognize(image, "экран.png", self._screen_recognized)

    def _screen_recognized(self, lines: list):
        found = screen_import.match_quests(self.db, lines)
        if not found:
            self._show_notice("Квесты на экране не найдены. Откройте в игре экран, где виден список квестов "
                              f"(например, лобби), и нажмите {shortcuts.key('import')} ещё раз.")
            return
        had_current = self.progress.current_entry() is not None
        new = [q for q in found if not any(e.id == q.id or e.name == q.name for e in self.progress.active)]
        for quest in new:
            self.progress.add(quest, make_current=not had_current and quest is new[0])
        self.progress.save()
        names = ", ".join(f"«{q.name}»" for q in found)
        if new:
            notice = f"Найдено на экране: {names}. Добавлено в список: {len(new)}."
        else:
            notice = f"Найдено на экране: {names}. Все они уже в списке."
        self.show_current(notice)
        self.set_card_visible(True)

    # --- брать или продавать ------------------------------------------------

    def check_item(self):
        """Снимок экрана вокруг курсора → название предмета из подсказки игры → нужен ли он."""
        self._capture(self._grab_item, 150)

    def _grab_item(self):
        # Экран, на котором курсор: игра может быть и на втором мониторе.
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        image = screen.grabWindow(0).toImage()
        self._apply_visibility()
        ratio = image.width() / max(1, screen.geometry().width())
        pos = QCursor.pos() - screen.geometry().topLeft()
        cx, cy = pos.x() * ratio, pos.y() * ratio
        width, height = ITEM_GRAB_SIZE
        area = QRect(int(cx - width / 2), int(cy - height / 2), width, height).intersected(image.rect())
        if area.isEmpty():
            area = image.rect()
        self._item_cursor = (cx - area.x(), cy - area.y())
        self._recognize(image.copy(area), "предмет.png", self._item_recognized, boxes=True)

    def _item_recognized(self, lines: list):
        item = items.match_item(self.db, lines, self._item_cursor)
        if item is None:
            self._show_notice("Не нашёл название предмета. Наведите курсор на предмет, чтобы появилась подсказка "
                              f"с его названием, и нажмите {shortcuts.key('item')} ещё раз.")
            return
        self._show_item(item, ITEM_PANEL_MS)

    def on_item_submitted(self, text: str):
        item = self.db.find_item(text)
        similar = self.db.similar_items(text) if item is None else []
        if item is None and len(similar) == 1:  # «батарейка» → «Батарея»
            item = self.db.find_item(similar[0])
        if item is None:
            hint = f" Возможно: {', '.join(similar)}." if similar else ""
            self.item_input.show_error(f"Предмет «{text.strip()}» не найден.{hint}")
            return
        self.item_input.close_and_return_focus()
        self._show_item(item, ITEM_SEARCH_PANEL_MS)

    def _show_item(self, item, close_after_ms: int):
        report = items.item_report(self.db, item, self._active_quests(), self.progress.completed,
                                   self.progress.workshops)
        self._close_map()
        self._close_zoom()
        self.card.show_item(report)
        self.set_card_visible(True)
        self._item_timer.start(close_after_ms)

    def _close_item_panel(self):
        if self._map_on and self._map_item is not None:
            self._item_timer.start(ITEM_PANEL_MS)  # пока смотрят карту, панель не закрываем
            return
        if self.card.panel == "item":
            self.card.close_panel()

    def _fill_workshops_menu(self):
        """Уровни мастерских: по ним «Что собрать» и проверка предмета считают нужное для улучшений."""
        for action in self._workshops_menu.actions():
            if action.menu() is not None:
                action.menu().deleteLater()  # clear() подменю не удаляет
        self._workshops_menu.clear()
        for workshop in self.db.workshops:
            level = self.progress.workshops.get(workshop.id)
            title = workshop.name + ("" if level is None else " — не построен" if level == 0 else f" — ур. {level}")
            sub = self._workshops_menu.addMenu(title)
            group = QActionGroup(sub)
            first = 0 if workshop.requirements(1) else 1  # если первый уровень бесплатный, «не построен» не бывает
            options = [(None, "Не учитывать")] + [
                (lv, "Не построен" if lv == 0 else f"Уровень {lv}" + (" (максимум)" if lv == workshop.max_level else ""))
                for lv in range(first, workshop.max_level + 1)]
            for value, text in options:
                action = sub.addAction(text)
                action.setCheckable(True)
                action.setChecked(value == level)
                action.setActionGroup(group)
                action.triggered.connect(lambda _checked, w=workshop.id, v=value: self.set_workshop_level(w, v))

    def set_workshop_level(self, workshop_id: str, level: int | None):
        if level is None:
            self.progress.workshops.pop(workshop_id, None)
        else:
            self.progress.workshops[workshop_id] = level
        self.progress.save()

    def _show_notice(self, text: str):
        """Сообщение на карточке поверх текущего квеста (или приглашения)."""
        entry = self.progress.current_entry()
        quest = self.progress.resolve(self.db, entry)
        if quest is None:
            self.card.show_welcome(text)
        else:
            self.card.show_quest(quest, entry.step, (self.progress.current, len(self.progress.active)), text)
        self.guide_mode = False
        self._close_zoom()
        self._close_map()
        self.set_card_visible(True)

    def _fill_active_menu(self):
        self._active_menu.clear()
        if not self.progress.active:
            empty = self._active_menu.addAction(f"Пока пусто — {shortcuts.key('input')}")
            empty.setEnabled(False)
            return
        for i, entry in enumerate(self.progress.active):
            action = self._active_menu.addAction(entry.name)
            action.setCheckable(True)
            action.setChecked(i == self.progress.current)
            action.triggered.connect(lambda _checked, i=i: self.select_quest(i))
        self._active_menu.addSeparator()
        self._active_menu.addAction(f"Квест выполнен ({shortcuts.key('complete')})", self.complete_quest)
        self._active_menu.addAction("Убрать текущий квест из списка", self.remove_quest)

    # --- гайд -------------------------------------------------------------

    def toggle_guide(self):
        if self.card.quest is None:
            return
        self.guide_mode = not self.guide_mode
        if self.guide_mode:
            self.render_page()
        else:
            self._close_zoom()
            self.card.show_step()
        self.set_card_visible(True)

    def next_page(self):
        self._turn_page(+1)

    def prev_page(self):
        self._turn_page(-1)

    def _turn_page(self, delta: int):
        if self._map_on:  # при открытой карте те же клавиши переключают карты
            maps = self._map_ids()
            if maps:
                self._map_index = max(0, min(len(maps) - 1, self._map_index + delta))
                self._update_map()
            return
        if self.card.quest is None:
            return
        if self.guide_mode and self.pages:
            self.page_index = max(0, min(len(self.pages) - 1, self.page_index + delta))
        self.guide_mode = True
        self.render_page()
        self.set_card_visible(True)

    def rebuild_pages(self):
        quest = self.card.quest
        if quest is None:
            self.pages = []
            return
        section = guide.steam_section_id(quest.steam_url)
        pages = list(self.steam_pages.get(section, []))
        pages += guide.wiki_pages(quest)
        if quest.hints:
            pages.append(guide.GuidePage("подсказки", "Подсказки", "\n".join("• " + h for h in quest.hints)))
        self.pages = pages
        self.page_index = min(self.page_index, max(0, len(pages) - 1))

    def render_page(self):
        if not self.guide_mode or self.card.quest is None:
            return
        if not self.pages:
            self.card.show_guide_page(None, 0, 0, self.steam_status)
            return
        page = self.pages[self.page_index]
        self.card.show_guide_page(page, self.page_index, len(self.pages), self.steam_status)
        if not page.image:
            self._close_zoom()  # на странице без скриншота смотреть крупно нечего
            return
        if page.image.startswith("http"):
            self.card.set_image(None, "Загружаю скриншот…")
            self.downloader.get(page.image, lambda path, p=page: self._image_ready(p, path), validate=net.is_image)
        else:
            self.card.set_image(QPixmap(page.image))
        self._update_zoom()

    def _image_ready(self, page: guide.GuidePage, path):
        if self.guide_mode and self.pages and self.page_index < len(self.pages) and self.pages[self.page_index] is page:
            self.card.set_image(QPixmap(str(path)) if path else None, "" if path else "Скриншот не загрузился")
            self._update_zoom()

    # --- скриншот на весь экран -------------------------------------------

    def toggle_zoom(self):
        if self._zoom_on:
            self._close_zoom()
            return
        if self.card.quest is None:
            return
        self._close_map()
        self._zoom_on = True
        if not self.guide_mode:
            self.guide_mode = True
            self.render_page()  # сам вызовет _update_zoom
        else:
            self._update_zoom()
        self.set_card_visible(True)

    def _update_zoom(self):
        """Показывает на весь экран скриншот текущей страницы гайда (если просмотр включён)."""
        if not self._zoom_on:
            return
        page = self.pages[self.page_index] if self.guide_mode and self.pages else None
        pixmap = self.card.current_pixmap
        if page is None or not page.image:
            self._close_zoom()
            self._show_notice("На этой странице гайда нет скриншота.") if page is not None else None
            return
        if pixmap is None:
            return  # скриншот ещё загружается — покажем, когда придёт
        if page.full:
            # В базе уменьшенная копия: пока качается оригинал с вики, показываем её.
            if page.full in self._full_images:
                pixmap = self._full_images[page.full]
            else:
                self.downloader.get(page.full, lambda path, p=page: self._full_image_ready(p, path),
                                    validate=net.is_image)
        caption = " — ".join(filter(None, [page.title, page.text]))
        hint = (f"{shortcuts.key('page_up')} / {shortcuts.key('page_down')} — листать · "
                f"{shortcuts.key('zoom')} — закрыть · {self.page_index + 1} из {len(self.pages)}")
        self.zoom.show_image(pixmap, caption, hint)

    def _full_image_ready(self, page: guide.GuidePage, path):
        if not path:
            return  # оригинал не скачался — остаётся уменьшенная копия
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return
        if len(self._full_images) > 6:  # не держим в памяти много больших картинок
            self._full_images.clear()
        self._full_images[page.full] = pixmap
        if self._zoom_on and self.guide_mode and self.pages and self.pages[self.page_index] is page:
            self._update_zoom()

    def _close_zoom(self):
        self._zoom_on = False
        self.zoom.hide()

    # --- карта с точками квеста -------------------------------------------

    def quest_maps(self) -> list[str]:
        """id карт текущего квеста, для которых есть картинка: сначала карты с точками."""
        quest = self.card.quest
        if quest is None:
            return []
        ids = []
        for map_id in [p["map"] for p in quest.places] + list(quest.locations):
            game_map = self.db.maps.get(map_id)
            if game_map is not None and game_map.image and map_id not in ids:
                ids.append(map_id)
        return ids

    def toggle_map(self):
        if self._map_on:
            self._close_map()
            return
        item = self.card.item
        # С панелью предмета — места, где его искать; если таких карт нет — карта квеста.
        self._map_item = item if item is not None and item.where.maps else None
        if self._map_item is not None:
            self._map_index = 0
        elif self.card.quest is None:
            return
        elif not self.quest_maps():
            self._show_notice("Для этого квеста нет карты: он выполняется на любой локации.")
            return
        self._close_zoom()
        self._map_on = True
        self._update_map()
        self.set_card_visible(True)

    def _update_map(self):
        """Показывает карту текущего квеста с точками; точка текущего шага выделена."""
        if not self._map_on:
            return
        maps = self._map_ids()
        if not maps:
            self._close_map()
            return
        self._map_index = min(self._map_index, len(maps) - 1)
        game_map = self.db.maps[maps[self._map_index]]
        local = DATA_DIR / game_map.image
        if local.exists():
            pixmap = QPixmap(str(local))
        else:
            # Карта из свежей базы, которой ещё нет в папке программы, докачивается с GitHub.
            url = REMOTE_DATA_URL + game_map.image
            pixmap = self._full_images.get(url)
            if pixmap is None:
                self.downloader.get(url, lambda path, u=url: self._map_image_ready(u, path), validate=net.is_image)
                return
        name = game_map.name_ru or game_map.name
        if self._map_item is not None:
            report = self._map_item
            spots = next(s for s in report.where.maps if s.map_id == game_map.id)
            markers = [(r["x"], r["y"], f"{i + 1} {r['name']}", False) for i, r in enumerate(spots.rooms)]
            caption = f"{report.item.name} — {name}: места с лутом «{', '.join(report.where.types)}»"
            hint = f"{shortcuts.key('map')} — закрыть"
        else:
            quest = self.card.quest
            places = [p for p in quest.places if p["map"] == game_map.id]
            markers = [(p["x"], p["y"], f"{p['step'] + 1} {p['name']}", p["step"] == self.card.step) for p in places]
            caption = f"{quest.name} — {name}"
            if not places:
                caption += ". Точные места на карте не отмечены"
            hint = f"Цифра — номер шага квеста · {shortcuts.key('map')} — закрыть"
        if len(maps) > 1:
            hint += (f" · {shortcuts.key('page_up')} / {shortcuts.key('page_down')} — другая карта "
                     f"({self._map_index + 1} из {len(maps)})")
        self.map_view.show_image(pixmap, caption, hint, markers)

    def _map_image_ready(self, url: str, path):
        if not self._map_on:
            return  # карту уже закрыли
        pixmap = QPixmap(str(path)) if path else QPixmap()
        if pixmap.isNull():
            self._close_map()
            self._show_notice("Карта не загрузилась — проверьте интернет.")
            return
        self._full_images[url] = pixmap
        self._update_map()

    def _map_ids(self) -> list[str]:
        if self._map_item is not None:
            return [s.map_id for s in self._map_item.where.maps
                    if s.map_id in self.db.maps and self.db.maps[s.map_id].image]
        return self.quest_maps()

    def _close_map(self):
        self._map_on = False
        self._map_item = None
        self.map_view.hide()

    def sync(self):
        self.sync_db()
        self.sync_steam_guide()
        self.check_update()

    def sync_db(self):
        """Скачивает свежую базу квестов с GitHub (её раз в сутки пересобирает GitHub Actions)."""
        self.downloader.get(REMOTE_DB_URL, self._remote_db_loaded, max_age=DB_MAX_AGE, validate=_is_json)

    def _remote_db_loaded(self, path):
        if not path:
            return
        try:
            remote = QuestDB.from_dict(json.loads(path.read_text(encoding="utf-8")))
            newer = isinstance(remote.generated_at, str) and remote.generated_at > self.db.generated_at
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return  # битый или чужой файл — остаёмся на текущей базе
        if len(remote.quests) < 50 or not newer:
            return
        self.db = remote
        self.card.set_db(remote)
        self.merge_steam_quests()
        if self.card.quest is not None and not self.guide_mode and not self.card.panel and not self._map_on:
            self.show_current()  # шаги и подсказки текущего квеста — из новой базы

    def sync_steam_guide(self):
        """Скачивает руководство Steam (не чаще раза в сутки) и добавляет в поиск новые квесты из него."""
        self.downloader.get(STEAM_GUIDE_URL, self._steam_guide_loaded, max_age=STEAM_MAX_AGE,
                            validate=lambda data: b"subSectionTitle" in data)

    def _steam_guide_loaded(self, path):
        self._steam_sync_done = True
        changed = not path
        if path:
            try:
                page_html = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                page_html = self.steam_html
            if page_html != self.steam_html:
                changed = True
                self.steam_html = page_html
                self.steam_pages.clear()
                self.merge_steam_quests()
                if self.card.quest is None and self.progress.active:
                    self.show_current()  # текущий квест мог оказаться из руководства Steam
        if changed and not self.card.panel:  # раз в час без изменений карточку не трогаем
            self.load_steam_guide()
            self.rebuild_pages()
            self.render_page()

    def merge_steam_quests(self) -> int:
        """Квесты из руководства, которых нет в базе, становятся доступны для поиска."""
        added = 0
        for item in guide.parse_steam_index(self.steam_html or ""):
            url = f"{STEAM_GUIDE_URL}#{item.section_id}"
            quest = self.db.find_exact(item.title)
            if quest is not None:
                quest.steam_url = url  # номер раздела из живого руководства точнее, чем в базе
                continue
            game_map = self.db.find_map_exact(item.category)
            self.db.add(Quest(
                id=f"steam_{item.section_id}",
                name=item.title,
                steps=item.steps,
                locations=[game_map.id] if game_map else [],
                steam_url=url,
            ))
            added += 1
        return added

    def load_steam_guide(self):
        quest = self.card.quest
        section = guide.steam_section_id(quest.steam_url) if quest else None
        if not section or section in self.steam_pages:
            self.steam_status = ""
            return
        if self.steam_html is None:
            self.steam_status = (f"Гайд из Steam не загрузился — открой его в браузере ({shortcuts.key('open_browser')})"
                                 if self._steam_sync_done else "Загружаю гайд из Steam…")
            return
        pages = guide.parse_steam_section(self.steam_html, section)
        self.steam_pages[section] = pages
        self.steam_status = "" if pages else (f"Раздел не найден в руководстве Steam — открой его в браузере "
                                              f"({shortcuts.key('open_browser')})")

    def open_guide_in_browser(self):
        quest = self.card.quest
        if quest:
            self._open(quest.steam_url or quest.video_url)

    def _open(self, url: str | None):
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def on_submitted(self, quest_name: str):
        quest = self.db.find(quest_name)
        if quest is None:
            examples = ", ".join(self.db.names()[:3])
            self.input.show_error(f"Квест «{quest_name.strip()}» не найден в базе. Например: {examples}.")
            return
        self.progress.add(quest)
        self.progress.save()
        self.show_current()
        self.set_card_visible(True)
        self.input.close_and_return_focus()


def self_test() -> int:
    """Проверка собранного .exe без окон: база читается, HTTPS доступен. Код возврата 0 — всё в порядке."""
    from PyQt6.QtNetwork import QSslSocket

    db = QuestDB.load()
    ok = len(db.quests) >= 100 and QSslSocket.supportsSsl()
    print(f"квестов: {len(db.quests)}, HTTPS: {QSslSocket.supportsSsl()}")
    return 0 if ok else 1


def ocr_self_test() -> int:
    """Проверка распознавания в собранном .exe: рисуем названия квестов и распознаём их."""
    from PyQt6.QtGui import QImage

    image = QImage(1400, 300, QImage.Format.Format_RGB32)
    image.fill(QColor("#15181e"))
    painter = QPainter(image)
    painter.setPen(QColor("#f0f0f0"))
    painter.setFont(QFont("Arial", 28))
    painter.drawText(40, 100, "Greasing Her Palms")
    painter.drawText(40, 200, "What Goes Around")
    painter.end()
    result: dict = {}
    thread = screen_import.RecognizeThread(image, paths.cache_dir() / "ocr-test.png")
    thread.recognized.connect(lambda lines: result.update(lines=lines), Qt.ConnectionType.DirectConnection)
    thread.failed.connect(lambda message: result.update(error=message), Qt.ConnectionType.DirectConnection)
    thread.start()
    if not thread.wait(60_000):
        print("распознавание зависло")
        return 1
    if "error" in result:
        print(f"распознавание недоступно: {result['error']}")
        return 1
    lines = result.get("lines", [])
    found = screen_import.match_quests(QuestDB.load(), lines)
    print(f"строки: {lines}; квесты: {[q.english_name for q in found]}")
    return 0 if len(found) >= 2 else 1


def _log_unhandled(exc_type, exc, tb):
    """Ошибка в обработчике Qt иначе закрыла бы программу без следа: пишем её в «Данные\\ошибки.log»."""
    import datetime
    import traceback

    text = "".join(traceback.format_exception(exc_type, exc, tb))
    print(text, file=sys.stderr)
    try:
        log = paths.user_data_dir() / "ошибки.log"
        if log.exists() and log.stat().st_size > 1_000_000:
            log.unlink()  # не даём журналу разрастись
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n{text}\n")
    except OSError:
        pass


def main() -> int:
    if "--ocr-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication(sys.argv)
        code = ocr_self_test()
        sys.stdout.flush()
        # Зависший вызов Windows в фоновом потоке не даёт процессу завершиться обычным путём.
        os._exit(code)
    if "--self-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication(sys.argv)
        return self_test()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # окна прячутся, но программа живёт в трее
    # Вторая копия программы делила бы горячие клавиши с первой — не запускаем её.
    lock = QLockFile(str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation))
                         / "arc_raiders_overlay.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "ARC Raiders — подсказчик",
                                "Программа уже запущена — её значок «?» в трее рядом с часами.")
        return 0
    paths.migrate_legacy()
    sys.excepthook = _log_unhandled  # с ним PyQt не завершает программу при ошибке в обработчике
    _overlay = OverlayApp(app)
    return app.exec()

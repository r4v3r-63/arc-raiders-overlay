"""Точка входа: связывает базу квестов, карточку, окно ввода, горячие клавиши и трей."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile, QStandardPaths, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import autostart, guide, paths, winapi
from .input_window import InputWindow
from .net import CachedDownloader
from .overlay import OverlayCard
from .quest_db import REMOTE_DATA_URL, Quest, QuestDB

MODS = winapi.MOD_CONTROL | winapi.MOD_SHIFT
HOTKEY_INPUT = "Ctrl+Shift+Q"
GUIDE_HINT = "Ctrl+Shift+G — гайд со скриншотами"
STEAM_GUIDE_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id=3672641520"
STEAM_MAX_AGE = 24 * 60 * 60  # руководство перекачивается раз в сутки
REMOTE_DB_URL = REMOTE_DATA_URL + "quests.json"
DB_MAX_AGE = 24 * 60 * 60  # свежая база с GitHub скачивается раз в сутки
SYNC_CHECK_INTERVAL_MS = 60 * 60 * 1000  # раз в час проверяем, не пора ли обновить


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
        self.card = OverlayCard(self.db, HOTKEY_INPUT, GUIDE_HINT)
        self.downloader = CachedDownloader()
        self.downloader.cleanup()
        self.guide_mode = False
        self.pages: list[guide.GuidePage] = []
        self.page_index = 0
        self.steam_pages: dict[str, list[guide.GuidePage]] = {}  # id раздела → страницы
        self.steam_status = ""
        self.steam_html: str | None = None
        self._steam_sync_done = False
        self.input = InputWindow()
        self.input.submitted.connect(self.on_submitted)
        self.input.help_requested.connect(self.show_help)

        self.hotkeys = winapi.HotkeyManager()
        app.installNativeEventFilter(self.hotkeys)
        failed = [
            name
            for name, vk, callback in [
                (HOTKEY_INPUT, winapi.VK_Q, self.input.open),
                ("Ctrl+Shift+→", winapi.VK_RIGHT, self.next_step),
                ("Ctrl+Shift+←", winapi.VK_LEFT, self.prev_step),
                ("Ctrl+Shift+X", winapi.VK_X, self.toggle_card),
                ("Ctrl+Shift+G", winapi.VK_G, self.toggle_guide),
                ("Ctrl+Shift+↓", winapi.VK_DOWN, self.next_page),
                ("Ctrl+Shift+↑", winapi.VK_UP, self.prev_page),
                ("Ctrl+Shift+O", winapi.VK_O, self.open_guide_in_browser),
                ("Ctrl+Shift+M", winapi.VK_M, self.toggle_editing),
                ("Ctrl+Shift+H", winapi.VK_H, self.show_help),
            ]
            if not self.hotkeys.register(MODS, vk, callback)
        ]
        app.aboutToQuit.connect(self.hotkeys.unregister_all)

        self.tray = self._make_tray()
        autostart.refresh()
        self.sync()
        self._sync_timer = QTimer()
        self._sync_timer.timeout.connect(self.sync)
        self._sync_timer.start(SYNC_CHECK_INTERVAL_MS)
        self.card.show()

        if not winapi.IS_WINDOWS:
            # Без Windows глобальных клавиш нет — сразу открываем ввод для проверки.
            self.input.open()
        elif failed:
            QMessageBox.warning(
                None,
                "Горячие клавиши",
                "Не удалось занять клавиши: " + ", ".join(failed)
                + ".\nВозможно, их уже использует другая программа. Ввод квеста доступен через значок в трее.",
            )

    def _make_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(make_tray_icon(), self.app)
        tray.setToolTip("ARC Raiders — подсказчик\nCtrl+Shift+H — все сочетания клавиш")
        menu = QMenu()
        enter = QAction("Ввести квест", menu)
        enter.triggered.connect(self.input.open)
        help_action = QAction("Сочетания клавиш (?)", menu)
        help_action.triggered.connect(self.show_help)
        edit_action = QAction("Переместить / изменить масштаб", menu)
        edit_action.triggered.connect(self.toggle_editing)
        self._toggle_action = QAction("Спрятать карточку", menu)
        self._toggle_action.triggered.connect(self.toggle_card)
        self._quest_actions = []
        for title, handler in [
            ("Гайд со скриншотами", self.toggle_guide),
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
        self._clear_cache_action = QAction("Очистить кэш", menu)
        self._clear_cache_action.triggered.connect(self.clear_cache)
        menu.aboutToShow.connect(self._update_cache_label)
        quit_action = QAction("Выход", menu)
        quit_action.triggered.connect(self.app.quit)
        menu.addAction(enter)
        menu.addAction(self._toggle_action)
        menu.addAction(edit_action)
        menu.addAction(help_action)
        menu.addSeparator()
        for action in self._quest_actions:
            menu.addAction(action)
        menu.addSeparator()
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
        self.card.setVisible(visible)
        self._toggle_action.setText("Спрятать карточку" if visible else "Показать карточку")

    def toggle_card(self):
        if self.card.editing:
            self.card.set_editing(False)
        self.set_card_visible(not self.card.isVisible())

    def toggle_editing(self):
        self.set_card_visible(True)
        self.card.toggle_editing()

    def show_help(self):
        self.card.toggle_help()
        self.set_card_visible(True)

    def next_step(self):
        self.guide_mode = False
        self.card.next_step()
        self.set_card_visible(True)

    def prev_step(self):
        self.guide_mode = False
        self.card.prev_step()
        self.set_card_visible(True)

    # --- гайд -------------------------------------------------------------

    def toggle_guide(self):
        if self.card.quest is None:
            return
        self.guide_mode = not self.guide_mode
        if self.guide_mode:
            self.render_page()
        else:
            self.card.show_step()
        self.set_card_visible(True)

    def next_page(self):
        self._turn_page(+1)

    def prev_page(self):
        self._turn_page(-1)

    def _turn_page(self, delta: int):
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
            return
        if page.image.startswith("http"):
            self.card.set_image(None, "Загружаю скриншот…")
            self.downloader.get(page.image, lambda path, p=page: self._image_ready(p, path))
        else:
            self.card.set_image(QPixmap(page.image))

    def _image_ready(self, page: guide.GuidePage, path):
        if self.guide_mode and self.pages and self.pages[self.page_index] is page:
            self.card.set_image(QPixmap(str(path)) if path else None, "" if path else "Скриншот не загрузился")

    def sync(self):
        self.sync_db()
        self.sync_steam_guide()

    def sync_db(self):
        """Скачивает свежую базу квестов с GitHub (её раз в сутки пересобирает GitHub Actions)."""
        self.downloader.get(REMOTE_DB_URL, self._remote_db_loaded, max_age=DB_MAX_AGE)

    def _remote_db_loaded(self, path):
        if not path:
            return
        try:
            remote = QuestDB.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError, AttributeError):
            return  # битый или чужой файл — остаёмся на текущей базе
        if len(remote.quests) < 50 or remote.generated_at <= self.db.generated_at:
            return
        self.db = remote
        self.card.set_db(remote)
        self.merge_steam_quests()

    def sync_steam_guide(self):
        """Скачивает руководство Steam (не чаще раза в сутки) и добавляет в поиск новые квесты из него."""
        self.downloader.get(STEAM_GUIDE_URL, self._steam_guide_loaded, max_age=STEAM_MAX_AGE)

    def _steam_guide_loaded(self, path):
        self._steam_sync_done = True
        if path:
            page_html = path.read_text(encoding="utf-8", errors="replace")
            if page_html != self.steam_html:
                self.steam_html = page_html
                self.steam_pages.clear()
                self.merge_steam_quests()
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
                quest.steam_url = quest.steam_url or url
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
            self.steam_status = ("Гайд из Steam не загрузился — открой его в браузере (Ctrl+Shift+O)"
                                 if self._steam_sync_done else "Загружаю гайд из Steam…")
            return
        pages = guide.parse_steam_section(self.steam_html, section)
        self.steam_pages[section] = pages
        self.steam_status = "" if pages else "Раздел не найден в руководстве Steam — открой его в браузере (Ctrl+Shift+O)"

    def open_guide_in_browser(self):
        quest = self.card.quest
        if quest:
            self._open(quest.steam_url or quest.video_url)

    def _open(self, url: str | None):
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def on_submitted(self, quest_name: str, location: str):
        quest = self.db.find(quest_name)
        if quest is None:
            examples = ", ".join(self.db.names()[:3])
            self.input.show_error(f"Квест «{quest_name.strip()}» не найден в базе. Например: {examples}.")
            return
        self.card.show_quest(quest, location)
        self.guide_mode = False
        self.page_index = 0
        for action in self._quest_actions:
            action.setEnabled(True)
        self.load_steam_guide()
        self.rebuild_pages()
        self.set_card_visible(True)
        self.input.close_and_return_focus()


def self_test() -> int:
    """Проверка собранного .exe без окон: база читается, HTTPS доступен. Код возврата 0 — всё в порядке."""
    from PyQt6.QtNetwork import QSslSocket

    db = QuestDB.load()
    ok = len(db.quests) >= 100 and QSslSocket.supportsSsl()
    print(f"квестов: {len(db.quests)}, HTTPS: {QSslSocket.supportsSsl()}")
    return 0 if ok else 1


def main() -> int:
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
    _overlay = OverlayApp(app)
    return app.exec()

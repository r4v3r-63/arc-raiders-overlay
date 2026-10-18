"""Точка входа: связывает базу квестов, карточку, окно ввода, горячие клавиши и трей."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile, QStandardPaths, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import autostart, guide, paths, winapi
from .progress import Progress
from . import screen_import
from .input_window import InputWindow
from .net import CachedDownloader
from .onboarding import OnboardingWindow
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
        self.progress = Progress.load(paths.user_data_dir() / "прогресс.json")
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
        self.input.set_suggester(lambda text: self.db.suggest(text))

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
                ("Ctrl+Shift+Tab", winapi.VK_TAB, self.switch_quest),
                ("Ctrl+Shift+D", winapi.VK_D, self.complete_quest),
                ("Ctrl+Shift+I", winapi.VK_I, self.import_from_screen),
                ("Ctrl+Shift+H", winapi.VK_H, self.show_help),
            ]
            if not self.hotkeys.register(MODS, vk, callback)
        ]
        app.aboutToQuit.connect(self.hotkeys.unregister_all)

        self.tray = self._make_tray()
        autostart.refresh()
        self.show_current()
        self.sync()

        self.settings = paths.settings()
        self.onboarding = OnboardingWindow()
        self.onboarding.finished.connect(self._onboarding_finished)
        if not self.settings.value("onboarding_done", False, type=bool):
            self.onboarding.open()
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
        tour_action = QAction("Как пользоваться", menu)
        tour_action.triggered.connect(lambda: self.onboarding.open())
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
        self._active_menu = menu.addMenu("Активные квесты")
        self._active_menu.aboutToShow.connect(self._fill_active_menu)
        import_action = QAction("Найти квесты на экране (Ctrl+Shift+I)", menu)
        import_action.triggered.connect(self.import_from_screen)
        menu.addAction(import_action)
        menu.addAction(self._toggle_action)
        menu.addAction(edit_action)
        menu.addAction(help_action)
        menu.addAction(tour_action)
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
        self._save_step()
        self.set_card_visible(True)

    def prev_step(self):
        self.guide_mode = False
        self.card.prev_step()
        self._save_step()
        self.set_card_visible(True)

    def _save_step(self):
        if self.card.quest is not None:
            self.progress.set_step(self.card.step)
            self.progress.save()

    # --- активные квесты --------------------------------------------------

    def _onboarding_finished(self):
        self.settings.setValue("onboarding_done", True)
        self.settings.sync()

    def show_current(self, notice: str = ""):
        """Показывает текущий активный квест (или приглашение ввести квест, если список пуст)."""
        entry = self.progress.current_entry()
        quest = self.progress.resolve(self.db, entry)
        self.guide_mode = False
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
                         + ". Нужные возьми через Ctrl+Shift+Q.")
        self.show_current("\n".join(lines))
        self.set_card_visible(True)

    def remove_quest(self):
        entry = self.progress.remove_current()
        if entry is not None:
            self.progress.save()
            self.show_current(f"«{entry.name}» убран из списка.")
            self.set_card_visible(True)

    # --- импорт квестов с экрана --------------------------------------------

    def import_from_screen(self):
        """Снимок экрана → распознавание → найденные квесты в список активных."""
        if getattr(self, "_recognizer", None) is not None and self._recognizer.isRunning():
            return
        self.card.hide()  # своя карточка не должна попасть в снимок
        self.input.hide()
        QTimer.singleShot(200, self._grab_screen)

    def _grab_screen(self):
        screen = QGuiApplication.primaryScreen()
        image = screen.grabWindow(0).toImage()
        # Мелкий текст распознаётся лучше, если картинку немного увеличить.
        limit = screen_import.max_image_dimension()
        factor = min(1.5, limit / max(image.width(), image.height(), 1))
        if factor > 1.05 or factor < 1:
            image = image.scaled(int(image.width() * factor), int(image.height() * factor),
                                 Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        path = paths.cache_dir() / "экран.png"
        image.save(str(path))
        self.card.setVisible(True)
        self._show_notice("Ищу квесты на экране…")
        self._recognizer = screen_import.RecognizeThread(path)
        self._recognizer.recognized.connect(self._screen_recognized)
        self._recognizer.failed.connect(lambda message: self._show_notice(message))
        self._recognizer.start()

    def _screen_recognized(self, lines: list):
        found = screen_import.match_quests(self.db, lines)
        if not found:
            self._show_notice("Квесты на экране не найдены. Откройте в игре экран, где виден список квестов "
                              "(например, лобби), и нажмите Ctrl+Shift+I ещё раз.")
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

    def _show_notice(self, text: str):
        """Сообщение на карточке поверх текущего квеста (или приглашения)."""
        entry = self.progress.current_entry()
        quest = self.progress.resolve(self.db, entry)
        if quest is None:
            self.card.show_welcome(text)
        else:
            self.card.show_quest(quest, entry.step, (self.progress.current, len(self.progress.active)), text)
        self.guide_mode = False
        self.set_card_visible(True)

    def _fill_active_menu(self):
        self._active_menu.clear()
        if not self.progress.active:
            empty = self._active_menu.addAction("Пока пусто — Ctrl+Shift+Q")
            empty.setEnabled(False)
            return
        for i, entry in enumerate(self.progress.active):
            action = self._active_menu.addAction(entry.name)
            action.setCheckable(True)
            action.setChecked(i == self.progress.current)
            action.triggered.connect(lambda _checked, i=i: self.select_quest(i))
        self._active_menu.addSeparator()
        self._active_menu.addAction("Квест выполнен (Ctrl+Shift+D)", self.complete_quest)
        self._active_menu.addAction("Убрать текущий квест из списка", self.remove_quest)

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
                if self.card.quest is None and self.progress.active:
                    self.show_current()  # текущий квест мог оказаться из руководства Steam
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
    path = paths.cache_dir() / "ocr-test.png"
    image.save(str(path))
    try:
        lines = screen_import.recognize_file(path)
    except screen_import.OcrUnavailable as error:
        print(f"распознавание недоступно: {error}")
        return 1
    found = screen_import.match_quests(QuestDB.load(), lines)
    print(f"строки: {lines}; квесты: {[q.english_name for q in found]}")
    return 0 if len(found) >= 2 else 1


def main() -> int:
    if "--ocr-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication(sys.argv)
        return ocr_self_test()
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

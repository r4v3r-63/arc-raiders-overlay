"""Точка входа: связывает базу квестов, карточку, окно ввода, горячие клавиши и трей."""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import winapi
from .input_window import InputWindow
from .overlay import OverlayCard
from .quest_db import QuestDB

MODS = winapi.MOD_CONTROL | winapi.MOD_SHIFT
HOTKEY_INPUT = "Ctrl+Shift+Q"
HOTKEY_HELP = (
    f"{HOTKEY_INPUT} — ввести квест\n"
    "Ctrl+Shift+→ / ← — следующий / предыдущий шаг\n"
    "Ctrl+Shift+End — выход"
)


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
        self.card = OverlayCard(self.db, HOTKEY_INPUT)
        self.input = InputWindow()
        self.input.submitted.connect(self.on_submitted)

        self.hotkeys = winapi.HotkeyManager()
        app.installNativeEventFilter(self.hotkeys)
        failed = [
            name
            for name, vk, callback in [
                (HOTKEY_INPUT, winapi.VK_Q, self.input.open),
                ("Ctrl+Shift+→", winapi.VK_RIGHT, self.card.next_step),
                ("Ctrl+Shift+←", winapi.VK_LEFT, self.card.prev_step),
                ("Ctrl+Shift+End", winapi.VK_END, app.quit),
            ]
            if not self.hotkeys.register(MODS, vk, callback)
        ]
        app.aboutToQuit.connect(self.hotkeys.unregister_all)

        self.tray = self._make_tray()
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
        tray.setToolTip("ARC Raiders — подсказчик\n" + HOTKEY_HELP)
        menu = QMenu()
        enter = QAction("Ввести квест", menu)
        enter.triggered.connect(self.input.open)
        quit_action = QAction("Выход", menu)
        quit_action.triggered.connect(self.app.quit)
        menu.addAction(enter)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.show()
        self._tray_menu = menu  # держим ссылку, иначе меню удалит сборщик мусора
        return tray

    def on_submitted(self, quest_name: str, location: str):
        quest = self.db.find(quest_name)
        if quest is None:
            examples = ", ".join(self.db.names()[:3])
            self.input.show_error(f"Квест «{quest_name.strip()}» не найден в базе. Например: {examples}.")
            return
        self.card.show_quest(quest, location)
        self.input.close_and_return_focus()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # окна прячутся, но программа живёт в трее
    _overlay = OverlayApp(app)
    return app.exec()

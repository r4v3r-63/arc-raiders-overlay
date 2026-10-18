"""Окно ввода квеста и локации. Только оно забирает фокус, и только на время ввода."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeyEvent
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from . import winapi


class InputWindow(QWidget):
    # Отправляется после Enter: (название квеста, локация).
    submitted = pyqtSignal(str, str)
    help_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setWindowTitle("Ввод квеста")
        self.setFixedWidth(420)
        self.setStyleSheet(
            "QWidget { background: #1b1f27; color: #f0f0f0; font-size: 14px; }"
            "QLineEdit { background: #2a303b; border: 1px solid #3a4250; border-radius: 4px; padding: 6px; }"
            "QLineEdit:focus { border-color: #f2c94c; }"
        )

        self.quest_edit = QLineEdit()
        self.quest_edit.setPlaceholderText("например, Чистое небо")
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("необязательно, например, Космопорт")
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #ff8a65;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        hint = QLabel("Enter — показать подсказку · Esc — отмена")
        hint.setStyleSheet("color: #a8adb5; font-size: 12px;")
        help_button = QPushButton("?")
        help_button.setToolTip("Все сочетания клавиш")
        help_button.setFixedWidth(28)
        help_button.setStyleSheet(
            "QPushButton { background: #2a303b; border: 1px solid #3a4250; border-radius: 4px; padding: 2px; }"
            "QPushButton:hover { border-color: #f2c94c; }"
        )
        help_button.clicked.connect(self.help_requested.emit)
        bottom = QHBoxLayout()
        bottom.addWidget(hint)
        bottom.addStretch()
        bottom.addWidget(help_button)

        form = QFormLayout()
        form.addRow("Квест:", self.quest_edit)
        form.addRow("Локация:", self.location_edit)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addLayout(bottom)

        self._previous_window = None

    def open(self):
        """Показывает окно и забирает фокус, запомнив, какое окно (игра) было активно."""
        self._previous_window = winapi.get_foreground_window()
        self.error_label.hide()
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.top() + screen.height() // 4)
        self.show()
        self.raise_()
        self.activateWindow()
        winapi.set_foreground_window(int(self.winId()))
        self.quest_edit.setFocus()
        self.quest_edit.selectAll()

    def show_error(self, text: str):
        self.error_label.setText(text)
        self.error_label.show()
        self.adjustSize()
        self.quest_edit.setFocus()
        self.quest_edit.selectAll()

    def close_and_return_focus(self):
        self.hide()
        winapi.set_foreground_window(self._previous_window)
        self._previous_window = None

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.submitted.emit(self.quest_edit.text(), self.location_edit.text())
        elif event.key() == Qt.Key.Key_Escape:
            self.close_and_return_focus()
        else:
            super().keyPressEvent(event)

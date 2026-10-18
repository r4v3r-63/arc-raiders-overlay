"""Окно ввода названия квеста. Только оно забирает фокус, и только на время ввода."""

from __future__ import annotations

from PyQt6.QtCore import QStringListModel, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeyEvent
from PyQt6.QtWidgets import (QCompleter, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                             QWidget)

from . import winapi


class InputWindow(QWidget):
    # Отправляется после Enter: название квеста.
    submitted = pyqtSignal(str)
    help_requested = pyqtSignal()

    def __init__(self, title: str = "Ввод квеста", label: str = "Квест:", example: str = "например, Чистое небо"):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setWindowTitle(title)
        self.setFixedWidth(420)
        self.setStyleSheet(
            "QWidget { background: #1b1f27; color: #f0f0f0; font-size: 14px; }"
            "QLineEdit { background: #2a303b; border: 1px solid #3a4250; border-radius: 4px; padding: 6px; }"
            "QLineEdit:focus { border-color: #f2c94c; }"
        )

        self.quest_edit = QLineEdit()
        self.quest_edit.setPlaceholderText(example)
        self._quest_suggest = lambda text: []
        self._attach_completer(self.quest_edit, lambda text: self._quest_suggest(text))
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
        form.addRow(label, self.quest_edit)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addLayout(bottom)

        self._previous_window = None

    def set_suggester(self, quests):
        """quests(text) возвращает варианты для выпадающего списка."""
        self._quest_suggest = quests

    def _attach_completer(self, edit: QLineEdit, suggest):
        model = QStringListModel(self)
        completer = QCompleter(model, self)
        # Список подбираем сами (без учёта «ё», регистра и кавычек), QCompleter только показывает его.
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setMaxVisibleItems(10)
        completer.popup().setStyleSheet(
            "QListView { background: #2a303b; color: #f0f0f0; border: 1px solid #3a4250; font-size: 14px; }"
            "QListView::item { padding: 4px 6px; }"
            "QListView::item:selected { background: #f2c94c; color: #15181e; }"
        )
        edit.setCompleter(completer)

        def update(text: str):
            options = suggest(text)
            model.setStringList(options)
            if options and not (len(options) == 1 and options[0] == text):
                completer.complete()
            else:
                completer.popup().hide()

        edit.textEdited.connect(update)

    def open(self):
        """Показывает окно и забирает фокус, запомнив, какое окно (игра) было активно."""
        if not self.isVisible():  # повторное нажатие не должно запомнить само окно ввода вместо игры
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
            self.submitted.emit(self.quest_edit.text())
        elif event.key() == Qt.Key.Key_Escape:
            self.close_and_return_focus()
        else:
            super().keyPressEvent(event)

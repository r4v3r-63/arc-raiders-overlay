"""Окно «Горячие клавиши»: игрок меняет сочетание любого действия."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QCursor, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from . import shortcuts

ACCENT = "#f2c94c"
MUTED = "#a8adb5"
ERROR = "#ff8a65"


class HotkeysWindow(QWidget):
    saved = pyqtSignal(dict)  # {id действия: сочетание}
    closed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Горячие клавиши — ARC Raiders")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(
            "QWidget { background: #1b1f27; color: #f0f0f0; font-size: 14px; }"
            "QKeySequenceEdit QLineEdit { background: #2a303b; border: 1px solid #3a4250; border-radius: 4px;"
            " padding: 4px 6px; }"
            "QKeySequenceEdit QLineEdit:focus { border-color: #f2c94c; }"
            "QPushButton { background: #2a303b; border: 1px solid #3a4250; border-radius: 4px; padding: 5px 12px; }"
            "QPushButton:hover { border-color: #f2c94c; }"
            "QPushButton#primary { background: #f2c94c; color: #15181e; border-color: #f2c94c; font-weight: bold; }"
        )
        title = QLabel("Горячие клавиши")
        title.setStyleSheet(f"color: {ACCENT}; font-size: 18px; font-weight: bold;")
        hint = QLabel("Нажмите на поле и затем нужное сочетание. Нужна хотя бы одна из клавиш Ctrl, Alt, Shift "
                      "или Win — иначе сочетание мешало бы играть.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED}; font-size: 12px;")

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self._edits: dict[str, QKeySequenceEdit] = {}
        for row, (action, default, text) in enumerate(shortcuts.ACTIONS):
            label = QLabel(text[:1].upper() + text[1:])
            label.setWordWrap(True)
            edit = QKeySequenceEdit()
            edit.setMaximumSequenceLength(1)
            edit.setFixedWidth(170)
            edit.keySequenceChanged.connect(self._validate)
            reset = QPushButton("↺")
            reset.setToolTip(f"По умолчанию: {shortcuts.pretty(default)}")
            reset.setFixedWidth(34)
            reset.clicked.connect(lambda _checked, e=edit, d=default: e.setKeySequence(QKeySequence(d)))
            grid.addWidget(label, row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(reset, row, 2)
            self._edits[action] = edit
        grid.setColumnStretch(0, 1)

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setStyleSheet(f"color: {ERROR};")
        self._error.hide()

        reset_all = QPushButton("Всё по умолчанию")
        reset_all.clicked.connect(self._reset_all)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.close)
        self._save = QPushButton("Сохранить")
        self._save.setObjectName("primary")
        self._save.clicked.connect(self._on_save)
        buttons = QHBoxLayout()
        buttons.addWidget(reset_all)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self._save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(hint)
        # Список сочетаний прокручивается, если экран невысокий; ошибки и кнопки всегда видны.
        rows = QWidget()
        rows.setLayout(grid)
        self._scroll = QScrollArea()
        self._scroll.setWidget(rows)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._error)
        layout.addLayout(buttons)
        self.setMinimumWidth(620)

    def open(self, bindings: dict[str, str]):
        for action, edit in self._edits.items():
            edit.setKeySequence(QKeySequence(bindings.get(action, shortcuts.DEFAULTS[action])))
        self._validate()
        # Высота по содержимому, но не больше экрана: остальное прокручивается.
        screen = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        wanted = self._scroll.widget().sizeHint().height() + 220
        self.resize(self.width(), min(wanted, int(screen.height() * 0.9)))
        self.show()
        self.raise_()
        self.activateWindow()

    def current(self) -> dict[str, str]:
        return {action: edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                for action, edit in self._edits.items()}

    def problems(self) -> list[str]:
        """Что мешает сохранить: пустые, неподходящие и повторяющиеся сочетания."""
        issues = []
        seen: dict[str, str] = {}
        for action, sequence in self.current().items():
            name = shortcuts.DESCRIPTIONS[action]
            if not sequence:
                issues.append(f"не задано: «{name}»")
            elif shortcuts.to_native(sequence) is None:
                issues.append(f"{shortcuts.pretty(sequence)} не подходит («{name}»): нужна клавиша "
                              f"с Ctrl, Alt, Shift или Win")
            elif sequence in seen:
                issues.append(f"{shortcuts.pretty(sequence)} назначено дважды: «{seen[sequence]}» и «{name}»")
            else:
                seen[sequence] = name
        return issues

    def _validate(self):
        issues = self.problems()
        self._error.setText("\n".join(issues))
        self._error.setVisible(bool(issues))
        self._save.setEnabled(not issues)

    def _reset_all(self):
        for action, edit in self._edits.items():
            edit.setKeySequence(QKeySequence(shortcuts.DEFAULTS[action]))

    def _on_save(self):
        if not self.problems():
            self.saved.emit(self.current())
            self.close()

    def closeEvent(self, event: QCloseEvent):
        super().closeEvent(event)
        self.closed.emit()

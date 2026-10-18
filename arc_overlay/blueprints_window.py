"""Окно «Чертежи»: игрок отмечает, какие чертежи уже изучил."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from .quest_db import QuestDB, normalize

ACCENT = "#f2c94c"
MUTED = "#a8adb5"


class BlueprintsWindow(QWidget):
    changed = pyqtSignal(set)  # id изученных чертежей

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Чертежи — ARC Raiders")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(
            "QWidget { background: #1b1f27; color: #f0f0f0; font-size: 14px; }"
            "QLineEdit, QListWidget { background: #2a303b; border: 1px solid #3a4250; border-radius: 4px; padding: 4px; }"
            "QLineEdit:focus { border-color: #f2c94c; }"
            "QPushButton { background: #2a303b; border: 1px solid #3a4250; border-radius: 4px; padding: 5px 12px; }"
            "QPushButton:hover { border-color: #f2c94c; }"
        )
        title = QLabel("Изученные чертежи")
        title.setStyleSheet(f"color: {ACCENT}; font-size: 18px; font-weight: bold;")
        hint = QLabel("Отметьте чертежи, которые уже изучили. Тогда проверка предмета подскажет, "
                      "забрать найденный чертёж или его можно продать. Сохраняется сразу.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Поиск по названию")
        self._filter.textChanged.connect(self._apply_filter)
        self._list = QListWidget()
        self._list.itemChanged.connect(self._item_changed)
        self._counter = QLabel()
        self._counter.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        close = QPushButton("Готово")
        close.clicked.connect(self.close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self._filter)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._counter)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(520, 640)
        self._filling = False

    def open(self, db: QuestDB, learned: set[str]):
        self._filling = True
        self._list.clear()
        blueprints = sorted((i for i in db.items.values() if i.unlocks), key=lambda i: i.name.lower())
        for blueprint in blueprints:
            row = QListWidgetItem(blueprint.name)
            row.setData(Qt.ItemDataRole.UserRole, blueprint.id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked if blueprint.id in learned else Qt.CheckState.Unchecked)
            self._list.addItem(row)
        self._filling = False
        self._filter.clear()
        self._update_counter()
        self.show()
        self.raise_()
        self.activateWindow()
        self._filter.setFocus()

    def learned(self) -> set[str]:
        return {self._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.CheckState.Checked}

    def _apply_filter(self, text: str):
        query = normalize(text)
        for i in range(self._list.count()):
            row = self._list.item(i)
            row.setHidden(bool(query) and query not in normalize(row.text()))

    def _item_changed(self, _row):
        if not self._filling:
            self._update_counter()
            self.changed.emit(self.learned())

    def _update_counter(self):
        self._counter.setText(f"Изучено: {len(self.learned())} из {self._list.count()}")

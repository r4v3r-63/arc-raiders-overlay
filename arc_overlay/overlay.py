"""Полупрозрачная карточка с подсказкой поверх игры. Клики проходят сквозь неё."""

from __future__ import annotations

import html

from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .quest_db import Quest

CARD_WIDTH = 380
SCREEN_MARGIN = 24
BACKGROUND = QColor(15, 18, 24, 190)  # последний параметр — непрозрачность (0–255)
ACCENT = "#f2c94c"
TEXT = "#f0f0f0"
MUTED = "#a8adb5"
WARNING = "#ff8a65"


class OverlayCard(QWidget):
    def __init__(self, hotkey_hint: str):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # не показывать на панели задач
            | Qt.WindowType.WindowTransparentForInput  # клики уходят в игру
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(CARD_WIDTH)

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setStyleSheet(f"color: {TEXT}; font-size: 14px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.addWidget(self._label)

        self._hotkey_hint = hotkey_hint
        self._quest: Quest | None = None
        self._location = ""
        self._step = 0
        self.show_welcome()

    # --- содержимое -------------------------------------------------------

    def show_welcome(self):
        self._quest = None
        self._set_html(
            f"<div style='color:{ACCENT}; font-size:16px; font-weight:bold;'>ARC Raiders — подсказчик</div>"
            f"<p>Нажми <b>{html.escape(self._hotkey_hint)}</b>, чтобы ввести квест.</p>"
        )

    def show_quest(self, quest: Quest, location: str = ""):
        self._quest = quest
        self._location = location.strip()
        self._step = 0
        self._render_quest()

    def next_step(self):
        if self._quest and self._step < len(self._quest.steps) - 1:
            self._step += 1
            self._render_quest()

    def prev_step(self):
        if self._quest and self._step > 0:
            self._step -= 1
            self._render_quest()

    def _render_quest(self):
        q = self._quest
        esc = html.escape
        parts = [f"<div style='color:{ACCENT}; font-size:16px; font-weight:bold;'>{esc(q.name)}</div>"]
        meta = []
        if q.trader:
            meta.append(f"Торговец: {esc(q.trader)}")
        if self._location:
            meta.append(f"Локация: {esc(self._location)}")
        if meta:
            parts.append(f"<div style='color:{MUTED};'>{' · '.join(meta)}</div>")
        if not q.available_at(self._location):
            places = ", ".join(q.locations)
            parts.append(f"<p style='color:{WARNING};'>Этот квест выполняется на: {esc(places)}</p>")
        if q.steps:
            parts.append(
                f"<p><span style='color:{MUTED};'>Шаг {self._step + 1} из {len(q.steps)}</span><br>"
                f"<span style='font-size:15px;'>{esc(q.steps[self._step])}</span></p>"
            )
        else:
            parts.append(f"<p style='color:{MUTED};'>Для этого квеста в базе нет шагов.</p>")
        if q.required_items:
            parts.append(f"<div style='color:{MUTED};'>Нужно: {esc(', '.join(q.required_items))}</div>")
        self._set_html("".join(parts))

    def _set_html(self, text: str):
        self._label.setText(text)
        # Высоту считаем от фиксированной ширины, иначе перенос строк обрезает низ карточки.
        self.setFixedHeight(self.layout().heightForWidth(CARD_WIDTH))
        self._move_to_corner()

    # --- внешний вид ------------------------------------------------------

    def _move_to_corner(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(QPoint(screen.right() - self.width() - SCREEN_MARGIN, screen.top() + SCREEN_MARGIN))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.fillPath(path, BACKGROUND)

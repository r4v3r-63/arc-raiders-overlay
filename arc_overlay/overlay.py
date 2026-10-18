"""Полупрозрачная карточка с подсказкой поверх игры. Клики проходят сквозь неё.

Два режима: шаг квеста (узкая карточка) и гайд (шире, с текстом и скриншотом).
"""

from __future__ import annotations

import html

from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .guide import GuidePage
from .quest_db import Quest, QuestDB

CARD_WIDTH = 380
GUIDE_MAX_WIDTH = 640
SCREEN_MARGIN = 24
BACKGROUND = QColor(15, 18, 24, 190)  # последний параметр — непрозрачность (0–255)
ACCENT = "#f2c94c"
TEXT = "#f0f0f0"
MUTED = "#a8adb5"
WARNING = "#ff8a65"
GUIDE_NAV_HINT = "Ctrl+Shift+↑ / ↓ — листать · Ctrl+Shift+G — назад к шагу"


def _lines(text: str) -> str:
    return "<br>".join(html.escape(line) for line in text.splitlines())


class OverlayCard(QWidget):
    def __init__(self, db: QuestDB, hotkey_hint: str, guide_hint: str = ""):
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

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setStyleSheet(f"color: {TEXT}; font-size: 14px;")
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.hide()
        self._footer = QLabel()
        self._footer.setTextFormat(Qt.TextFormat.RichText)
        self._footer.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        self._footer.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        layout.addWidget(self._label)
        layout.addWidget(self._image)
        layout.addWidget(self._footer)

        self._db = db
        self._hotkey_hint = hotkey_hint
        self._guide_hint = guide_hint
        self._quest: Quest | None = None
        self._location = ""
        self._step = 0
        self._width = CARD_WIDTH
        self.show_welcome()

    @property
    def quest(self) -> Quest | None:
        return self._quest

    # --- режим шага -------------------------------------------------------

    def show_welcome(self):
        self._quest = None
        self._set_content(
            f"<div style='color:{ACCENT}; font-size:16px; font-weight:bold;'>ARC Raiders — подсказчик</div>"
            f"<p>Нажми <b>{html.escape(self._hotkey_hint)}</b>, чтобы ввести квест.</p>"
        )

    def show_quest(self, quest: Quest, location: str = ""):
        self._quest = quest
        self._location = location.strip()
        self._step = 0
        self.show_step()

    def next_step(self):
        if self._quest and self._step < len(self._quest.steps) - 1:
            self._step += 1
        self.show_step()

    def prev_step(self):
        if self._quest and self._step > 0:
            self._step -= 1
        self.show_step()

    def show_step(self):
        q = self._quest
        if q is None:
            self.show_welcome()
            return
        esc = html.escape
        parts = [self._header(q)]
        meta = []
        if q.trader:
            meta.append(f"Торговец: {esc(q.trader)}")
        if self._location:
            meta.append(f"Локация: {esc(self._location)}")
        if meta:
            parts.append(f"<div style='color:{MUTED};'>{' · '.join(meta)}</div>")
        if not self._db.available_at(q, self._location):
            places = ", ".join(self._db.map_names(q))
            parts.append(f"<p style='color:{WARNING};'>Этот квест выполняется на: {esc(places)}</p>")
        if q.steps:
            one_round = " · всё за один рейд" if q.one_round else ""
            parts.append(
                f"<p><span style='color:{MUTED};'>Шаг {self._step + 1} из {len(q.steps)}{one_round}</span><br>"
                f"<span style='font-size:15px;'>{esc(q.steps[self._step])}</span></p>"
            )
        else:
            parts.append(f"<p style='color:{MUTED};'>Для этого квеста в базе нет шагов.</p>")
        if q.required_items:
            parts.append(f"<div style='color:{MUTED};'>Нужно: {esc(', '.join(q.required_items))}</div>")
        self._set_content("".join(parts), footer=self._guide_hint)

    # --- режим гайда ------------------------------------------------------

    def show_guide_page(self, page: GuidePage | None, index: int, total: int, status: str = ""):
        q = self._quest
        if q is None:
            return
        parts = [self._header(q)]
        if page is None:
            parts.append(f"<p style='color:{MUTED};'>{html.escape(status or 'Гайда для этого квеста пока нет.')}</p>")
            self._set_content("".join(parts), footer="Ctrl+Shift+G — назад к шагу", wide=True)
            return
        parts.append(f"<div style='color:{MUTED};'>Гайд · {html.escape(page.source)} · {index + 1} из {total}</div>")
        if page.title:
            parts.append(f"<p style='font-weight:bold; color:{ACCENT};'>{_lines(page.title)}</p>")
        if page.text:
            parts.append(f"<p>{_lines(page.text)}</p>")
        footer = "\n".join(filter(None, [status, GUIDE_NAV_HINT]))
        self._set_content("".join(parts), footer=footer, wide=True, keep_image=bool(page.image))

    def set_image(self, pixmap: QPixmap | None, placeholder: str = ""):
        if pixmap is None or pixmap.isNull():
            if placeholder:
                self._image.setPixmap(QPixmap())
                self._image.setText(placeholder)
                self._image.setStyleSheet(f"color: {MUTED};")
                self._image.show()
            else:
                self._image.hide()
        else:
            screen = QGuiApplication.primaryScreen().availableGeometry()
            inner = self._width - 36
            scaled = pixmap.scaled(inner, int(screen.height() * 0.45), Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self._image.setText("")
            self._image.setPixmap(scaled)
            self._image.show()
        self._relayout()

    # --- общее ------------------------------------------------------------

    def _header(self, q: Quest) -> str:
        esc = html.escape
        header = f"<div style='color:{ACCENT}; font-size:16px; font-weight:bold;'>{esc(q.name)}</div>"
        if q.english_name and q.english_name != q.name:
            header += f"<div style='color:{MUTED}; font-size:12px;'>{esc(q.english_name)}</div>"
        return header

    def _set_content(self, text: str, footer: str = "", wide: bool = False, keep_image: bool = False):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self._width = max(CARD_WIDTH, min(GUIDE_MAX_WIDTH, screen.width() // 3)) if wide else CARD_WIDTH
        self._label.setText(text)
        self._footer.setText(_lines(footer))
        self._footer.setVisible(bool(footer))
        if not keep_image:
            self._image.hide()
        self._relayout()

    def _relayout(self):
        self.setFixedWidth(self._width)
        # Высоту считаем от фиксированной ширины, иначе перенос строк обрезает низ карточки.
        self.setFixedHeight(self.layout().heightForWidth(self._width))
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(QPoint(screen.right() - self.width() - SCREEN_MARGIN, screen.top() + SCREEN_MARGIN))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.fillPath(path, BACKGROUND)

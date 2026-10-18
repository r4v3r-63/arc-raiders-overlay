"""Скриншот гайда почти на весь экран. Как и карточка, пропускает клики в игру."""

from __future__ import annotations

import html

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

BACKGROUND = QColor(10, 12, 16, 225)
MARGIN = 40  # отступ окна от краёв экрана
CAPTION_HEIGHT = 64


class ZoomWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._pixmap: QPixmap | None = None
        self._caption = ""
        self._hint = ""
        self._markers: list[tuple[float, float, str, bool]] = []

    def show_image(self, pixmap: QPixmap, caption: str = "", hint: str = "",
                   markers: list[tuple[float, float, str, bool]] | None = None):
        """markers — точки на картинке: (x 0..1, y 0..1, подпись, выделить)."""
        self._pixmap = pixmap
        self._caption = caption
        self._hint = hint
        self._markers = markers or []
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN))
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BACKGROUND)
        painter.drawRoundedRect(QRectF(self.rect()), 14, 14)
        if self._pixmap is None or self._pixmap.isNull():
            return
        area = self.rect().adjusted(20, 20, -20, -20 - CAPTION_HEIGHT)
        scaled = self._pixmap.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect(0, 0, scaled.width(), scaled.height())
        target.moveCenter(area.center())
        painter.drawPixmap(target, self._pixmap)
        self._paint_markers(painter, target)
        caption_rect = QRect(20, self.height() - CAPTION_HEIGHT - 10, self.width() - 40, CAPTION_HEIGHT)
        painter.setPen(QColor("#f0f0f0"))
        font = painter.font()
        font.setPixelSize(17)
        painter.setFont(font)
        text = self._caption.replace("\n", " ")
        painter.drawText(caption_rect.adjusted(0, 0, 0, -24), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                         html.unescape(text))
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QColor("#a8adb5"))
        painter.drawText(caption_rect.adjusted(0, 36, 0, 0), Qt.AlignmentFlag.AlignCenter, self._hint)

    def _paint_markers(self, painter: QPainter, target: QRect):
        font = painter.font()
        font.setPixelSize(15)
        font.setBold(True)
        painter.setFont(font)
        for x, y, label, highlight in self._markers:
            cx = target.left() + x * target.width()
            cy = target.top() + y * target.height()
            radius = 13 if highlight else 10
            painter.setPen(QPen(QColor("#15181e"), 2))
            painter.setBrush(QColor("#f2c94c") if highlight else QColor("#ff6b5b"))
            painter.drawEllipse(QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius))
            painter.setPen(QColor("#15181e"))
            number, _, name = label.partition(" ")
            painter.drawText(QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius), Qt.AlignmentFlag.AlignCenter,
                             number)
            # подпись с тёмной подложкой, чтобы читалась на любой карте
            text_rect = painter.fontMetrics().boundingRect(name)
            box = QRectF(cx + radius + 4, cy - text_rect.height() / 2 - 3, text_rect.width() + 10,
                         text_rect.height() + 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(10, 12, 16, 200))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(QColor("#f2c94c") if highlight else QColor("#f0f0f0"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, name)

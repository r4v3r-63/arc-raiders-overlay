"""Полупрозрачная карточка с подсказкой поверх игры. Клики проходят сквозь неё.

Режимы содержимого: шаг квеста, гайд (шире, с текстом и скриншотом) и справка.
В режиме настройки карточка принимает мышь: её можно перетаскивать и менять
масштаб колёсиком; положение и масштаб сохраняются между запусками.
"""

from __future__ import annotations

import html

from PyQt6.QtCore import QPoint, QRectF, QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from . import paths, shortcuts, winapi
from .guide import GuidePage
from .quest_db import Quest, QuestDB

CARD_WIDTH = 380
GUIDE_MAX_WIDTH = 640
SCREEN_MARGIN = 24
MIN_SCALE, MAX_SCALE, SCALE_STEP = 0.6, 2.0, 0.1
MIN_OPACITY, MAX_OPACITY, DEFAULT_OPACITY, OPACITY_STEP = 20, 100, 100, 5  # непрозрачность фона, %
BACKGROUND_RGB = (15, 18, 24)
ACCENT = "#f2c94c"
TEXT = "#f0f0f0"
MUTED = "#a8adb5"
SUCCESS = "#7bd88f"
EDIT_HINT = "Перетащи карточку мышкой. Колёсико — масштаб, Ctrl + колёсико — прозрачность. Esc или «Готово» — выйти."


def _lines(text: str) -> str:
    return "<br>".join(html.escape(line) for line in text.splitlines())


class OverlayCard(QWidget):
    editing_changed = pyqtSignal(bool)  # видимость после настройки решает приложение (карточка вне игры прячется)

    def __init__(self, db: QuestDB, settings: QSettings | None = None):
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

        self._toolbar = QWidget()
        bar = QHBoxLayout(self._toolbar)
        bar.setContentsMargins(0, 0, 0, 0)
        self._buttons = {}
        for key, label, handler in [
            ("help", "?", self.toggle_help),
            ("smaller", "−", lambda: self.change_scale(-SCALE_STEP)),
            ("bigger", "+", lambda: self.change_scale(SCALE_STEP)),
            ("reset", "Сброс", self.reset_geometry),
            ("done", "Готово", lambda: self.set_editing(False)),
        ]:
            button = QPushButton(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(handler)
            self._buttons[key] = button
            if key == "done":
                bar.addStretch()
            bar.addWidget(button)
        self._opacity_row = QWidget()
        row = QHBoxLayout(self._opacity_row)
        row.setContentsMargins(0, 0, 0, 0)
        self._opacity_label = QLabel()
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(MIN_OPACITY, MAX_OPACITY)
        self._opacity_slider.setSingleStep(OPACITY_STEP)
        self._opacity_slider.setPageStep(OPACITY_STEP * 2)
        self._opacity_slider.valueChanged.connect(self.set_opacity)
        row.addWidget(self._opacity_label)
        row.addWidget(self._opacity_slider, 1)
        self._toolbar.hide()
        self._opacity_row.hide()

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.hide()
        self._footer = QLabel()
        self._footer.setTextFormat(Qt.TextFormat.RichText)
        self._footer.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._opacity_row)
        layout.addWidget(self._label)
        layout.addWidget(self._image)
        layout.addWidget(self._footer)

        self._settings = settings or paths.settings()
        self._scale = self._clamp_scale(float(self._settings.value("scale", 1.0)))
        self._opacity = self._clamp_opacity(int(self._settings.value("opacity", DEFAULT_OPACITY)))
        self._opacity_slider.setValue(self._opacity)
        self._update_opacity_label()
        anchor = self._settings.value("anchor")
        self._anchor: QPoint | None = anchor if isinstance(anchor, QPoint) else None

        self._db = db
        self._quest: Quest | None = None
        self._step = 0
        self._position = (0, 0)  # (номер текущего квеста, всего активных)
        self._notice = ""  # короткое сообщение над карточкой, например «квест выполнен»
        self._wide = False
        self._width = CARD_WIDTH
        self._pixmap: QPixmap | None = None
        self._render = self._render_welcome
        self._before_help = None  # что было на карточке до временной панели (справка, сводка)
        self._panel = ""  # какая временная панель открыта: "help", "shopping" или ""
        self._shopping: list = []
        self._shopping_note = ""
        self._item = None  # ItemReport для панели «брать или продавать»
        self._saved_pixmap: QPixmap | None = None  # скриншот гайда, пока поверх открыта панель
        self._keeps_image = False  # текущее содержимое показывает скриншот (страница гайда)
        self._editing = False
        self._drag_offset: QPoint | None = None
        self._previous_window = None
        self._apply_scale()
        self._render()

    @property
    def quest(self) -> Quest | None:
        return self._quest

    def set_db(self, db: QuestDB):
        self._db = db

    def refresh(self):
        """Перерисовать текущее содержимое (например, после смены горячих клавиш)."""
        self._render()

    @property
    def current_pixmap(self) -> QPixmap | None:
        """Скриншот, который сейчас показан в гайде (для просмотра на весь экран)."""
        return self._pixmap

    @property
    def scale(self) -> float:
        return self._scale

    @property
    def opacity(self) -> int:
        return self._opacity

    @property
    def editing(self) -> bool:
        return self._editing

    # --- содержимое ---------------------------------------------------------

    @property
    def step(self) -> int:
        return self._step

    def show_welcome(self, notice: str = ""):
        self._quest = None
        self._notice = notice
        self._show(self._render_welcome)

    def show_quest(self, quest: Quest, step: int = 0, position: tuple[int, int] = (0, 0), notice: str = ""):
        self._quest = quest
        self._step = max(0, min(step, len(quest.steps) - 1)) if quest.steps else 0
        self._position = position
        self._notice = notice
        self.show_step()

    def next_step(self):
        if self._quest and self._step < len(self._quest.steps) - 1:
            self._step += 1
        self._notice = ""
        self.show_step()

    def prev_step(self):
        if self._quest and self._step > 0:
            self._step -= 1
        self._notice = ""
        self.show_step()

    def show_step(self):
        self._show(self._render_step if self._quest else self._render_welcome)

    def show_guide_page(self, page: GuidePage | None, index: int, total: int, status: str = ""):
        if self._quest is not None:
            self._pixmap = None
            self._show(lambda: self._render_guide(page, index, total, status))

    def set_image(self, pixmap: QPixmap | None, placeholder: str = ""):
        if self._panel:  # скриншот догрузился, пока открыта панель: покажем, когда её закроют
            self._saved_pixmap = pixmap
            return
        self._pixmap = pixmap if pixmap is not None and not pixmap.isNull() else None
        self._image.setPixmap(QPixmap())
        self._image.setText("" if self._pixmap else placeholder)
        self._image.setVisible(bool(self._pixmap or placeholder))
        self._relayout()

    def toggle_help(self):
        self._toggle_panel("help", self._render_help)

    def toggle_shopping(self, items: list, note: str = ""):
        """Сводка «что собрать»: items — [(предмет, количество, [для чего])]."""
        self._shopping = items
        self._shopping_note = note
        self._toggle_panel("shopping", self._render_shopping)

    @property
    def panel(self) -> str:
        return self._panel

    @property
    def item(self):
        """Предмет на панели «брать или продавать» (ItemReport) или None."""
        return self._item if self._panel == "item" else None

    def show_item(self, report):
        """Панель «брать или продавать» (report — items.ItemReport). Повторный вызов обновляет её."""
        self._item = report
        if self._panel == "item":
            self._render_item()
        else:
            self._toggle_panel("item", self._render_item)

    def close_panel(self):
        """Закрывает справку или сводку, если открыта, и возвращает прежнее содержимое."""
        if self._before_help is not None:
            previous, self._before_help = self._before_help, None
            self._panel = ""
            self._render = previous
            previous()
            self._restore_image()

    def _restore_image(self):
        """Возвращает скриншот гайда, который был на карточке до панели."""
        saved, self._saved_pixmap = self._saved_pixmap, None
        if self._keeps_image and saved is not None:
            self.set_image(saved)

    def _toggle_panel(self, panel: str, render):
        if self._before_help is not None:
            previous, self._before_help = self._before_help, None
            was = self._panel
            self._panel = ""
            self._render = previous
            if was == panel:  # повторное нажатие закрывает панель
                previous()
                self._restore_image()
                return
        else:
            self._saved_pixmap = self._pixmap
        self._before_help = self._render
        self._panel = panel
        self._render = render
        render()

    def _show(self, render):
        self._before_help = None
        self._saved_pixmap = None
        self._panel = ""
        self._render = render
        render()

    # --- отрисовка --------------------------------------------------------

    def _px(self, size: float) -> int:
        return max(1, round(size * self._scale))

    def _header(self, q: Quest) -> str:
        esc = html.escape
        header = f"<div style='color:{ACCENT}; font-size:{self._px(16)}px; font-weight:bold;'>{esc(q.name)}</div>"
        if q.english_name and q.english_name != q.name:
            header += f"<div style='color:{MUTED}; font-size:{self._px(12)}px;'>{esc(q.english_name)}</div>"
        return header

    def _notice_html(self) -> str:
        if not self._notice:
            return ""
        return f"<p style='color:{SUCCESS};'>{_lines(self._notice)}</p>"

    def _render_welcome(self):
        self._set_content(
            self._notice_html() +
            f"<div style='color:{ACCENT}; font-size:{self._px(16)}px; font-weight:bold;'>ARC Raiders — подсказчик</div>"
            f"<p>Нажми <b>{html.escape(shortcuts.key('input'))}</b>, чтобы ввести квест.</p>",
            footer=f"{shortcuts.key('help')} — все сочетания клавиш",
        )

    def _render_step(self):
        q = self._quest
        esc = html.escape
        parts = [self._notice_html(), self._header(q)]
        meta = []
        index, total = self._position
        if total > 1:
            meta.append(f"Квест {index + 1} из {total}")
        if q.trader:
            meta.append(f"Торговец: {esc(q.trader)}")
        if q.locations:
            meta.append(f"Где: {esc(', '.join(self._db.map_names(q)))}")
        if meta:
            parts.append(f"<div style='color:{MUTED};'>{' · '.join(meta)}</div>")
        if q.steps:
            one_round = " · всё за один рейд" if q.one_round else ""
            parts.append(
                f"<p><span style='color:{MUTED};'>Шаг {self._step + 1} из {len(q.steps)}{one_round}</span><br>"
                f"<span style='font-size:{self._px(15)}px;'>{esc(q.steps[self._step])}</span></p>"
            )
        else:
            parts.append(f"<p style='color:{MUTED};'>Для этого квеста в базе нет шагов.</p>")
        if q.required_items:
            parts.append(f"<div style='color:{MUTED};'>Нужно: {esc(', '.join(q.required_items))}</div>")
        footer = f"{shortcuts.key('guide')} — гайд со скриншотами"
        if q.places:
            footer += f"\n{shortcuts.key('map')} — карта с точками"
        self._set_content("".join(parts), footer=footer)

    def _render_guide(self, page: GuidePage | None, index: int, total: int, status: str):
        parts = [self._header(self._quest)]
        if page is None:
            parts.append(f"<p style='color:{MUTED};'>{html.escape(status or 'Гайда для этого квеста пока нет.')}</p>")
            self._set_content("".join(parts), footer=f"{shortcuts.key('guide')} — назад к шагу", wide=True)
            return
        parts.append(f"<div style='color:{MUTED};'>Гайд · {html.escape(page.source)} · {index + 1} из {total}</div>")
        if page.title:
            parts.append(f"<p style='font-weight:bold; color:{ACCENT};'>{_lines(page.title)}</p>")
        if page.text:
            parts.append(f"<p>{_lines(page.text)}</p>")
        nav = (f"{shortcuts.key('page_up')} / {shortcuts.key('page_down')} — листать · "
               f"{shortcuts.key('zoom')} — крупно · {shortcuts.key('guide')} — назад к шагу")
        footer = "\n".join(filter(None, [status, nav]))
        self._set_content("".join(parts), footer=footer, wide=True, keep_image=bool(page.image))

    def _render_shopping(self):
        esc = html.escape
        title = (f"<div style='color:{ACCENT}; font-size:{self._px(16)}px; font-weight:bold;'>"
                 f"Что собрать для активных квестов</div>")
        if not self._shopping:
            body = f"<p style='color:{MUTED};'>Активным квестам предметы не нужны.</p>"
        else:
            rows = "".join(
                f"<tr><td style='color:{ACCENT}; padding-right:{self._px(10)}px;' align='right'><b>{qty}×</b></td>"
                f"<td>{esc(name)}<br><span style='color:{MUTED}; font-size:{self._px(12)}px;'>"
                f"{esc(', '.join(quests))}</span></td></tr>"
                for name, qty, quests in self._shopping
            )
            body = f"<table style='margin-top:{self._px(6)}px;' cellspacing='{self._px(3)}'>{rows}</table>"
        if self._shopping_note:
            body += f"<p style='color:{MUTED}; font-size:{self._px(12)}px;'>{esc(self._shopping_note)}</p>"
        self._set_content(title + body, footer=f"{shortcuts.key('shopping')} — закрыть сводку", wide=True)

    def _render_item(self):
        esc = html.escape
        r = self._item
        unknown_blueprint = r.item.unlocks and not r.keep and "изучен" not in r.verdict
        color = SUCCESS if r.keep else (ACCENT if r.later_quests or r.later_workshops or unknown_blueprint else MUTED)
        parts = [
            f"<div style='color:{ACCENT}; font-size:{self._px(16)}px; font-weight:bold;'>{esc(r.item.name)}</div>",
            f"<div style='color:{color}; font-size:{self._px(15)}px; font-weight:bold;'>{esc(r.verdict)}</div>",
        ]

        def section(title: str, lines: list[str]):
            if lines:
                parts.append(f"<p style='margin-top:{self._px(6)}px;'><span style='color:{MUTED};'>{esc(title)}</span>"
                             f"<br>{'<br>'.join(esc(line) for line in lines)}</p>")

        section("Для активных квестов:", [f"{qty}× — {name}" for name, qty in r.quests])
        section("Для мастерских (следующий уровень):", [f"{qty}× — {name}, ур. {lv}" for name, lv, qty in r.workshops])
        later = r.later_quests[:4] + ([f"и ещё {len(r.later_quests) - 4}"] if len(r.later_quests) > 4 else [])
        section("Понадобится в квестах, которые ещё не взяты:", later)
        section("Для мастерских позже:", [f"{qty}× — {name}, ур. {lv}" for name, lv, qty in r.later_workshops[:4]])
        w = r.where
        maps = [f"{m.name} — {len(m.rooms)}: " + ", ".join(room["name"] for room in m.rooms[:4])
                + (" …" if len(m.rooms) > 4 else "") for m in w.maps[:3]]
        section("Где искать — места с лутом:", [", ".join(w.types)] if w.types else [])
        section("Где таких мест больше всего:", maps)
        section("Выпадает из машин:", w.drops)
        section("Получается разборкой:", [", ".join(w.sources[:6]) + (" …" if len(w.sources) > 6 else "")]
                if w.sources else [])
        if not (w.types or w.drops or w.sources):
            parts.append(f"<div style='color:{MUTED};'>Где искать — в базе не указано, "
                         f"{esc(shortcuts.key('open_browser'))} — поискать в интернете.</div>")
        section("Крафт:", r.craft + ([r.blueprint] if r.blueprint else []))
        section("Купить:", r.vendors)
        section("Разбирается на:", [", ".join(f"{qty}× {name}" for name, qty in r.recycles)] if r.recycles else [])
        if r.item.value:
            parts.append(f"<div style='color:{MUTED};'>Цена продажи: {r.item.value} монет</div>")
        footer = f"{shortcuts.key('item')} — проверить предмет под курсором · {shortcuts.key('find_item')} — найти"
        if w.maps:
            footer += f"\n{shortcuts.key('map')} — эти места на карте"
        footer += f"\n{shortcuts.key('open_browser')} — поискать в интернете, где найти"
        if r.item.unlocks or r.item.blueprint:
            footer += f"\n{shortcuts.key('blueprint')} — отметить чертёж изученным / не изученным"
        self._set_content("".join(parts), footer=footer, wide=True)

    def _render_help(self):
        rows = "".join(
            f"<tr><td style='color:{ACCENT}; padding-right:{self._px(12)}px;'><b>{html.escape(keys)}</b></td>"
            f"<td>{html.escape(what)}</td></tr>"
            for keys, what in shortcuts.rows()
        )
        self._set_content(
            f"<div style='color:{ACCENT}; font-size:{self._px(16)}px; font-weight:bold;'>Сочетания клавиш</div>"
            f"<table style='margin-top:{self._px(6)}px;' cellspacing='{self._px(3)}'>{rows}</table>"
            f"<p style='color:{MUTED};'>{html.escape(shortcuts.FOOTNOTE)}</p>",
            footer=f"{shortcuts.key('help')} — закрыть справку",
            wide=True,
        )

    def _set_content(self, text: str, footer: str = "", wide: bool = False, keep_image: bool = False):
        self._wide = wide
        self._label.setText(text)
        if self._editing:
            footer = EDIT_HINT
        self._footer.setText(_lines(footer))
        self._footer.setVisible(bool(footer))
        self._keeps_image = keep_image
        if not keep_image:
            self._pixmap = None
            self._image.hide()
        self._relayout()

    # --- размер и положение -----------------------------------------------

    @staticmethod
    def _clamp_scale(value: float) -> float:
        return round(min(MAX_SCALE, max(MIN_SCALE, value)), 2)

    def change_scale(self, delta: float):
        scale = self._clamp_scale(self._scale + delta)
        if scale != self._scale:
            self._scale = scale
            self._settings.setValue("scale", scale)
            self._apply_scale()
            self._render()

    @staticmethod
    def _clamp_opacity(value: int) -> int:
        return min(MAX_OPACITY, max(MIN_OPACITY, value))

    def set_opacity(self, value: int):
        value = self._clamp_opacity(value)
        if value != self._opacity:
            self._opacity = value
            self._settings.setValue("opacity", value)
        if self._opacity_slider.value() != value:
            self._opacity_slider.setValue(value)
        self._update_opacity_label()
        self.update()

    def _update_opacity_label(self):
        self._opacity_label.setText(f"Фон: {self._opacity}%")

    def reset_geometry(self):
        self._scale = 1.0
        self._anchor = None
        self.set_opacity(DEFAULT_OPACITY)
        for key in ("scale", "anchor", "opacity"):
            self._settings.remove(key)
        self._apply_scale()
        self._render()

    def _apply_scale(self):
        self.layout().setContentsMargins(self._px(18), self._px(14), self._px(18), self._px(14))
        self.layout().setSpacing(self._px(8))
        self._label.setStyleSheet(f"color: {TEXT}; font-size: {self._px(14)}px;")
        self._image.setStyleSheet(f"color: {MUTED}; font-size: {self._px(13)}px;")
        self._footer.setStyleSheet(f"color: {MUTED}; font-size: {self._px(12)}px;")
        self._opacity_label.setStyleSheet(f"color: {MUTED}; font-size: {self._px(12)}px;")
        self._toolbar.setStyleSheet(
            f"QPushButton {{ background: #2a303b; color: {TEXT}; border: 1px solid #3a4250; border-radius: 4px;"
            f" padding: {self._px(3)}px {self._px(9)}px; font-size: {self._px(13)}px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; }}"
        )

    def _screen_geometry(self):
        screen = QGuiApplication.screenAt(self._anchor) if self._anchor else None
        return (screen or QGuiApplication.primaryScreen()).availableGeometry()

    def _relayout(self):
        screen = self._screen_geometry()
        if self._wide:
            base = max(CARD_WIDTH, min(GUIDE_MAX_WIDTH, screen.width() // 3))
        else:
            base = CARD_WIDTH
        self._width = min(round(base * self._scale), int(screen.width() * 0.95))
        if self._pixmap is not None:
            inner = self._width - 2 * self._px(18)
            self._image.setPixmap(self._pixmap.scaled(
                inner, int(screen.height() * 0.45 * min(self._scale, 1.6)),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.setFixedWidth(self._width)
        # Высоту считаем от фиксированной ширины, иначе перенос строк обрезает низ карточки.
        self.setFixedHeight(min(self.layout().heightForWidth(self._width), screen.height()))
        self._move_to_anchor()

    def _move_to_anchor(self):
        screen = self._screen_geometry()
        if self._anchor is None:
            x, y = screen.right() - self.width() - SCREEN_MARGIN, screen.top() + SCREEN_MARGIN
        else:
            # Привязка к правому верхнему углу: карточка растёт влево и вниз, как по умолчанию.
            x, y = self._anchor.x() - self.width(), self._anchor.y()
        x = max(screen.left(), min(x, screen.right() - self.width()))
        y = max(screen.top(), min(y, screen.bottom() - self.height()))
        self.move(QPoint(x, y))

    # --- режим настройки --------------------------------------------------

    def set_editing(self, editing: bool):
        if editing == self._editing:
            return
        self._editing = editing
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, not editing)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, not editing)
        self._toolbar.setVisible(editing)
        self._opacity_row.setVisible(editing)
        self.setCursor(Qt.CursorShape.SizeAllCursor if editing else Qt.CursorShape.ArrowCursor)
        self._render()
        if editing:
            self._previous_window = winapi.get_foreground_window()
            self.show()
            self.raise_()
            self.activateWindow()
            winapi.set_foreground_window(int(self.winId()))
            self.setFocus()
        else:
            self.close_panel()
            self.setVisible(visible)
            winapi.set_foreground_window(self._previous_window)
            self._previous_window = None
        self.editing_changed.emit(editing)

    def toggle_editing(self):
        self.set_editing(not self._editing)

    def mousePressEvent(self, event):
        if self._editing and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._editing and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            self._drag_offset = None
            self._anchor = QPoint(self.x() + self.width(), self.y())
            self._settings.setValue("anchor", self._anchor)

    def wheelEvent(self, event):
        if not self._editing:
            return
        up = event.angleDelta().y() > 0
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_opacity(self._opacity + (OPACITY_STEP if up else -OPACITY_STEP))
        else:
            self.change_scale(SCALE_STEP if up else -SCALE_STEP)

    def keyPressEvent(self, event):
        if self._editing and event.key() == Qt.Key.Key_Escape:
            self.set_editing(False)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        painter.fillPath(path, QColor(*BACKGROUND_RGB, round(self._opacity * 2.55)))
        if self._editing:
            pen = QPen(QColor(ACCENT), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPath(path)

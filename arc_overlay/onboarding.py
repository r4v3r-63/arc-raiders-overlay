"""Короткий обзор возможностей при первом запуске (и по пункту «Как пользоваться» в трее).

Тем же окном после обновления один раз показывается «Что нового» (NEWS).
"""

from __future__ import annotations

import html

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeyEvent, QTextDocument
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import shortcuts

ACCENT = "#f2c94c"
MUTED = "#a8adb5"

# (заголовок, текст). Сочетания клавиш в `обратных кавычках` выделяются.
PAGES = [
    ("Подсказчик квестов ARC Raiders",
     "Программа показывает поверх игры карточку с текущим шагом квеста и гайдом со скриншотами.\n\n"
     "Карточка не мешает играть: клики проходят сквозь неё, всё управление — горячими клавишами.\n\n"
     "Важно: в настройках игры выберите режим экрана «Оконный без рамки» — иначе Windows "
     "не покажет карточку поверх игры."),
    ("Ввести квест",
     "`{input}` — открыть окно ввода. Начните печатать название, как в игре, и выберите "
     "квест из списка подсказок.\n\n"
     "В правом верхнем углу появится карточка с первым шагом.\n"
     "`{next_step}` / `{prev_step}` — следующий и предыдущий шаг."),
    ("Гайд со скриншотами",
     "`{guide}` — развернуть карточку в гайд: куда идти и что делать, со скриншотами карты "
     "и мест в игре.\n\n"
     "`{page_up}` / `{page_down}` — листать страницы гайда, `{zoom}` — скриншот на весь экран.\n"
     "`{map}` — карта локации с точками квеста: цифра — номер шага.\n"
     "`{open_browser}` — открыть гайд квеста в браузере."),
    ("Несколько квестов",
     "Каждый введённый квест попадает в список активных, прогресс сохраняется между запусками.\n\n"
     "`{switch_quest}` — переключить активный квест.\n"
     "`{complete}` — квест выполнен: следующие квесты цепочки добавятся в список сами.\n"
     "`{import}` — найти квесты на экране игры (например, в лобби) и добавить их в список.\n"
     "`{shopping}` — что собрать для всех активных квестов.\n"
     "`{item}` — наведите курсор на предмет в игре: программа подскажет, брать его или продавать.\n"
     "`{find_item}` — найти предмет по названию: на каких картах его искать."),
    ("Настройка и значок в трее",
     "`{edit}` — перетащить карточку мышкой, колёсико — масштаб, Ctrl + колёсико — прозрачность.\n"
     "`{toggle_card}` — спрятать или показать карточку.\n"
     "`{help}` — справка со всеми сочетаниями.\n\n"
     "Когда вы переключаетесь из игры в другое окно, карточка прячется сама.\n\n"
     "Жёлтый значок «?» в трее рядом с часами: правый клик — меню с автозапуском вместе с Windows, "
     "уровнями мастерских (для сводки «Что собрать»), этим обзором и выходом из программы. Там же появится ссылка, когда выйдет новая версия."),
]


# Новое в программе, свежее сверху: (номер, заголовок, текст). Номер только растёт:
# по нему программа понимает, что игрок ещё не видел. Добавляя новость, дайте ей следующий номер.
NEWS = [
    (5, "Поиск предметов",
     "`{find_item}` — введите название предмета: программа покажет, в каких местах с лутом он лежит "
     "и на каких картах таких мест больше всего. `{map}` отметит эти места на карте."),
    (4, "Мастерские в «Что собрать»",
     "Отметьте уровни мастерских в меню значка в трее → «Мастерские» — сводка `{shopping}` добавит "
     "предметы для следующего уровня."),
    (3, "Брать или продавать?",
     "Наведите курсор на предмет в игре и нажмите `{item}`: программа скажет, нужен ли он для квестов "
     "и мастерских, на что разбирается и сколько стоит."),
    (2, "Карта с точками квеста",
     "`{map}` — карта локации с местами квеста: цифра у точки — номер шага, текущий шаг выделен."),
    (1, "Скриншоты в полном размере",
     "`{zoom}` открывает скриншот гайда на весь экран, а скриншоты с вики теперь в полном размере."),
]
LATEST_NEWS = max(number for number, _, _ in NEWS)


def news_pages(seen: int) -> list[tuple[str, str]]:
    """Одна страница «Что нового» со всем, что новее seen (пусто — нечего показывать)."""
    fresh = [(title, text) for number, title, text in NEWS if number > seen]
    if not fresh:
        return []
    return [("Что нового", "\n\n".join(f"`{title}`\n{text}" for title, text in fresh))]


def _format(text: str) -> str:
    text = text.format(**{action: shortcuts.key(action) for action in shortcuts.DEFAULTS})
    parts = html.escape(text).split("`")
    out = "".join(f"<b style='color:{ACCENT};'>{p}</b>" if i % 2 else p for i, p in enumerate(parts))
    return out.replace("\n", "<br>")


class OnboardingWindow(QWidget):
    finished = pyqtSignal()

    def __init__(self, pages: list[tuple[str, str]] | None = None, title: str = "Как пользоваться",
                 finish_text: str = "Начать"):
        super().__init__()
        self._pages = pages or PAGES
        self._finish_text = finish_text
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setWindowTitle(title)
        self.setFixedWidth(520)
        self.setStyleSheet(
            "QWidget { background: #1b1f27; color: #f0f0f0; font-size: 14px; }"
            "QPushButton { background: #2a303b; border: 1px solid #3a4250; border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { border-color: #f2c94c; }"
            "QPushButton#primary { background: #f2c94c; color: #15181e; border-color: #f2c94c; font-weight: bold; }"
        )
        self._title = QLabel()
        self._title.setStyleSheet(f"color: {ACCENT}; font-size: 18px; font-weight: bold;")
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setTextFormat(Qt.TextFormat.RichText)
        self._text.setMinimumHeight(170)
        self._text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._counter = QLabel()
        self._counter.setStyleSheet(f"color: {MUTED}; font-size: 12px;")

        self._skip = QPushButton("Пропустить")
        self._back = QPushButton("Назад")
        self._next = QPushButton()
        self._next.setObjectName("primary")
        self._skip.clicked.connect(self.finish)
        self._back.clicked.connect(lambda: self.show_page(self._page - 1))
        self._next.clicked.connect(self._forward)

        buttons = QHBoxLayout()
        buttons.addWidget(self._skip)
        buttons.addStretch()
        buttons.addWidget(self._counter)
        buttons.addSpacing(12)
        buttons.addWidget(self._back)
        buttons.addWidget(self._next)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        layout.addWidget(self._title)
        layout.addWidget(self._text)
        layout.addLayout(buttons)

        self._page = 0
        self.show_page(0)

    @property
    def page(self) -> int:
        return self._page

    def show_page(self, index: int):
        self._page = max(0, min(index, len(self._pages) - 1))
        title, text = self._pages[self._page]
        self._title.setText(title)
        self._text.setText(_format(text))
        # Длинный текст («Что нового») не должен обрезаться: высота по переносу строк при ширине окна.
        self._text.ensurePolished()
        doc = QTextDocument()
        doc.setDefaultFont(self._text.font())
        doc.setHtml(self._text.text())
        doc.setTextWidth(self.width() - 48)
        self._text.setMinimumHeight(max(170, int(doc.size().height()) + 8))
        self._counter.setText(f"{self._page + 1} из {len(self._pages)}")
        self._counter.setVisible(len(self._pages) > 1)
        self._back.setVisible(self._page > 0)
        last = self._page == len(self._pages) - 1
        self._next.setText(self._finish_text if last else "Далее")
        self._skip.setVisible(not last)

    def set_pages(self, pages: list[tuple[str, str]]):
        self._pages = pages

    def _forward(self):
        if self._page == len(self._pages) - 1:
            self.finish()
        else:
            self.show_page(self._page + 1)

    def open(self):
        self.show_page(0)
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()

    def finish(self):
        self.hide()
        self.finished.emit()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._forward()
        elif event.key() == Qt.Key.Key_Left:
            self.show_page(self._page - 1)
        elif event.key() == Qt.Key.Key_Escape:
            self.finish()
        else:
            super().keyPressEvent(event)

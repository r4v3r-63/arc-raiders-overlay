"""Короткий обзор возможностей при первом запуске (и по пункту «Как пользоваться» в трее)."""

from __future__ import annotations

import html

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeyEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

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
     "`Ctrl+Shift+Q` — открыть окно ввода. Начните печатать название, как в игре, и выберите "
     "квест из списка подсказок.\n\n"
     "В правом верхнем углу появится карточка с первым шагом.\n"
     "`Ctrl+Shift+→` / `Ctrl+Shift+←` — следующий и предыдущий шаг."),
    ("Гайд со скриншотами",
     "`Ctrl+Shift+G` — развернуть карточку в гайд: куда идти и что делать, со скриншотами карты "
     "и мест в игре.\n\n"
     "`Ctrl+Shift+↑` / `Ctrl+Shift+↓` — листать страницы гайда.\n"
     "`Ctrl+Shift+O` — открыть гайд квеста в браузере."),
    ("Несколько квестов",
     "Каждый введённый квест попадает в список активных, прогресс сохраняется между запусками.\n\n"
     "`Ctrl+Shift+Tab` — переключить активный квест.\n"
     "`Ctrl+Shift+D` — квест выполнен: следующие квесты цепочки добавятся в список сами.\n"
     "`Ctrl+Shift+I` — найти квесты на экране игры (например, в лобби) и добавить их в список."),
    ("Настройка и значок в трее",
     "`Ctrl+Shift+M` — перетащить карточку мышкой, колёсико — масштаб, Ctrl + колёсико — прозрачность.\n"
     "`Ctrl+Shift+X` — спрятать или показать карточку.\n"
     "`Ctrl+Shift+H` — справка со всеми сочетаниями.\n\n"
     "Жёлтый значок «?» в трее рядом с часами: правый клик — меню с автозапуском вместе с Windows, "
     "этим обзором и выходом из программы."),
]


def _format(text: str) -> str:
    parts = html.escape(text).split("`")
    out = "".join(f"<b style='color:{ACCENT};'>{p}</b>" if i % 2 else p for i, p in enumerate(parts))
    return out.replace("\n", "<br>")


class OnboardingWindow(QWidget):
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setWindowTitle("Как пользоваться")
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
        self._page = max(0, min(index, len(PAGES) - 1))
        title, text = PAGES[self._page]
        self._title.setText(title)
        self._text.setText(_format(text))
        self._counter.setText(f"{self._page + 1} из {len(PAGES)}")
        self._back.setVisible(self._page > 0)
        last = self._page == len(PAGES) - 1
        self._next.setText("Начать" if last else "Далее")
        self._skip.setVisible(not last)

    def _forward(self):
        if self._page == len(PAGES) - 1:
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

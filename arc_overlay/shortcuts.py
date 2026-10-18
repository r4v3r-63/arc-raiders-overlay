"""Горячие клавиши: действия, сочетания по умолчанию и сочетания, которые выбрал игрок.

Сочетания хранятся в «настройки.ini» (раздел hotkeys) в формате Qt, например «Ctrl+Shift+Q».
Справка, подсказки на карточке и меню трея берут текст сочетаний отсюда через key().
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QKeySequence

from . import winapi

# (id действия, сочетание по умолчанию, что делает)
ACTIONS = [
    ("input", "Ctrl+Shift+Q", "ввести квест"),
    ("next_step", "Ctrl+Shift+Right", "следующий шаг квеста"),
    ("prev_step", "Ctrl+Shift+Left", "предыдущий шаг квеста"),
    ("switch_quest", "Ctrl+Shift+Tab", "переключить активный квест"),
    ("complete", "Ctrl+Shift+D", "квест выполнен — следующие по цепочке добавятся сами"),
    ("import", "Ctrl+Shift+I", "найти квесты на экране игры и добавить в список"),
    ("shopping", "Ctrl+Shift+L", "что собрать для всех активных квестов"),
    ("item", "Ctrl+Shift+E", "брать или продавать: проверить предмет под курсором"),
    ("find_item", "Ctrl+Shift+P", "найти предмет по названию: где искать и нужен ли он"),
    ("guide", "Ctrl+Shift+G", "гайд со скриншотами / назад к шагу"),
    ("page_down", "Ctrl+Shift+Down", "следующая страница гайда"),
    ("page_up", "Ctrl+Shift+Up", "предыдущая страница гайда"),
    ("zoom", "Ctrl+Shift+F", "скриншот гайда на весь экран"),
    ("map", "Ctrl+Shift+K", "карта с точками текущего квеста (или мест, где искать предмет)"),
    ("open_browser", "Ctrl+Shift+O", "открыть гайд квеста в Steam в браузере"),
    ("toggle_card", "Ctrl+Shift+X", "спрятать / показать карточку"),
    ("edit", "Ctrl+Shift+M", "настройка: перетащить мышкой, колёсико — масштаб, Ctrl + колёсико — прозрачность"),
    ("help", "Ctrl+Shift+H", "справка со всеми сочетаниями"),
]
DEFAULTS = {action: default for action, default, _ in ACTIONS}
DESCRIPTIONS = {action: text for action, _, text in ACTIONS}

FOOTNOTE = "Выход из программы — правый клик по значку «?» в трее → «Выход». Сочетания меняются там же."

_bindings: dict[str, str] = dict(DEFAULTS)

_ARROWS = {"Right": "→", "Left": "←", "Up": "↑", "Down": "↓"}


def load(settings: QSettings):
    for action, default in DEFAULTS.items():
        value = settings.value(f"hotkeys/{action}", default)
        _bindings[action] = value if isinstance(value, str) and to_native(value) else default


def save(settings: QSettings, bindings: dict[str, str]):
    for action, default in DEFAULTS.items():
        value = bindings.get(action, default)
        if value == default:
            settings.remove(f"hotkeys/{action}")
        else:
            settings.setValue(f"hotkeys/{action}", value)
        _bindings[action] = value
    settings.sync()


def bindings() -> dict[str, str]:
    return dict(_bindings)


def pretty(sequence: str) -> str:
    """«Ctrl+Shift+Right» → «Ctrl+Shift+→»."""
    parts = sequence.split("+")
    return "+".join(_ARROWS.get(p, p) for p in parts)


def key(action: str) -> str:
    """Текущее сочетание действия для подсказок, например «Ctrl+Shift+Q»."""
    return pretty(_bindings.get(action, DEFAULTS.get(action, "")))


def rows() -> list[tuple[str, str]]:
    """Строки справки: (сочетание, что делает)."""
    return [(key(action), text) for action, _, text in ACTIONS]


# --- перевод сочетания Qt в код Windows для RegisterHotKey -----------------

_SPECIAL_KEYS = {
    Qt.Key.Key_Tab: 0x09, Qt.Key.Key_Space: 0x20, Qt.Key.Key_PageUp: 0x21, Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_End: 0x23, Qt.Key.Key_Home: 0x24, Qt.Key.Key_Left: 0x25, Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27, Qt.Key.Key_Down: 0x28, Qt.Key.Key_Insert: 0x2D, Qt.Key.Key_Delete: 0x2E,
    Qt.Key.Key_Minus: 0xBD, Qt.Key.Key_Equal: 0xBB, Qt.Key.Key_Comma: 0xBC, Qt.Key.Key_Period: 0xBE,
    Qt.Key.Key_Slash: 0xBF, Qt.Key.Key_Semicolon: 0xBA, Qt.Key.Key_Apostrophe: 0xDE,
    Qt.Key.Key_BracketLeft: 0xDB, Qt.Key.Key_BracketRight: 0xDD, Qt.Key.Key_Backslash: 0xDC,
    Qt.Key.Key_QuoteLeft: 0xC0,
}
_MODIFIERS = [
    (Qt.KeyboardModifier.ControlModifier, winapi.MOD_CONTROL),
    (Qt.KeyboardModifier.ShiftModifier, winapi.MOD_SHIFT),
    (Qt.KeyboardModifier.AltModifier, winapi.MOD_ALT),
    (Qt.KeyboardModifier.MetaModifier, winapi.MOD_WIN),
]


def to_native(sequence: str) -> tuple[int, int] | None:
    """(модификаторы, виртуальный код клавиши) или None, если сочетание не подходит.

    Подходит одна клавиша с хотя бы одним модификатором (Ctrl, Shift, Alt, Win): без модификатора
    сочетание перехватывало бы обычные клавиши в игре.
    """
    seq = QKeySequence(sequence)
    if seq.count() != 1:
        return None
    combo = seq[0]
    mods = 0
    for qt_mod, win_mod in _MODIFIERS:
        if combo.keyboardModifiers() & qt_mod:
            mods |= win_mod
    if not mods:
        return None
    qt_key = combo.key()
    value = int(qt_key.value) if hasattr(qt_key, "value") else int(qt_key)
    if ord("A") <= value <= ord("Z") or ord("0") <= value <= ord("9"):
        vk = value
    elif int(Qt.Key.Key_F1.value) <= value <= int(Qt.Key.Key_F24.value):
        vk = 0x70 + value - int(Qt.Key.Key_F1.value)
    else:
        vk = _SPECIAL_KEYS.get(qt_key)
    return (mods, vk) if vk else None

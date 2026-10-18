"""Импорт квестов с экрана: снимок экрана → распознавание текста Windows → квесты из базы.

С игрой программа не взаимодействует: это обычный снимок экрана, как скриншот.
Распознавание — встроенное в Windows (Windows.Media.Ocr), для русского текста
в Windows должен быть установлен русский язык с компонентом «Распознавание текста».
"""

from __future__ import annotations

import asyncio
import difflib
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .quest_db import Quest, QuestDB, normalize

MATCH_CUTOFF = 0.85  # насколько строка должна совпасть с названием квеста (опечатки распознавания)
MIN_LENGTH = 4


class OcrUnavailable(Exception):
    """Распознавание текста недоступно (не Windows или не установлен язык)."""


def match_quests(db: QuestDB, lines: list[str]) -> list[Quest]:
    """Квесты, названия которых встречаются среди распознанных строк (по порядку, без повторов)."""
    index = {}
    for quest in db.quests:
        for name in [quest.name, *quest.aliases]:
            key = normalize(name)
            if len(key) >= MIN_LENGTH:
                index.setdefault(key, quest)
    keys = list(index)
    found: list[Quest] = []
    for line in lines:
        text = normalize(line)
        if len(text) < MIN_LENGTH:
            continue
        quest = index.get(text)
        if quest is None:
            close = difflib.get_close_matches(text, keys, n=1, cutoff=MATCH_CUTOFF)
            quest = index[close[0]] if close else None
        if quest is not None and quest not in found:
            found.append(quest)
    return found


# --- распознавание (только Windows) ---------------------------------------


def _engine():
    if sys.platform != "win32":
        raise OcrUnavailable("Распознавание текста работает только в Windows.")
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
    except ImportError as error:
        raise OcrUnavailable(f"Не найден модуль распознавания текста Windows: {error}") from error
    russian = Language("ru")
    engine = OcrEngine.try_create_from_language(russian) if OcrEngine.is_language_supported(russian) else None
    engine = engine or OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrUnavailable(
            "В Windows не установлено распознавание текста для русского языка: Параметры → Время и язык → "
            "Язык и регион → Русский → Параметры языка → «Распознавание текста».")
    return engine


def max_image_dimension() -> int:
    try:
        from winrt.windows.media.ocr import OcrEngine
        return int(OcrEngine.max_image_dimension)
    except Exception:  # noqa: BLE001 — не Windows или старая сборка: берём безопасное значение
        return 2600


async def _recognize(path: Path) -> list[str]:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage import FileAccessMode, StorageFile

    engine = _engine()
    file = await StorageFile.get_file_from_path_async(str(path.resolve()))
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    return [line.text for line in result.lines]


def recognize_file(path: Path) -> list[str]:
    """Строки текста на картинке. Бросает OcrUnavailable, если распознавание недоступно."""
    _engine()  # понятная ошибка до запуска асинхронной части
    return asyncio.run(_recognize(path))


class RecognizeThread(QThread):
    """Распознаёт картинку в фоне, чтобы оверлей не подвисал."""

    recognized = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def run(self):
        try:
            self.recognized.emit(recognize_file(self._path))
        except OcrUnavailable as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 — любая ошибка Windows API должна дойти до игрока текстом
            self.failed.emit(f"Не удалось распознать экран: {error}")

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

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QImage

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
#
# Всё, что касается Windows Runtime, выполняется в отдельном потоке с многопоточным
# COM-апартаментом (MTA): в главном потоке Qt включает однопоточный (STA), и ожидание
# асинхронных вызовов Windows там зависает.

TIMEOUT_SECONDS = 30
SAFE_MAX_DIMENSION = 2600


def _init_thread():
    if sys.platform != "win32":
        raise OcrUnavailable("Распознавание текста работает только в Windows.")
    try:
        from winrt.runtime import ApartmentType, init_apartment
    except ImportError as error:
        raise OcrUnavailable(f"Не найден модуль распознавания текста Windows: {error}") from error
    try:
        init_apartment(ApartmentType.MULTI_THREADED)
    except OSError:
        pass  # поток уже инициализирован


def _engine():
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine

    russian = Language("ru")
    engine = OcrEngine.try_create_from_language(russian) if OcrEngine.is_language_supported(russian) else None
    engine = engine or OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrUnavailable(
            "В Windows не установлено распознавание текста для русского языка: Параметры → Время и язык → "
            "Язык и регион → Русский → Параметры языка → «Распознавание текста».")
    return engine


def _max_dimension() -> int:
    try:
        from winrt.windows.media.ocr import OcrEngine
        return int(OcrEngine.max_image_dimension) or SAFE_MAX_DIMENSION
    except Exception:  # noqa: BLE001 — старая сборка Windows: берём безопасное значение
        return SAFE_MAX_DIMENSION


async def _recognize(engine, path: Path) -> list[str]:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage import FileAccessMode, StorageFile

    file = await StorageFile.get_file_from_path_async(str(path.resolve()))
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    return [line.text for line in result.lines]


def recognize_image(image: QImage, work_path: Path) -> list[str]:
    """Строки текста на картинке. Вызывать из фонового потока (см. RecognizeThread).

    Бросает OcrUnavailable, если распознавание недоступно.
    """
    _init_thread()
    engine = _engine()
    # Мелкий текст распознаётся лучше, если картинку немного увеличить (но не больше предела Windows).
    factor = min(1.5, _max_dimension() / max(image.width(), image.height(), 1))
    if abs(factor - 1) > 0.05:
        image = image.scaled(int(image.width() * factor), int(image.height() * factor),
                             Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    image.save(str(work_path))
    try:
        return asyncio.run(asyncio.wait_for(_recognize(engine, work_path), TIMEOUT_SECONDS))
    except asyncio.TimeoutError as error:
        raise OcrUnavailable("Распознавание текста не ответило вовремя.") from error


class RecognizeThread(QThread):
    """Распознаёт картинку в фоне, чтобы оверлей не подвисал."""

    recognized = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, image: QImage, work_path: Path):
        super().__init__()
        self._image = image
        self._path = work_path

    def run(self):
        try:
            self.recognized.emit(recognize_image(self._image, self._path))
        except OcrUnavailable as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 — любая ошибка Windows API должна дойти до игрока текстом
            self.failed.emit(f"Не удалось распознать экран: {error}")

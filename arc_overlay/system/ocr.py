"""Распознавание текста на снимке экрана встроенным распознаванием Windows (Windows.Media.Ocr).

С игрой программа не взаимодействует: это обычный снимок экрана, как скриншот. Что делать
с распознанными строками, решают core/recognition.py (квесты) и core/items.py (предметы).
Для русского текста в Windows должен быть установлен русский язык с компонентом
«Распознавание текста».
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage


class OcrUnavailable(Exception):
    """Распознавание текста недоступно (не Windows или не установлен язык)."""


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


def _line_box(line) -> tuple[str, float, float, float, float]:
    """(текст, x, y, ширина, высота) строки — рамка вокруг её слов."""
    rects = [word.bounding_rect for word in line.words]
    if not rects:
        return line.text, 0, 0, 0, 0
    left = min(r.x for r in rects)
    top = min(r.y for r in rects)
    right = max(r.x + r.width for r in rects)
    bottom = max(r.y + r.height for r in rects)
    return line.text, left, top, right - left, bottom - top


async def _recognize(engine, path: Path, boxes: bool = False) -> list:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage import FileAccessMode, StorageFile

    file = await StorageFile.get_file_from_path_async(str(path.resolve()))
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    return [_line_box(line) if boxes else line.text for line in result.lines]


def recognize_image(image: QImage, work_path: Path, boxes: bool = False) -> list:
    """Строки текста на картинке. Вызывать из фонового потока (см. RecognizeThread).

    С boxes=True каждая строка — (текст, x, y, ширина, высота) в пикселях исходной картинки.

    Бросает OcrUnavailable, если распознавание недоступно.
    """
    _init_thread()
    engine = _engine()
    # Мелкий текст распознаётся лучше, если картинку немного увеличить (но не больше предела Windows).
    factor = min(1.5, _max_dimension() / max(image.width(), image.height(), 1))
    if abs(factor - 1) > 0.05:
        image = image.scaled(int(image.width() * factor), int(image.height() * factor),
                             Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if not image.save(str(work_path)):
        raise OcrUnavailable("Не удалось сохранить снимок экрана для распознавания (нет места на диске?).")
    try:
        lines = asyncio.run(asyncio.wait_for(_recognize(engine, work_path, boxes), TIMEOUT_SECONDS))
    except TimeoutError as error:
        raise OcrUnavailable("Распознавание текста не ответило вовремя.") from error
    if boxes and abs(factor - 1) > 0.05:
        lines = [(text, x / factor, y / factor, w / factor, h / factor) for text, x, y, w, h in lines]
    return lines


class RecognizeThread(QThread):
    """Распознаёт картинку в фоне, чтобы оверлей не подвисал."""

    recognized = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, image: QImage, work_path: Path, boxes: bool = False):
        super().__init__()
        self._image = image
        self._path = work_path
        self._boxes = boxes

    def run(self):
        try:
            self.recognized.emit(recognize_image(self._image, self._path, self._boxes))
        except OcrUnavailable as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 — любая ошибка Windows API должна дойти до игрока текстом
            self.failed.emit(f"Не удалось распознать экран: {error}")

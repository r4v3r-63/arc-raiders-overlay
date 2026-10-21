"""Запуск программы: обычный режим, самопроверки собранного .exe и журнал ошибок.

Вызывается из run_overlay.py (сборка .exe, автозапуск) и через `python -m arc_overlay`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile, QStandardPaths, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QApplication, QMessageBox

from .app import OverlayApp
from .core import recognition
from .core.quest_db import QuestDB
from .system import ocr, paths


def self_test() -> int:
    """Проверка собранного .exe без окон: база читается, HTTPS доступен. Код возврата 0 — всё в порядке."""
    from PyQt6.QtNetwork import QSslSocket

    db = QuestDB.load()
    ok = len(db.quests) >= 100 and QSslSocket.supportsSsl()
    print(f"квестов: {len(db.quests)}, HTTPS: {QSslSocket.supportsSsl()}")
    return 0 if ok else 1


def ocr_self_test() -> int:
    """Проверка распознавания в собранном .exe: рисуем названия квестов и распознаём их."""
    from PyQt6.QtGui import QImage

    image = QImage(1400, 300, QImage.Format.Format_RGB32)
    image.fill(QColor("#15181e"))
    painter = QPainter(image)
    painter.setPen(QColor("#f0f0f0"))
    painter.setFont(QFont("Arial", 28))
    painter.drawText(40, 100, "Greasing Her Palms")
    painter.drawText(40, 200, "What Goes Around")
    painter.end()
    result: dict = {}
    thread = ocr.RecognizeThread(image, paths.cache_dir() / "ocr-test.png")
    thread.recognized.connect(lambda lines: result.update(lines=lines), Qt.ConnectionType.DirectConnection)
    thread.failed.connect(lambda message: result.update(error=message), Qt.ConnectionType.DirectConnection)
    thread.start()
    if not thread.wait(60_000):
        print("распознавание зависло")
        return 1
    if "error" in result:
        print(f"распознавание недоступно: {result['error']}")
        return 1
    lines = result.get("lines", [])
    found = recognition.match_quests(QuestDB.load(), lines)
    print(f"строки: {lines}; квесты: {[q.english_name for q in found]}")
    return 0 if len(found) >= 2 else 1


def _log_unhandled(exc_type, exc, tb):
    """Ошибка в обработчике Qt иначе закрыла бы программу без следа: пишем её в «Данные\\ошибки.log»."""
    import datetime
    import traceback

    text = "".join(traceback.format_exception(exc_type, exc, tb))
    print(text, file=sys.stderr)
    try:
        log = paths.user_data_dir() / "ошибки.log"
        if log.exists() and log.stat().st_size > 1_000_000:
            log.unlink()  # не даём журналу разрастись
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n{text}\n")
    except OSError:
        pass


def main() -> int:
    if "--ocr-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication(sys.argv)
        code = ocr_self_test()
        sys.stdout.flush()
        # Зависший вызов Windows в фоновом потоке не даёт процессу завершиться обычным путём.
        os._exit(code)
    if "--self-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication(sys.argv)
        return self_test()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # окна прячутся, но программа живёт в трее
    # Вторая копия программы делила бы горячие клавиши с первой — не запускаем её.
    lock = QLockFile(str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation))
                         / "arc_raiders_overlay.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "ARC Raiders — подсказчик",
                                "Программа уже запущена — её значок «?» в трее рядом с часами.")
        return 0
    paths.migrate_legacy()
    sys.excepthook = _log_unhandled  # с ним PyQt не завершает программу при ошибке в обработчике
    _overlay = OverlayApp(app)
    return app.exec()

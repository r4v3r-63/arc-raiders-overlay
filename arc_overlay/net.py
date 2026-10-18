"""Асинхронная загрузка по сети с кэшем на диске игрока.

Кэш лежит в папке «Данные\кэш» рядом с программой (см. arc_overlay/paths.py), поэтому
скачанное руководство Steam и картинки остаются только на этом компьютере.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import paths

UNUSED_DAYS = 30  # файлы, которые столько дней не открывались, удаляются при запуске
USER_AGENT = b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) arc-raiders-overlay"
TRANSFER_TIMEOUT_MS = 30_000  # зависшее соединение не должно навсегда занять загрузку


def is_image(data: bytes) -> bool:
    """Проверка для картинок: вместо них иногда приходит страница с ошибкой (Wi-Fi в гостинице и т. п.)."""
    from PyQt6.QtGui import QImage

    return QImage().loadFromData(data)


class CachedDownloader:
    def __init__(self, directory: Path | None = None):
        self._manager = QNetworkAccessManager()
        self._manager.setTransferTimeout(TRANSFER_TIMEOUT_MS)
        self._dir = directory or paths.cache_dir()
        self._waiting: dict[str, list] = {}

    def path_for(self, url: str) -> Path:
        return self._dir / hashlib.sha1(url.encode()).hexdigest()

    def get(self, url: str, callback, max_age: float | None = None, validate=None):
        """Вызывает callback(путь к файлу или None). max_age — сколько секунд кэш считается свежим.

        validate(данные) → False — ответ не тот (страница с ошибкой вместо файла): кэш не трогаем.
        """
        path = self.path_for(url)
        if path.exists() and (max_age is None or time.time() - path.stat().st_mtime < max_age):
            self._touch(path)
            QTimer.singleShot(0, lambda: callback(path))
            return
        if url in self._waiting:
            self._waiting[url].append(callback)
            return
        self._waiting[url] = [callback]
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", USER_AGENT)
        request.setRawHeader(b"Accept-Language", b"ru")
        reply = self._manager.get(request)
        reply.finished.connect(lambda: self._finished(url, path, reply, validate))

    def _finished(self, url: str, path: Path, reply: QNetworkReply, validate=None):
        callbacks = self._waiting.pop(url, [])
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        ok = reply.error() == QNetworkReply.NetworkError.NoError and status in (None, 200)
        data = bytes(reply.readAll()) if ok else b""
        reply.deleteLater()
        if ok and (validate is None or validate(data)):
            try:
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(path)
            except OSError:
                pass  # диск занят или полон — отдадим прежнюю копию, если есть
        # Нет сети — отдаём устаревшую копию, если она есть.
        result = path if path.exists() else None
        if result:
            self._touch(result)
        for callback in callbacks:
            callback(result)

    @staticmethod
    def _touch(path: Path):
        """Отмечает, что файл открывали (время доступа), не трогая время загрузки (mtime)."""
        try:
            os.utime(path, (time.time(), path.stat().st_mtime))
        except OSError:
            pass

    def size(self) -> int:
        return sum(f.stat().st_size for f in self._dir.iterdir() if f.is_file())

    def clear(self) -> int:
        """Удаляет весь кэш, возвращает освобождённые байты."""
        return self._remove(lambda f: True)

    def cleanup(self, unused_days: float = UNUSED_DAYS) -> int:
        """Удаляет файлы, которые не открывались дольше unused_days дней."""
        limit = time.time() - unused_days * 24 * 60 * 60
        return self._remove(lambda f: f.stat().st_atime < limit)

    def _remove(self, should_remove) -> int:
        freed = 0
        for f in list(self._dir.iterdir()):
            if not f.is_file():
                continue
            try:
                if should_remove(f):
                    size = f.stat().st_size
                    f.unlink()
                    freed += size
            except OSError:
                pass  # файл занят — удалим в следующий раз
        return freed

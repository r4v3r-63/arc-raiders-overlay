"""Асинхронная загрузка по сети с кэшем на диске игрока.

Кэш лежит в папке программы в профиле пользователя (не в репозитории), поэтому
скачанное руководство Steam и картинки остаются только на этом компьютере.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, QTimer, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

USER_AGENT = b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) arc-raiders-overlay"


def cache_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
    path = Path(base or Path.home() / ".cache") / "arc_raiders_overlay"
    path.mkdir(parents=True, exist_ok=True)
    return path


class CachedDownloader:
    def __init__(self):
        self._manager = QNetworkAccessManager()
        self._dir = cache_dir()
        self._waiting: dict[str, list] = {}

    def path_for(self, url: str) -> Path:
        return self._dir / hashlib.sha1(url.encode()).hexdigest()

    def get(self, url: str, callback, max_age: float | None = None):
        """Вызывает callback(путь к файлу или None). max_age — сколько секунд кэш считается свежим."""
        path = self.path_for(url)
        if path.exists() and (max_age is None or time.time() - path.stat().st_mtime < max_age):
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
        reply.finished.connect(lambda: self._finished(url, path, reply))

    def _finished(self, url: str, path: Path, reply: QNetworkReply):
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        if ok:
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(bytes(reply.readAll()))
            tmp.replace(path)
        reply.deleteLater()
        # Нет сети — отдаём устаревшую копию, если она есть.
        result = path if path.exists() else None
        for callback in self._waiting.pop(url, []):
            callback(result)

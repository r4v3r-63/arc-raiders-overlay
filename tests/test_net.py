import os
import time

from arc_overlay.system.net import CachedDownloader


def test_cleanup_removes_only_unused(qapp, tmp_path):
    cache = CachedDownloader(tmp_path)
    old, fresh = tmp_path / "old", tmp_path / "fresh"
    old.write_bytes(b"x" * 100)
    fresh.write_bytes(b"y" * 50)
    month_ago = time.time() - 40 * 24 * 60 * 60
    os.utime(old, (month_ago, month_ago))
    assert cache.size() == 150
    assert cache.cleanup() == 100
    assert not old.exists() and fresh.exists()
    assert cache.clear() == 50
    assert cache.size() == 0


def test_touch_keeps_download_time(qapp, tmp_path):
    cache = CachedDownloader(tmp_path)
    f = tmp_path / "file"
    f.write_bytes(b"z")
    os.utime(f, (1000, 2000))
    cache._touch(f)
    assert f.stat().st_mtime == 2000
    assert f.stat().st_atime > 2000


def test_data_lives_next_to_program(qapp):
    from arc_overlay.system import paths

    assert paths.user_data_dir() == paths.app_dir() / "Данные"
    assert paths.cache_dir().parent == paths.user_data_dir()
    assert paths.settings().fileName().endswith("настройки.ini")


class FakeReply:
    def __init__(self, data, status=200, error=None):
        from PyQt6.QtNetwork import QNetworkReply
        self._data, self._status = data, status
        self._error = error or QNetworkReply.NetworkError.NoError

    def error(self):
        return self._error

    def attribute(self, _attr):
        return self._status

    def readAll(self):
        return self._data

    def deleteLater(self):
        pass


def test_bad_response_keeps_good_cache(qapp, tmp_path):
    cache = CachedDownloader(tmp_path)
    path = cache.path_for("u")
    path.write_bytes(b"good")
    got = []
    cache._waiting["u"] = [got.append]
    cache._finished("u", path, FakeReply(b"<html>portal</html>"), validate=lambda d: d.startswith(b"{"))
    assert path.read_bytes() == b"good" and got == [path]
    cache._waiting["u"] = [got.append]
    cache._finished("u", path, FakeReply(b"oops", status=404))
    assert path.read_bytes() == b"good"
    cache._waiting["u"] = [got.append]
    cache._finished("u", path, FakeReply(b"{new}"), validate=lambda d: d.startswith(b"{"))
    assert path.read_bytes() == b"{new}" and "u" not in cache._waiting


def test_is_image(qapp):
    from PyQt6.QtCore import QBuffer, QByteArray
    from PyQt6.QtGui import QImage

    from arc_overlay.system.net import is_image

    image = QImage(4, 4, QImage.Format.Format_RGB32)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    assert is_image(bytes(data)) and not is_image(b"<html>")

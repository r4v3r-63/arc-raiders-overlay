import os
import time

from arc_overlay.net import CachedDownloader


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
    from arc_overlay import paths

    assert paths.user_data_dir() == paths.app_dir() / "Данные"
    assert paths.cache_dir().parent == paths.user_data_dir()
    assert paths.settings().fileName().endswith("настройки.ini")

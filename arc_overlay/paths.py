"""Где программа хранит свои данные: всё в папке «Данные» рядом с программой.

ARC-Raiders-Overlay\\
├── ARC-Raiders-Overlay.exe
├── _internal\\          программа, встроенная база и скриншоты с вики
└── Данные\\
    ├── кэш\\            руководство Steam, его скриншоты, свежая база с GitHub
    └── настройки.ini   положение и масштаб карточки

Если в папку программы писать нельзя (например, Program Files), данные хранятся в AppData.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings, QStandardPaths

DATA_DIR_NAME = "Данные"
LEGACY_SETTINGS = ("arc_raiders_overlay", "overlay")  # прежние настройки в реестре


def app_dir() -> Path:
    """Папка с ARC-Raiders-Overlay.exe (или корень проекта при запуске из исходников)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".probe"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _legacy_cache_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
    return Path(base or Path.home() / ".cache") / "arc_raiders_overlay"


def user_data_dir() -> Path:
    folder = app_dir() / DATA_DIR_NAME
    if _writable(folder):
        return folder
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    folder = Path(base or Path.home()) / "arc_raiders_overlay"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def cache_dir() -> Path:
    folder = user_data_dir() / "кэш"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def settings() -> QSettings:
    return QSettings(str(user_data_dir() / "настройки.ini"), QSettings.Format.IniFormat)


def migrate_legacy():
    """Переносит настройки из реестра в настройки.ini и удаляет старый кэш из AppData."""
    old = QSettings(*LEGACY_SETTINGS)
    keys = old.allKeys()
    if keys:
        new = settings()
        for key in keys:
            if not new.contains(key):
                new.setValue(key, old.value(key))
        new.sync()
        old.clear()
        old.sync()
    legacy_cache = _legacy_cache_dir()
    if legacy_cache.is_dir() and legacy_cache.resolve() != cache_dir().resolve():
        shutil.rmtree(legacy_cache, ignore_errors=True)

"""Автозапуск вместе с Windows через ключ реестра HKCU\\...\\Run (без прав администратора)."""

from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ARC Raiders Overlay"

try:
    import winreg
except ImportError:  # не Windows
    winreg = None


def available() -> bool:
    return winreg is not None


def command() -> str:
    """Команда запуска текущей копии программы: сам .exe или pythonw с run_overlay.py."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = Path(__file__).resolve().parents[2] / "run_overlay.py"
    return f'"{pythonw if pythonw.exists() else sys.executable}" "{script}"'


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(enabled: bool):
    if winreg is None:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def refresh():
    """Если автозапуск включён, а программу перенесли в другую папку, обновляет путь."""
    if is_enabled():
        set_enabled(True)

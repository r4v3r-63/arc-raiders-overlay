"""Тонкая обёртка над Windows API: глобальные горячие клавиши и фокус окон.

На других системах (например, Linux при разработке) функции ничего не делают,
чтобы программу можно было запустить и проверить без Windows.
"""

from __future__ import annotations

import ctypes
import sys

from PyQt6.QtCore import QAbstractNativeEventFilter

IS_WINDOWS = sys.platform == "win32"

WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000  # не повторять событие, пока клавиша зажата

VK_TAB = 0x09
VK_D = 0x44
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_G = 0x47
VK_H = 0x48
VK_I = 0x49
VK_M = 0x4D
VK_O = 0x4F
VK_Q = 0x51
VK_X = 0x58

if IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]


class HotkeyManager(QAbstractNativeEventFilter):
    """Регистрирует системные горячие клавиши (работают, даже когда активна игра)."""

    def __init__(self):
        super().__init__()
        self._callbacks: dict[int, callable] = {}
        self._next_id = 1

    def register(self, modifiers: int, vk: int, callback) -> bool:
        """Возвращает False, если клавиша недоступна (занята другой программой или не Windows)."""
        if not IS_WINDOWS:
            return False
        hotkey_id = self._next_id
        if not _user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk):
            return False
        self._next_id += 1
        self._callbacks[hotkey_id] = callback
        return True

    def unregister_all(self):
        if IS_WINDOWS:
            for hotkey_id in self._callbacks:
                _user32.UnregisterHotKey(None, hotkey_id)
        self._callbacks.clear()

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in self._callbacks:
                self._callbacks[msg.wParam]()
                return True, 0
        return False, 0


def get_foreground_window() -> int | None:
    if not IS_WINDOWS:
        return None
    return _user32.GetForegroundWindow()


def set_foreground_window(hwnd: int | None):
    if IS_WINDOWS and hwnd:
        _user32.SetForegroundWindow(hwnd)

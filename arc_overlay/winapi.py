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
VK_L = 0x4C
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
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


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


# --- окно игры ----------------------------------------------------------------

# Процесс игры — PioneerGame.exe (…\steamapps\common\Arc Raiders\…). Запасной вариант —
# заголовок окна «ARC Raiders», если это окно не браузера и не мессенджера.
GAME_PROCESS_PREFIXES = ("pioneergame",)
NOT_GAME_PROCESSES = {"chrome", "msedge", "firefox", "opera", "browser", "brave", "vivaldi", "yandex",
                      "steam", "steamwebhelper", "discord", "telegram", "explorer"}


def window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def window_process(hwnd: int) -> tuple[int, str]:
    """(pid, имя exe без расширения в нижнем регистре)."""
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            name = buffer.value.replace("/", "\\").rsplit("\\", 1)[-1].lower().removesuffix(".exe")
        _kernel32.CloseHandle(handle)
    return pid.value, name


def is_game_window(title: str, process: str) -> bool:
    if process.startswith(GAME_PROCESS_PREFIXES):
        return True
    return title.strip().lower().startswith("arc raiders") and process not in NOT_GAME_PROCESSES


def foreground_info() -> tuple[int, int, bool] | None:
    """(hwnd, pid, это окно игры) для активного окна; None не в Windows."""
    if not IS_WINDOWS:
        return None
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return 0, 0, False
    pid, process = window_process(hwnd)
    return hwnd, pid, is_game_window(window_title(hwnd), process)


def window_alive(hwnd: int) -> bool:
    return bool(IS_WINDOWS and hwnd and _user32.IsWindow(hwnd) and _user32.IsWindowVisible(hwnd))


def find_game_window() -> int:
    """Ищет окно игры среди всех окон (0 — игра не запущена)."""
    if not IS_WINDOWS:
        return 0
    found = []

    def callback(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            title = window_title(hwnd)
            if title and is_game_window(title, window_process(hwnd)[1]):
                found.append(hwnd)
                return False
        return True

    _user32.EnumWindows(_WNDENUMPROC(callback), 0)
    return found[0] if found else 0

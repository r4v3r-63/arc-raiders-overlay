from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QKeySequence

from arc_overlay.system import shortcuts, winapi


def test_to_native_converts_common_keys(qapp):
    assert shortcuts.to_native("Ctrl+Shift+Q") == (winapi.MOD_CONTROL | winapi.MOD_SHIFT, ord("Q"))
    assert shortcuts.to_native("Ctrl+Shift+Right") == (winapi.MOD_CONTROL | winapi.MOD_SHIFT, 0x27)
    assert shortcuts.to_native("Alt+F5") == (winapi.MOD_ALT, 0x74)
    assert shortcuts.to_native("Ctrl+Shift+Tab")[1] == 0x09
    assert shortcuts.to_native("Q") is None  # без модификатора нельзя
    assert shortcuts.to_native("") is None


def test_defaults_are_valid_and_unique(qapp):
    natives = [shortcuts.to_native(d) for d in shortcuts.DEFAULTS.values()]
    assert all(natives) and len(set(natives)) == len(natives)


def test_save_and_load(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    bindings = shortcuts.bindings()
    bindings["input"] = "Alt+Q"
    shortcuts.save(settings, bindings)
    assert shortcuts.key("input") == "Alt+Q"
    shortcuts.load(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    assert shortcuts.key("input") == "Alt+Q"
    shortcuts.save(settings, dict(shortcuts.DEFAULTS))  # вернуть как было
    assert shortcuts.key("input") == "Ctrl+Shift+Q"
    assert shortcuts.key("next_step") == "Ctrl+Shift+→"


def test_window_rejects_duplicates_and_bare_keys(qapp):
    from arc_overlay.ui.hotkeys_window import HotkeysWindow

    w = HotkeysWindow()
    w.open(dict(shortcuts.DEFAULTS))
    assert w.problems() == [] and w._save.isEnabled()
    w._edits["help"].setKeySequence(QKeySequence("Ctrl+Shift+Q"))
    assert any("дважды" in p for p in w.problems()) and not w._save.isEnabled()
    w._edits["help"].setKeySequence(QKeySequence("H"))
    assert any("не подходит" in p for p in w.problems())
    saved = []
    w.saved.connect(saved.append)
    w._reset_all()
    w._on_save()
    assert saved and saved[0]["input"] == "Ctrl+Shift+Q"

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_system_side_effects(monkeypatch):
    """Тесты не занимают настоящие горячие клавиши Windows и не показывают окна, ждущие нажатия:
    на сервере сборки их некому закрыть, и тесты зависли бы."""
    from PyQt6.QtWidgets import QMessageBox

    from arc_overlay.system import winapi

    monkeypatch.setattr(winapi.HotkeyManager, "register", lambda self, *args, **kwargs: True)
    for name in ("warning", "information", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok))

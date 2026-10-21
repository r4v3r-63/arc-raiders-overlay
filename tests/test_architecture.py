"""Правила слоёв (см. docs/ARCHITECTURE.md): нарушение ловится тестом, а не на ревью."""

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "arc_overlay"


def imports(layer: str) -> list[tuple[str, str]]:
    found = []
    for path in (PACKAGE / layer).glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.match(r"\s*(from|import) ", line):
                found.append((path.name, line.strip()))
    return found


def test_core_has_no_windows_qt_or_system():
    bad = [(f, line) for f, line in imports("core") if "PyQt" in line or "..system" in line or "..ui" in line]
    assert bad == [], "core/ — чистые правила: без окон, Qt и обращений к Windows/сети"


def test_system_does_not_know_about_windows_of_the_program():
    bad = [(f, line) for f, line in imports("system") if "..ui" in line or "..core" in line]
    assert bad == [], "system/ не зависит от окон программы и её правил"


def test_ui_does_not_reach_into_app():
    bad = [(f, line) for f, line in imports("ui") if re.search(r"\.\.(app|main)\b", line)]
    assert bad == [], "окна получают данные от OverlayApp, а не обращаются к нему сами"

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_freshness as cf  # noqa: E402


def test_only_content_updates_count():
    news = [
        {"title": "Hotfix 2.1.1", "date": 1792143336},
        {"title": "Store Update 2.1.0", "date": 1791900000},
        {"title": "FROZEN TRAIL - 2.0 Update", "date": 1791451880},
        {"title": "Play ARC Raiders for FREE", "date": 1791999999},
    ]
    title, _ = cf.last_game_update(news)
    assert title == "FROZEN TRAIL - 2.0 Update"


def test_lagging_only_after_grace_period():
    update = ("Live Update 3.0", date(2026, 11, 1))
    stale = {"arctracker.io": date(2026, 10, 20)}
    assert not cf.check(update, stale, date(2026, 11, 3))[0]  # неделя ещё не прошла
    lagging, report = cf.check(update, stale, date(2026, 11, 10))
    assert lagging and "Live Update 3.0" in report
    assert not cf.check(update, {"arctracker.io": date(2026, 11, 2)}, date(2026, 11, 10))[0]
    assert not cf.check(None, stale, date(2026, 11, 10))[0]

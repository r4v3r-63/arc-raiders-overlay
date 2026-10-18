"""Не отстаёт ли база от игры: сравнивает дату последнего обновления игры с датами источников.

Обновления игры берутся из новостей Steam: учитываются только контентные («Live Update 1.45.0»,
«FROZEN TRAIL - 2.0 Update»), а еженедельные обновления магазина и хотфиксы — нет, в них новых
предметов и квестов обычно не бывает.

Если после обновления прошло больше GRACE_DAYS дней, а источники так и не обновились, база
считается отстающей. Результат — файл freshness.md (текст для задачи на GitHub) и строка
lagging=true/false в $GITHUB_OUTPUT; задачу открывает или закрывает workflow update-db.

Использование:
    python tools/check_freshness.py путь/к/arcraiders-data
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

STEAM_APP_ID = 1808500
STEAM_NEWS = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
              f"?appid={STEAM_APP_ID}&count=40&maxlength=1&feeds=steam_community_announcements")
ARCTRACKER_API = "https://arctracker.io/api/"
GRACE_DAYS = 7  # столько дней даём источникам, чтобы добавить новое после обновления игры
REPORT_PATH = Path("freshness.md")
USER_AGENT = "arc-raiders-overlay (github.com/r4v3r-63/arc-raiders-overlay)"


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def is_content_update(title: str) -> bool:
    """«Live Update 1.45.0», «FROZEN TRAIL - 2.0 Update», «Patch Notes 1.29.0» — да; магазин и хотфиксы — нет."""
    return bool(re.search(r"\d+\.\d+", title)) and not re.search(r"store|hotfix|survey|beta", title, re.I)


def last_game_update(news: list[dict]) -> tuple[str, date] | None:
    """(название, дата) последнего контентного обновления игры."""
    updates = [(n["title"], datetime.fromtimestamp(n["date"], timezone.utc).date())
               for n in news if is_content_update(n.get("title", ""))]
    return max(updates, key=lambda u: u[1]) if updates else None


def source_dates(data_dir: Path) -> dict[str, date]:
    """Когда источники данных последний раз менялись."""
    dates = {}
    try:
        stamp = subprocess.run(["git", "-C", str(data_dir), "log", "-1", "--format=%cs"],
                               capture_output=True, text=True, check=True).stdout.strip()
        dates["arcraiders-data"] = date.fromisoformat(stamp)
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    try:
        items = get_json(ARCTRACKER_API + "items")["items"]
        stamps = [datetime.strptime(i["updatedAt"], "%m/%d/%Y").date() for i in items if i.get("updatedAt")]
        quests = get_json(ARCTRACKER_API + "quests")
        stamps.append(date.fromisoformat(quests["lastUpdated"][:10]))
        dates["arctracker.io"] = max(stamps)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return dates


def check(update: tuple[str, date] | None, sources: dict[str, date], today: date) -> tuple[bool, str]:
    """(отстаёт ли база, текст отчёта)."""
    if update is None or not sources:
        return False, "Не удалось узнать дату обновления игры или источников — проверка пропущена."
    title, released = update
    freshest = max(sources.values())
    lagging = freshest < released and (today - released).days >= GRACE_DAYS
    lines = [
        f"Последнее обновление игры: **{title}** от {released:%d.%m.%Y}.",
        "",
        "Источники данных последний раз обновлялись:",
        *[f"- {name}: {when:%d.%m.%Y}" for name, when in sorted(sources.items())],
        "",
    ]
    if lagging:
        lines += [
            f"Прошло {(today - released).days} дн. после обновления игры, а источники так и не обновились. "
            "Новых предметов, квестов и мастерских из этого обновления в программе может не быть.",
            "",
            "Что можно сделать:",
            "- ничего — когда источники обновятся, ежедневная сборка подтянет новое сама, "
            "а эта задача закроется автоматически;",
            "- или попросить Claude поискать другой источник с новыми данными.",
        ]
    else:
        lines.append("База не отстаёт от игры.")
    return lagging, "\n".join(lines)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    try:
        update = last_game_update(get_json(STEAM_NEWS)["appnews"]["newsitems"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Новости Steam недоступны: {error!r}")
        update = None
    lagging, report = check(update, source_dates(Path(sys.argv[1])), datetime.now(timezone.utc).date())
    print(report)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    for name in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        if os.environ.get(name):
            with open(os.environ[name], "a", encoding="utf-8") as f:
                f.write(f"lagging={'true' if lagging else 'false'}\n" if name == "GITHUB_OUTPUT" else report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

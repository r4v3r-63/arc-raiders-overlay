"""Предметы: нужен ли предмет игроку и где его искать.

Предмет находится по названию во всплывающей подсказке игры (снимок экрана + распознавание
текста Windows, как у импорта квестов) или через поиск по названию. Дальше по базе: нужен ли
он для квестов и улучшения мастерских, на что разбирается, сколько стоит и где искать.

Где искать: в базе у предмета есть типы мест с лутом (механические, медицина…), а у мест на
картах — их типы. Карты ранжируются по числу подходящих мест. Это не точная статистика
выпадения, а ориентир: где таких мест больше, там и шансов больше.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .quest_db import Item, Quest, QuestDB, normalize

MATCH_CUTOFF = 0.88  # распознавание иногда путает буквы; короткие названия сравниваем только точно
FUZZY_MIN_LENGTH = 6
HEIGHT_TOLERANCE = 0.8  # заголовок подсказки крупнее остального текста: берём самые крупные строки

# строка распознанного текста: (текст, x, y, ширина, высота) в пикселях снимка
Line = tuple[str, float, float, float, float]


def parse_required(text: str) -> tuple[int, str]:
    """«3× Провода» → (3, «Провода»)."""
    match = re.match(r"^\s*(\d+)\s*[×x]\s*(.+)$", text)
    return (int(match.group(1)), match.group(2).strip()) if match else (1, text.strip())


def _index(db: QuestDB) -> dict[str, Item]:
    index: dict[str, Item] = {}
    for item in db.items.values():
        for name in (item.name, item.en):
            key = normalize(name)
            if len(key) >= 3:
                index.setdefault(key, item)
    return index


def match_item(db: QuestDB, lines: list[Line], cursor: tuple[float, float]) -> Item | None:
    """Предмет из подсказки: среди строк-названий самая крупная, при равенстве — ближайшая к курсору."""
    index = _index(db)
    long_keys = [k for k in index if len(k) >= FUZZY_MIN_LENGTH]
    found = []
    for text, x, y, w, h in lines:
        key = normalize(text)
        item = index.get(key)
        if item is None and len(key) >= FUZZY_MIN_LENGTH:
            close = difflib.get_close_matches(key, long_keys, n=1, cutoff=MATCH_CUTOFF)
            item = index[close[0]] if close else None
        if item is not None:
            distance = ((x + w / 2 - cursor[0]) ** 2 + (y + h / 2 - cursor[1]) ** 2) ** 0.5
            found.append((item, h, distance))
    if not found:
        return None
    tallest = max(h for _, h, _ in found)
    return min((f for f in found if f[1] >= tallest * HEIGHT_TOLERANCE), key=lambda f: f[2])[0]


@dataclass
class MapSpots:
    map_id: str
    name: str
    rooms: list[dict]  # места карты с подходящим типом лута: {"name", "x", "y", "types"}


@dataclass
class Where:
    types: list[str] = field(default_factory=list)  # «механические (Mechanical)»
    maps: list[MapSpots] = field(default_factory=list)  # сначала карты, где подходящих мест больше
    drops: list[str] = field(default_factory=list)  # «Оса (Поле битвы у дамбы, Космопорт)»
    sources: list[str] = field(default_factory=list)  # предметы, при разборке которых он получается


def where_to_find(db: QuestDB, item: Item) -> Where:
    where = Where()
    wanted = set(item.found)
    where.types = [f"{db.loot_types[t]} ({t})" if t in db.loot_types else t for t in item.found]
    for game_map in db.maps.values():
        rooms = [r for r in game_map.rooms if wanted & set(r.get("types", []))]
        if rooms:
            where.maps.append(MapSpots(game_map.id, game_map.name_ru or game_map.name, rooms))
    where.maps.sort(key=lambda spots: -len(spots.rooms))
    for drop in item.drops[:6]:
        maps = [db.maps[m].name_ru or db.maps[m].name for m in drop.get("maps", []) if m in db.maps]
        where.drops.append(drop["name"] + (f" ({', '.join(maps)})" if maps else ""))
    where.sources = sorted(i.name for i in db.items.values() if item.id in i.recycles)
    return where


@dataclass
class ItemReport:
    item: Item
    verdict: str
    keep: bool  # нужен прямо сейчас: для активного квеста или следующего уровня мастерской
    quests: list[tuple[str, int]] = field(default_factory=list)  # активные квесты: (название, штук)
    later_quests: list[str] = field(default_factory=list)  # ещё не взятые квесты
    workshops: list[tuple[str, int, int]] = field(default_factory=list)  # следующий уровень: (мастерская, ур., штук)
    later_workshops: list[tuple[str, int, int]] = field(default_factory=list)
    recycles: list[tuple[str, int]] = field(default_factory=list)  # (предмет, штук) при разборке
    where: Where = field(default_factory=Where)


def _needs(quest: Quest, item: Item) -> int:
    wanted = {normalize(item.name), normalize(item.en)}
    return sum(qty for qty, name in map(parse_required, quest.required_items) if normalize(name) in wanted)


def item_report(db: QuestDB, item: Item, active: list[Quest], completed: list[str],
                workshop_levels: dict[str, int]) -> ItemReport:
    """Нужен ли предмет. workshop_levels — уровни мастерских, которые отметил игрок (id → уровень)."""
    active_ids = {q.id for q in active}
    report = ItemReport(item, "", False)
    for quest in active:
        if qty := _needs(quest, item):
            report.quests.append((quest.name, qty))
    for quest in db.quests:
        if quest.id not in active_ids and quest.id not in completed and _needs(quest, item):
            report.later_quests.append(quest.name)
    for workshop in db.workshops:
        tracked = workshop.id in workshop_levels
        current = workshop_levels.get(workshop.id, 0)
        for level in workshop.levels:
            qty = level["items"].get(item.id, 0)
            if not qty or (tracked and level["level"] <= current):
                continue
            entry = (workshop.name, level["level"], qty)
            if tracked and level["level"] == current + 1:
                report.workshops.append(entry)
            else:
                report.later_workshops.append(entry)
    report.recycles = [(db.items[i].name if i in db.items else i, qty) for i, qty in item.recycles.items()]
    report.where = where_to_find(db, item)
    report.keep = bool(report.quests or report.workshops)
    if report.keep:
        report.verdict = "Оставить — нужен сейчас"
    elif report.later_quests or report.later_workshops:
        report.verdict = "Пригодится позже"
    else:
        report.verdict = "Можно продать или разобрать"
    return report


def workshop_shopping(db: QuestDB, workshop_levels: dict[str, int]) -> list[tuple[str, int, str]]:
    """Что нужно для следующего уровня отмеченных мастерских: [(предмет, штук, «Мастерская → ур. N»)]."""
    rows = []
    for workshop in db.workshops:
        if workshop.id not in workshop_levels:
            continue
        nxt = workshop_levels[workshop.id] + 1
        for item_id, qty in workshop.requirements(nxt).items():
            name = db.items[item_id].name if item_id in db.items else item_id
            rows.append((name, qty, f"{workshop.name} → ур. {nxt}"))
    return rows

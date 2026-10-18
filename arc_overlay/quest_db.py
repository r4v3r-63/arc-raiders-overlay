"""Загрузка базы квестов и поиск квеста по названию (по-русски или по-английски)."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "quests.json"
# Отсюда программа скачивает свежую базу и недостающие скриншоты (их обновляет GitHub Actions).
REMOTE_DATA_URL = "https://raw.githubusercontent.com/r4v3r-63/arc-raiders-overlay/main/arc_overlay/data/"


@dataclass
class GameMap:
    id: str
    name: str
    name_ru: str = ""
    aliases: list[str] = field(default_factory=list)
    image: str = ""  # картинка карты (путь внутри data)
    rooms: list[dict] = field(default_factory=list)  # места: {"name", "x", "y"}, координаты 0..1


@dataclass
class Item:
    id: str
    name: str
    en: str = ""
    value: int = 0  # цена продажи, монет
    recycles: dict[str, int] = field(default_factory=dict)  # id предмета → сколько получится при разборке
    found: list[str] = field(default_factory=list)  # типы мест с лутом, где лежит: Mechanical, Medical…
    drops: list[dict] = field(default_factory=list)  # машины ARC, из которых выпадает: {"name", "maps"}
    craft: dict | None = None  # {"benches": [id], "level": ур. верстака, "recipe": {id: штук}, "quantity": штук}
    vendors: list[dict] = field(default_factory=list)  # {"trader", "cost": {валюта или id: сколько}, "limit", "level"}
    unlocks: str = ""  # для чертежа: id предмета, который он открывает
    blueprint: str = ""  # для предмета: id чертежа, без которого его не скрафтить


@dataclass
class Workshop:
    id: str
    name: str
    levels: list[dict] = field(default_factory=list)  # {"level": 2, "items": {id предмета: штук}}

    @property
    def max_level(self) -> int:
        return max((level["level"] for level in self.levels), default=0)

    def requirements(self, level: int) -> dict[str, int]:
        return next((dict(lv["items"]) for lv in self.levels if lv["level"] == level), {})


@dataclass
class Quest:
    name: str
    steps: list[str]
    aliases: list[str] = field(default_factory=list)
    trader: str = ""
    locations: list[str] = field(default_factory=list)  # id карт; пусто — любая карта
    one_round: bool = False
    required_items: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    guide: dict | None = None  # {"text": [...], "images": [{"file", "caption"}]} с вики
    wiki_url: str = ""
    steam_url: str | None = None
    video_url: str = ""
    official_name: bool = True
    id: str = ""
    next: list[str] = field(default_factory=list)  # id квестов, которые открываются после этого
    places: list[dict] = field(default_factory=list)  # точки на карте: {"map", "name", "x", "y", "step"}

    @property
    def english_name(self) -> str:
        return self.aliases[0] if self.aliases else ""


def normalize(text: str) -> str:
    """Нижний регистр, ё → е, без кавычек и знаков препинания, одиночные пробелы."""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text).replace("_", " ")
    return " ".join(text.split())


class QuestDB:
    def __init__(self, quests: list[Quest], maps: list[GameMap] | None = None, generated_at: str = "",
                 items: list[Item] | None = None, workshops: list[Workshop] | None = None,
                 loot_types: dict[str, str] | None = None, benches: dict[str, str] | None = None):
        self.generated_at = generated_at  # дата сборки базы, ISO 8601 (UTC)
        self.items = {i.id: i for i in items or []}
        self.workshops = list(workshops or [])
        self.loot_types = dict(loot_types or {})  # тип места с лутом → по-русски
        self.benches = dict(benches or {})  # где крафтится: id верстака → по-русски
        self._item_by_name: dict[str, Item] = {}
        for item in self.items.values():
            for name in (item.name, item.en):
                if name:
                    self._item_by_name.setdefault(normalize(name), item)
        self.quests = quests
        self._by_id = {q.id: q for q in quests if q.id}
        self.maps = {m.id: m for m in maps or []}
        self._by_name: dict[str, Quest] = {}
        for q in quests:
            for name in [q.name, *q.aliases]:
                self._by_name.setdefault(normalize(name), q)
        self._map_by_name: dict[str, GameMap] = {}
        for m in self.maps.values():
            for name in [m.name, m.name_ru, *m.aliases]:
                self._map_by_name.setdefault(normalize(name), m)

    @classmethod
    def load(cls, path: Path = DEFAULT_DB_PATH) -> "QuestDB":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def from_dict(cls, data: dict) -> "QuestDB":
        maps = [
            GameMap(id=m["id"], name=m["name"], name_ru=m.get("name_ru", ""), aliases=list(m.get("aliases", [])),
                    image=m.get("image", ""), rooms=list(m.get("rooms", [])))
            for m in data.get("maps", [])
        ]
        quests = [
            Quest(
                name=item["name"],
                steps=list(item.get("steps", [])),
                aliases=list(item.get("aliases", [])),
                trader=item.get("trader", ""),
                locations=list(item.get("locations", [])),
                one_round=bool(item.get("one_round", False)),
                required_items=list(item.get("required_items", [])),
                hints=list(item.get("hints", [])),
                guide=item.get("guide"),
                wiki_url=item.get("wiki_url", ""),
                steam_url=item.get("steam_url"),
                video_url=item.get("video_url", ""),
                official_name=item.get("official_name", True),
                id=item.get("id", ""),
                next=list(item.get("next", [])),
                places=list(item.get("places", [])),
            )
            for item in data.get("quests", [])
        ]
        items = [Item(id=i["id"], name=i["name"], en=i.get("en", ""), value=int(i.get("value", 0)),
                      recycles=dict(i.get("recycles", {})), found=list(i.get("found", [])),
                      drops=list(i.get("drops", [])), craft=i.get("craft"), vendors=list(i.get("vendors", [])),
                      unlocks=i.get("unlocks", ""), blueprint=i.get("blueprint", "")) for i in data.get("items", [])]
        workshops = [Workshop(id=w["id"], name=w["name"], levels=list(w.get("levels", [])))
                     for w in data.get("workshops", [])]
        return cls(quests, maps, data.get("generated_at", ""), items, workshops, data.get("loot_types", {}),
                   data.get("benches", {}))

    def names(self) -> list[str]:
        return [q.name for q in self.quests]

    def find(self, query: str) -> Quest | None:
        """Ищет квест: точное совпадение, затем по подстроке, затем с учётом опечаток."""
        return _lookup(query, self._by_name)

    def find_exact(self, name: str) -> Quest | None:
        """Точное совпадение названия (без учёта регистра, «ё» и знаков препинания)."""
        return self._by_name.get(normalize(name))

    def find_by_id(self, quest_id: str) -> Quest | None:
        return self._by_id.get(quest_id)

    def add(self, quest: Quest):
        self.quests.append(quest)
        if quest.id:
            self._by_id.setdefault(quest.id, quest)
        for name in [quest.name, *quest.aliases]:
            self._by_name.setdefault(normalize(name), quest)

    def suggest(self, query: str, limit: int = 10) -> list[str]:
        """Названия квестов для автодополнения: сначала начинающиеся с введённого, потом содержащие."""
        return _suggest(query, [(q.name, [q.name, *q.aliases]) for q in self.quests], limit)

    def find_item(self, query: str) -> Item | None:
        """Предмет по названию (русскому или английскому): точно или единственный по подстроке."""
        key = normalize(query)
        if not key:
            return None
        if key in self._item_by_name:
            return self._item_by_name[key]
        partial = {i.id: i for k, i in self._item_by_name.items() if key in k}
        return next(iter(partial.values())) if len(partial) == 1 else None

    def suggest_items(self, query: str, limit: int = 10) -> list[str]:
        """Названия предметов для автодополнения."""
        return _suggest(query, [(i.name, [i.name, i.en]) for i in self.items.values()], limit)

    def similar_items(self, query: str, limit: int = 5) -> list[str]:
        """Похожие названия, если точного предмета нет: по совпавшим словам, затем с учётом опечаток."""
        typed = [w for w in normalize(query).split() if len(w) >= 4]

        def matches(w: str, word: str) -> bool:
            # начало слова без окончания («батарейка» → «батаре…») или целое слово внутри («турбонасос»)
            return word.startswith(w[:max(4, len(w) - 2)]) or (len(w) >= 5 and w in word)

        scored = []
        for item in self.items.values():
            words = normalize(item.name).split()
            score = sum(1 for w in typed if any(matches(w, word) for word in words))
            if score:
                scored.append((-score, item.name))
        result = [name for _, name in sorted(scored)]
        if result:
            return result[:limit]
        close = difflib.get_close_matches(normalize(query), list(self._item_by_name), n=3, cutoff=0.6)
        result += [self._item_by_name[key].name for key in close]
        return list(dict.fromkeys(result))[:limit]

    def find_map_exact(self, name: str) -> GameMap | None:
        return self._map_by_name.get(normalize(name))

    def map_names(self, quest: Quest) -> list[str]:
        return [(self.maps[m].name_ru or self.maps[m].name) if m in self.maps else m for m in quest.locations]


def _lookup(query: str, index: dict):
    query = normalize(query)
    if not query:
        return None
    if query in index:
        return index[query]
    partial = {id(v): v for key, v in index.items() if query in key}
    if len(partial) == 1:
        return next(iter(partial.values()))
    close = difflib.get_close_matches(query, list(index), n=1, cutoff=0.6)
    if close:
        return index[close[0]]
    return None


def _suggest(query: str, entries: list[tuple[str, list[str]]], limit: int) -> list[str]:
    """entries: (что показать, [названия, по которым искать])."""
    query = normalize(query)
    if not query:
        return []
    ranked = []
    for display, names in entries:
        keys = [normalize(n) for n in names if n]
        if any(k.startswith(query) for k in keys):
            rank = 0
        elif any(f" {query}" in f" {k}" for k in keys):
            rank = 1  # с начала одного из слов
        elif any(query in k for k in keys):
            rank = 2
        else:
            continue
        ranked.append((rank, display.lower(), display))
    result = []
    for _, _, display in sorted(ranked):
        if display not in result:
            result.append(display)
    return result[:limit]

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
    def __init__(self, quests: list[Quest], maps: list[GameMap] | None = None, generated_at: str = ""):
        self.generated_at = generated_at  # дата сборки базы, ISO 8601 (UTC)
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
        return cls(quests, maps, data.get("generated_at", ""))

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

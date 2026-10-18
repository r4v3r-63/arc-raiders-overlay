"""Загрузка базы квестов и поиск квеста по названию (по-русски или по-английски)."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "quests.json"


@dataclass
class GameMap:
    id: str
    name: str
    name_ru: str = ""
    aliases: list[str] = field(default_factory=list)


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

    @property
    def english_name(self) -> str:
        return self.aliases[0] if self.aliases else ""


def normalize(text: str) -> str:
    """Нижний регистр, ё → е, без кавычек и знаков препинания, одиночные пробелы."""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text).replace("_", " ")
    return " ".join(text.split())


class QuestDB:
    def __init__(self, quests: list[Quest], maps: list[GameMap] | None = None):
        self.quests = quests
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
            data = json.load(f)
        maps = [
            GameMap(id=m["id"], name=m["name"], name_ru=m.get("name_ru", ""), aliases=list(m.get("aliases", [])))
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
            )
            for item in data.get("quests", [])
        ]
        return cls(quests, maps)

    def names(self) -> list[str]:
        return [q.name for q in self.quests]

    def find(self, query: str) -> Quest | None:
        """Ищет квест: точное совпадение, затем по подстроке, затем с учётом опечаток."""
        return _lookup(query, self._by_name)

    def find_exact(self, name: str) -> Quest | None:
        """Точное совпадение названия (без учёта регистра, «ё» и знаков препинания)."""
        return self._by_name.get(normalize(name))

    def add(self, quest: Quest):
        self.quests.append(quest)
        for name in [quest.name, *quest.aliases]:
            self._by_name.setdefault(normalize(name), quest)

    def find_map_exact(self, name: str) -> GameMap | None:
        return self._map_by_name.get(normalize(name))

    def find_map(self, query: str) -> GameMap | None:
        return _lookup(query, self._map_by_name)

    def map_names(self, quest: Quest) -> list[str]:
        return [(self.maps[m].name_ru or self.maps[m].name) if m in self.maps else m for m in quest.locations]

    def available_at(self, quest: Quest, location: str) -> bool:
        """False, только если карта распознана и квест на ней точно не выполняется."""
        if not quest.locations:
            return True
        game_map = self.find_map(location)
        return game_map is None or game_map.id in quest.locations


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

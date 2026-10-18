"""Загрузка базы квестов и поиск квеста по названию."""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "quests.json"

# Значение в списке локаций, означающее «на любой карте».
ANY_LOCATION = "any"


@dataclass
class Quest:
    name: str
    steps: list[str]
    trader: str = ""
    locations: list[str] = field(default_factory=list)
    required_items: list[str] = field(default_factory=list)
    wiki_url: str = ""

    def available_at(self, location: str) -> bool:
        """Можно ли выполнять квест на указанной локации (пустая локация — не проверяем)."""
        location = _normalize(location)
        if not location or not self.locations:
            return True
        normalized = [_normalize(loc) for loc in self.locations]
        return ANY_LOCATION in normalized or location in normalized


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


class QuestDB:
    def __init__(self, quests: list[Quest]):
        self.quests = quests
        self._by_name = {_normalize(q.name): q for q in quests}

    @classmethod
    def load(cls, path: Path = DEFAULT_DB_PATH) -> "QuestDB":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        quests = [
            Quest(
                name=item["name"],
                steps=list(item.get("steps", [])),
                trader=item.get("trader", ""),
                locations=list(item.get("locations", [])),
                required_items=list(item.get("required_items", [])),
                wiki_url=item.get("wiki_url", ""),
            )
            for item in data.get("quests", [])
        ]
        return cls(quests)

    def names(self) -> list[str]:
        return [q.name for q in self.quests]

    def find(self, query: str) -> Quest | None:
        """Ищет квест: точное совпадение, затем по подстроке, затем с учётом опечаток."""
        query = _normalize(query)
        if not query:
            return None
        if query in self._by_name:
            return self._by_name[query]
        partial = [q for key, q in self._by_name.items() if query in key]
        if len(partial) == 1:
            return partial[0]
        close = difflib.get_close_matches(query, list(self._by_name), n=1, cutoff=0.6)
        if close:
            return self._by_name[close[0]]
        return None

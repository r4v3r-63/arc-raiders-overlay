"""Прогресс прохождения: активные квесты, шаг в каждом и выполненные квесты.

Хранится в «Данные\\прогресс.json» рядом с программой и переживает перезапуск.
Квест запоминается по id и названию: id стабилен в базе, а по названию находятся
квесты, которые подтягиваются из руководства Steam уже после запуска.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .items import parse_required
from .quest_db import Quest, QuestDB

AUTO_ADD_LIMIT = 3  # если после квеста открывается больше квестов, сами они не добавляются


@dataclass
class ActiveQuest:
    id: str
    name: str
    step: int = 0


@dataclass
class Progress:
    path: Path
    active: list[ActiveQuest] = field(default_factory=list)
    current: int = 0
    completed: list[str] = field(default_factory=list)  # id выполненных квестов
    workshops: dict[str, int] = field(default_factory=dict)  # уровни мастерских, которые отметил игрок
    blueprints: list[str] = field(default_factory=list)  # id изученных чертежей

    @classmethod
    def load(cls, path: Path) -> Progress:
        progress = cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("active", []), list):
                raise ValueError("неожиданный формат")
        except FileNotFoundError:
            return progress
        except (OSError, ValueError) as error:
            # Испорченный файл не затираем молча: копия остаётся рядом, начинаем с чистого листа.
            print(f"прогресс не прочитан: {error}")
            try:
                path.replace(path.with_name(path.name + ".bad"))
            except OSError:
                pass
            return progress
        for item in data.get("active", []):
            try:  # испорченная запись пропускается, остальные квесты сохраняются
                progress.active.append(ActiveQuest(str(item["id"]), str(item["name"]), int(item.get("step", 0))))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        try:
            progress.current = int(data.get("current", 0))
            progress.completed = [str(i) for i in data.get("completed", [])]
            progress.workshops = {str(k): int(v) for k, v in data.get("workshops", {}).items()}
            progress.blueprints = [str(i) for i in data.get("blueprints", [])]
        except (TypeError, ValueError, AttributeError):
            pass
        progress._clamp()
        return progress

    def save(self):
        data = {"active": [asdict(a) for a in self.active], "current": self.current, "completed": self.completed,
                "workshops": self.workshops, "blueprints": self.blueprints}
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as error:  # файл занят антивирусом или синхронизацией — сохранится в следующий раз
            print(f"прогресс не сохранён: {error}")

    def _clamp(self):
        self.current = max(0, min(self.current, len(self.active) - 1)) if self.active else 0

    # --- чтение -----------------------------------------------------------

    def current_entry(self) -> ActiveQuest | None:
        return self.active[self.current] if self.active else None

    def resolve(self, db: QuestDB, entry: ActiveQuest | None) -> Quest | None:
        if entry is None:
            return None
        return db.find_by_id(entry.id) or db.find_exact(entry.name)

    def migrate_ids(self, db: QuestDB) -> bool:
        """Квесты, взятые из руководства Steam (id «steam_…»), после появления в основной базе
        получают её id — иначе выполненный квест снова считался бы невыполненным. True — что-то поменялось."""
        changed = False
        for entry in self.active:
            current = db.find_by_id(entry.id)
            if current is None or current.id.startswith("steam_"):
                real = db.find_exact(entry.name)
                if real is not None and real.id and not real.id.startswith("steam_") and real.id != entry.id:
                    entry.id, changed = real.id, True
        by_section = {q.steam_url.rsplit("#", 1)[-1]: q.id for q in db.quests
                      if q.steam_url and "#" in q.steam_url and q.id and not q.id.startswith("steam_")}
        for n, quest_id in enumerate(self.completed):
            real = by_section.get(quest_id.removeprefix("steam_")) if quest_id.startswith("steam_") else None
            if real is not None:
                self.completed[n], changed = real, True
        self.completed = list(dict.fromkeys(self.completed))
        return changed

    # --- изменения --------------------------------------------------------

    def add(self, quest: Quest, make_current: bool = True) -> ActiveQuest:
        """Добавляет квест в активные (если его там нет) и делает текущим."""
        for i, entry in enumerate(self.active):
            if entry.id == quest.id or entry.name == quest.name:
                if make_current:
                    self.current = i
                return entry
        entry = ActiveQuest(quest.id, quest.name)
        self.active.append(entry)
        if make_current:
            self.current = len(self.active) - 1
        if quest.id in self.completed:
            self.completed.remove(quest.id)
        return entry

    def set_step(self, step: int):
        entry = self.current_entry()
        if entry:
            entry.step = step

    def switch(self, delta: int = 1) -> ActiveQuest | None:
        if self.active:
            self.current = (self.current + delta) % len(self.active)
        return self.current_entry()

    def select(self, index: int):
        if 0 <= index < len(self.active):
            self.current = index

    def remove_current(self) -> ActiveQuest | None:
        if not self.active:
            return None
        entry = self.active.pop(self.current)
        self._clamp()
        return entry

    def complete_current(self, db: QuestDB) -> tuple[Quest | None, list[Quest], list[Quest]]:
        """Отмечает текущий квест выполненным.

        Возвращает (выполненный квест, добавленные следующие квесты, открывшиеся, но не добавленные).
        """
        entry = self.current_entry()
        quest = self.resolve(db, entry)
        if entry is None:
            return None, [], []
        self.active.pop(self.current)
        key = quest.id if quest and quest.id else entry.id
        if key not in self.completed:
            self.completed.append(key)
        unlocked = []
        for next_id in (quest.next if quest else []):
            nxt = db.find_by_id(next_id)
            if nxt and nxt.id not in self.completed and not any(a.id == nxt.id for a in self.active) \
                    and all(p in self.completed for p in nxt.previous):  # остальные предшественники выполнены
                unlocked.append(nxt)
        added, skipped = (unlocked, []) if len(unlocked) <= AUTO_ADD_LIMIT else ([], unlocked)
        insert_at = self.current
        for offset, nxt in enumerate(added):
            self.active.insert(insert_at + offset, ActiveQuest(nxt.id, nxt.name))
        self._clamp()
        return quest, added, skipped


def shopping_list(quests: list[Quest], extra: list[tuple[str, int, str]] | None = None
                  ) -> list[tuple[str, int, list[str]]]:
    """Предметы, которые нужно собрать: [(предмет, всего штук, [для чего])], по алфавиту.

    extra — другие нужды, например мастерские: [(предмет, штук, для чего)].
    """
    rows = [(*parse_required(item), quest.name) for quest in quests for item in quest.required_items]
    rows += [(qty, name, purpose) for name, qty, purpose in extra or []]
    totals: dict[str, list] = {}
    for qty, name, purpose in rows:
        entry = totals.setdefault(name.lower(), [name, 0, []])
        entry[1] += qty
        if purpose not in entry[2]:
            entry[2].append(purpose)
    return [tuple(v) for _, v in sorted(totals.items())]

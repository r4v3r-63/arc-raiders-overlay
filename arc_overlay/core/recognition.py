"""Импорт квестов с экрана: какие квесты из базы есть среди строк, распознанных на снимке."""

from __future__ import annotations

import difflib

from .quest_db import Quest, QuestDB, normalize

MATCH_CUTOFF = 0.85  # насколько строка должна совпасть с названием квеста (опечатки распознавания)
MIN_LENGTH = 4
FUZZY_MIN_LENGTH = 8  # короткие названия («Лига», «Тупик») — только точное совпадение, иначе ложные находки


def match_quests(db: QuestDB, lines: list[str]) -> list[Quest]:
    """Квесты, названия которых встречаются среди распознанных строк (по порядку, без повторов)."""
    index = {}
    for quest in db.quests:
        for name in [quest.name, *quest.aliases]:
            key = normalize(name)
            if len(key) >= MIN_LENGTH:
                index.setdefault(key, quest)
    keys = [k for k in index if len(k) >= FUZZY_MIN_LENGTH]
    found: list[Quest] = []
    for line in lines:
        text = normalize(line)
        if len(text) < MIN_LENGTH:
            continue
        quest = index.get(text)
        if quest is None and len(text) >= FUZZY_MIN_LENGTH:
            close = difflib.get_close_matches(text, keys, n=1, cutoff=MATCH_CUTOFF)
            quest = index[close[0]] if close else None
        if quest is not None and quest not in found:
            found.append(quest)
    return found

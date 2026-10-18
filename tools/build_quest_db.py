"""Собирает arc_overlay/data/quests.json из открытой базы RaidTheory/arcraiders-data.

Использование:
    git clone --depth 1 https://github.com/RaidTheory/arcraiders-data
    python tools/build_quest_db.py путь/к/arcraiders-data

В базе есть официальные русские названия квестов и тексты целей из игры.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent.parent / "arc_overlay" / "data" / "quests.json"

TRADERS_RU = {
    "Shani": "Шани",
    "Celeste": "Селеста",
    "Tian Wen": "Тянь Вэнь",
    "Apollo": "Аполлон",
    "Lance": "Лэнс",
}

# Карты: английское название и варианты, по которым её можно ввести.
# Русские варианты взяты из той же базы; их качество не гарантировано,
# поэтому английские названия тоже принимаются.
MAPS = {
    "dam_battlegrounds": ("Dam Battlegrounds", ["дамба", "дамба поля боя", "dam"]),
    "the_spaceport": ("The Spaceport", ["космопорт", "spaceport"]),
    "buried_city": ("Buried City", ["погребенный город"]),
    "the_blue_gate": ("The Blue Gate", ["синие врата", "синяя врата", "blue gate"]),
    "stella_montis": ("Stella Montis", ["звезда горы"]),
    "riven_tides": ("Riven Tides", ["бурные потоки"]),
}
MAP_ID_FIXES = {"stella_montis_upper": "stella_montis", "stella_montis_lower": "stella_montis"}


def text(value: dict, lang: str = "ru") -> str:
    return (value.get(lang) or value.get("en") or "").strip()


def load_item_names(data_dir: Path) -> dict[str, str]:
    names = {}
    for path in (data_dir / "items").glob("*.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        names[item["id"]] = text(item.get("name", {})) or item["id"]
    return names


def build(data_dir: Path) -> dict:
    items = load_item_names(data_dir)
    quests = []
    for path in sorted((data_dir / "quests").glob("*.json")):
        q = json.loads(path.read_text(encoding="utf-8"))
        name_en = text(q["name"], "en")
        maps = []
        for map_id in q.get("map", []):
            map_id = MAP_ID_FIXES.get(map_id, map_id)
            if map_id in MAPS and map_id not in maps:
                maps.append(map_id)
        quests.append({
            "id": q["id"],
            "name": text(q["name"]),
            "aliases": [name_en],
            "trader": TRADERS_RU.get(q.get("trader", ""), q.get("trader", "")),
            "locations": maps,
            "one_round": bool(q.get("objectivesOneRound")),
            "required_items": [
                f"{r['quantity']}× {items.get(r['itemId'], r['itemId'])}" for r in q.get("requiredItemIds", [])
            ],
            "steps": [text(obj) for obj in q.get("objectives", []) if text(obj)],
            "wiki_url": "https://arcraiders.wiki/wiki/" + name_en.replace(" ", "_"),
        })
    return {
        "source": "https://github.com/RaidTheory/arcraiders-data (MIT) — данные игры © Embark Studios AB",
        "maps": [{"id": map_id, "name": name, "aliases": aliases} for map_id, (name, aliases) in MAPS.items()],
        "quests": quests,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    db = build(Path(sys.argv[1]))
    OUT_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Записано квестов: {len(db['quests'])} → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

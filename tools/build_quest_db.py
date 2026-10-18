"""Собирает arc_overlay/data/quests.json и скриншоты гайдов.

Источники:
- RaidTheory/arcraiders-data (MIT) — официальные русские названия, цели, предметы, враги;
- arcraiders.wiki (CC BY-SA 4.0) — гайды со скриншотами и квесты, которых ещё нет в arcraiders-data.

Использование (нужен Pillow: pip install -r requirements-dev.txt):
    git clone --depth 1 https://github.com/RaidTheory/arcraiders-data
    python tools/build_quest_db.py путь/к/arcraiders-data

Английские тексты с вики переводятся по словарю tools/translations/ru.json.
Строки без перевода попадают в базу по-английски и перечисляются в конце вывода —
их нужно добавить в словарь и пересобрать базу.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import steam_guide  # noqa: E402
import wiki  # noqa: E402
from hints_ru import BOTS_RU, LOOT_CATEGORIES_RU  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "arc_overlay" / "data"
OUT_PATH = DATA_DIR / "quests.json"
GUIDES_DIR = DATA_DIR / "guides"
TRANSLATIONS_PATH = Path(__file__).resolve().parent / "translations" / "ru.json"
OFFICIAL_NAMES_PATH = Path(__file__).resolve().parent / "translations" / "official_names.json"
IMAGE_MAX_WIDTH = 720

TRADERS_RU = {
    "Shani": "Шани",
    "Celeste": "Селеста",
    "Tian Wen": "Тянь Вэнь",
    "Apollo": "Аполлон",
    "Lance": "Лэнс",
    "Nomadic Envoys": "Посланник кочевников",
}

# id карты: (английское название, русское название, варианты ввода).
# Русские названия взяты из официальных текстов целей квестов
# («на поле битвы у дамбы», «у Синих ворот») и из русского руководства в Steam.
MAPS = {
    "dam_battlegrounds": ("Dam Battlegrounds", "Поле битвы у дамбы", ["дамба", "поле битвы у дамбы", "dam"]),
    "the_spaceport": ("The Spaceport", "Космопорт", ["космопорт", "spaceport", "space port"]),
    "buried_city": ("Buried City", "Погребенный город", ["погребенный город"]),
    "the_blue_gate": ("The Blue Gate", "Синие ворота", ["синие ворота", "blue gate"]),
    "stella_montis": ("Stella Montis", "Стелла Монтис", ["стелла монтис"]),
    "riven_tides": ("Riven Tides", "Бурные потоки", ["бурные потоки"]),
    "pendola_pass": ("Pendola Pass", "Перевал Пендола", ["перевал пендола", "пендола"]),
}
MAP_ID_FIXES = {"stella_montis_upper": "stella_montis", "stella_montis_lower": "stella_montis"}


def text(value: dict, lang: str = "ru") -> str:
    return (value.get(lang) or value.get("en") or "").strip()


def norm(name: str) -> str:
    return " ".join(name.lower().replace("’", "'").split())


def norm_ru(name: str) -> str:
    """Для сравнения русских названий: без регистра, «ё», кавычек и знаков препинания."""
    name = name.lower().replace("ё", "е")
    return " ".join(re.sub(r"[^\w\s]", " ", name).split())


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm(name)).strip("_")


class Translator:
    def __init__(self, path: Path):
        self.table = json.loads(path.read_text(encoding="utf-8"))
        self.missing: list[str] = []

    def __call__(self, english: str) -> str:
        if english in self.table:
            return self.table[english]
        if english not in self.missing:
            self.missing.append(english)
        return english


def map_ids_from_text(location: str) -> list[str]:
    index = {norm(alias): map_id for map_id, (en, ru, aliases) in MAPS.items() for alias in [en, ru, *aliases]}
    ids = []
    for part in re.split(r"[;,]", location):
        map_id = index.get(norm(part))
        if map_id and map_id not in ids:
            ids.append(map_id)
    return ids


def maps_ru(map_ids: list[str]) -> str:
    return ", ".join(MAPS[m][1] for m in map_ids if m in MAPS)


class Hints:
    """Подсказки для простых целей: где водится враг и где искать предмет."""

    def __init__(self, data_dir: Path):
        self.items = {}
        for path in (data_dir / "items").glob("*.json"):
            item = json.loads(path.read_text(encoding="utf-8"))
            self.items[item["id"]] = item
        self.bots = json.loads((data_dir / "bots.json").read_text(encoding="utf-8"))
        # Длинные названия раньше коротких, чтобы «Wasp Driver» не превратился в «Wasp».
        self.item_names = sorted(
            ((text(i["name"], "en"), i["id"]) for i in self.items.values() if len(text(i["name"], "en")) > 3),
            key=lambda pair: -len(pair[0]),
        )

    def item_ru(self, item_id: str) -> str:
        item = self.items.get(item_id)
        return text(item["name"]) if item else item_id

    def item_id_by_name(self, english: str) -> str | None:
        for name, item_id in self.item_names:
            if norm(name) == norm(english):
                return item_id
        return None

    def for_objectives(self, objectives: list[str], required_ids: list[str]) -> list[str]:
        hints = []
        joined = " ".join(objectives)
        item_ids = list(required_ids)
        rest = joined
        for name, item_id in self.item_names:
            pattern = r"\b" + re.escape(name) + r"s?\b"
            if re.search(pattern, rest, re.I):
                rest = re.sub(pattern, " ", rest, flags=re.I)
                if item_id not in item_ids:
                    item_ids.append(item_id)
        for bot in self.bots:
            if bot["id"] not in BOTS_RU:
                continue
            word = bot["name"].title().removeprefix("The ")
            plural = word[:-1] + "ies" if word.endswith("y") else word + "s"
            if re.search(r"\b(" + re.escape(word) + "|" + re.escape(plural) + r")\b", joined, re.I):
                ru, weakness = BOTS_RU[bot["id"]]
                maps = [MAP_ID_FIXES.get(m, m) for m in bot.get("maps", [])]
                where = maps_ru(list(dict.fromkeys(maps)))
                hints.append(f"«{ru}»: встречается — {where}. Слабое место: {weakness}.")
        for item_id in item_ids:
            item = self.items.get(item_id)
            if not item:
                continue
            droppers = [BOTS_RU[b["id"]][0] for b in self.bots if item_id in b.get("drops", []) and b["id"] in BOTS_RU]
            found = [c.strip() for c in (item.get("foundIn") or "").split(",") if c.strip()]
            parts = []
            if droppers and len(droppers) <= 4:
                parts.append("выпадает из машин: " + ", ".join(f"«{d}»" for d in droppers))
            elif droppers:
                parts.append("выпадает из большинства машин ARC")
            places = [f"{LOOT_CATEGORIES_RU[c]} ({c})" for c in found if c in LOOT_CATEGORIES_RU and c != "ARC"]
            if places:
                parts.append("ищите в местах с лутом: " + ", ".join(places))
            if parts:
                hints.append(f"{text(item['name'])}: " + "; ".join(parts) + ".")
        return hints[:5]


def download_images(quest_id: str, images: list[dict], urls: dict[str, str], tr: Translator) -> list[dict]:
    from PIL import Image

    result = []
    folder = GUIDES_DIR / quest_id
    for n, image in enumerate(images, start=1):
        url = urls.get(image["file"]) or urls.get(image["file"].replace("_", " "))
        if not url:
            print(f"  нет картинки на вики: {image['file']}")
            continue
        target = folder / f"{n:02d}.jpg"
        if not target.exists():
            folder.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": wiki.USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                picture = Image.open(io.BytesIO(resp.read())).convert("RGB")
            if picture.width > IMAGE_MAX_WIDTH:
                picture = picture.resize((IMAGE_MAX_WIDTH, round(picture.height * IMAGE_MAX_WIDTH / picture.width)), Image.LANCZOS)
            picture.save(target, "JPEG", quality=82, optimize=True)
        result.append({
            "file": target.relative_to(DATA_DIR).as_posix(),
            "caption": tr(image["caption"]) if image["caption"] else "",
            "source": "https://arcraiders.wiki/wiki/File:" + urllib.parse.quote(image["file"].replace(" ", "_")),
            "original": url,  # полный размер — программа скачивает его для просмотра на весь экран
        })
    return result


# Карты и места на них (координаты 0..1 от ширины и высоты картинки): фанатский проект
# Speranza Field Guide, данные из arcraiders.wiki (CC BY-SA 4.0).
HUB_RAW = "https://raw.githubusercontent.com/tyler45455/Arc-Raiders-hub/main/"
HUB_MAP_IDS = {"dam-battlegrounds": "dam_battlegrounds", "spaceport": "the_spaceport", "buried-city": "buried_city",
               "the-blue-gate": "the_blue_gate", "stella-montis": "stella_montis", "riven-tides": "riven_tides",
               "pendola-pass": "pendola_pass"}
MAP_IMAGE_WIDTH = 1600


def fetch_maps() -> dict[str, dict]:
    """{id карты: {"image": путь, "rooms": [{"name", "x", "y"}]}}; картинки сохраняются в data/maps."""
    from PIL import Image

    req = urllib.request.Request(HUB_RAW + "api/v1/maps.json", headers={"User-Agent": wiki.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        hub = json.load(resp)["maps"]
    folder = DATA_DIR / "maps"
    folder.mkdir(exist_ok=True)
    result = {}
    for item in hub:
        map_id = HUB_MAP_IDS.get(item["id"])
        if not map_id or not item.get("rooms"):
            continue
        target = folder / f"{map_id}.jpg"
        if not target.exists():
            # Координаты мест заданы относительно этой («detail») картинки.
            url = item.get("image") or f"{HUB_RAW}maps/{item['id']}-detail.jpg"
            url = url.replace("https://tyler45455.github.io/Arc-Raiders-hub/", HUB_RAW)
            req = urllib.request.Request(url, headers={"User-Agent": wiki.USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                picture = Image.open(io.BytesIO(resp.read())).convert("RGB")
            if picture.width > MAP_IMAGE_WIDTH:
                picture = picture.resize((MAP_IMAGE_WIDTH, round(picture.height * MAP_IMAGE_WIDTH / picture.width)),
                                         Image.LANCZOS)
            picture.save(target, "JPEG", quality=85, optimize=True)
        result[map_id] = {
            "image": target.relative_to(DATA_DIR).as_posix(),
            "rooms": [{"name": r["name"], "x": r["x"], "y": r["y"]} for r in item["rooms"]],
        }
    return result


def quest_places(objectives_en: list[str], map_ids: list[str], maps: dict[str, dict]) -> list[dict]:
    """Места на карте, которые упоминаются в целях квеста (по названию места)."""
    places, seen = [], set()
    for step, objective in enumerate(objectives_en):
        text = f" {norm_place(objective)} "
        for map_id in map_ids or list(maps):
            for room in maps.get(map_id, {}).get("rooms", []):
                key = (map_id, room["name"])
                if key not in seen and f" {norm_place(room['name'])} " in text:
                    seen.add(key)
                    places.append({"map": map_id, "name": room["name"], "x": room["x"], "y": room["y"], "step": step})
    return places


def norm_place(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower().replace("’", "'")).split())


MISSING_TRANSLATIONS: list[str] = []


def report_missing_translations():
    """Печатает строки без перевода; в GitHub Actions — ещё и в отчёт о запуске."""
    if not MISSING_TRANSLATIONS:
        return
    lines = [f"Нет перевода для {len(MISSING_TRANSLATIONS)} строк (показаны по-английски), "
             f"добавь их в tools/translations/ru.json:"] + [f"- {s}" for s in MISSING_TRANSLATIONS]
    print("\n" + "\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def build(data_dir: Path) -> dict:
    tr = Translator(TRANSLATIONS_PATH)
    official = {k: v for k, v in json.loads(OFFICIAL_NAMES_PATH.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    hints = Hints(data_dir)
    print("Загружаю страницы квестов с вики…")
    pages = wiki.fetch_quest_pages()
    pages_by_name = {norm(title): (title, text_) for title, text_ in pages.items()}
    guides = {norm(t): g for t, s in pages.items() if (g := wiki.parse_guide(s))}
    all_files = sorted({i["file"] for g in guides.values() for i in g["images"]})
    print(f"Гайдов: {len(guides)}, скриншотов: {len(all_files)}")
    urls = wiki.image_urls(all_files)

    quests = []
    seen = set()
    for path in sorted((data_dir / "quests").glob("*.json")):
        q = json.loads(path.read_text(encoding="utf-8"))
        name_en = text(q["name"], "en")
        maps = []
        for map_id in q.get("map", []):
            map_id = MAP_ID_FIXES.get(map_id, map_id)
            if map_id in MAPS and map_id not in maps:
                maps.append(map_id)
        required = [r["itemId"] for r in q.get("requiredItemIds", [])]
        title = pages_by_name.get(norm(name_en), (name_en, ""))[0]
        aliases = [name_en]
        if name_en in official and norm_ru(official[name_en]) != norm_ru(text(q["name"])):
            aliases.append(official[name_en])
        quests.append({
            "id": q["id"],
            "_next": list(q.get("nextQuestIds", [])),
            "name": text(q["name"]),
            "official_name": True,
            "aliases": aliases,
            "trader": TRADERS_RU.get(q.get("trader", ""), q.get("trader", "")),
            "locations": maps,
            "one_round": bool(q.get("objectivesOneRound")),
            "required_items": [f"{r['quantity']}× {hints.item_ru(r['itemId'])}" for r in q.get("requiredItemIds", [])],
            "steps": [text(obj) for obj in q.get("objectives", []) if text(obj)],
            "_objectives_en": [text(obj, "en") for obj in q.get("objectives", []) if text(obj)],
            "hints": hints.for_objectives([text(o, "en") for o in q.get("objectives", [])], required),
            "wiki_url": "https://arcraiders.wiki/wiki/" + title.replace(" ", "_"),
            "_wiki_key": norm(title),
        })
        seen.add(norm(name_en))

    # Квесты, которые уже есть на вики, но ещё не попали в arcraiders-data.
    for key, (title, source) in sorted(pages_by_name.items()):
        if key in seen:
            continue
        infobox = wiki.parse_infobox(source)
        objectives = wiki.parse_objectives(source)
        required = []
        for name, qty in wiki.parse_required_items(source):
            item_id = hints.item_id_by_name(name)
            required.append((item_id, f"{qty}× {hints.item_ru(item_id) if item_id else name}"))
        quests.append({
            "id": slug(title),
            "_next": [],
            "name": official.get(title) or tr(title),
            "official_name": title in official,
            "aliases": [title],
            "trader": TRADERS_RU.get(infobox.get("trader", ""), infobox.get("trader", "")),
            "locations": map_ids_from_text(infobox.get("location", "")),
            "one_round": "in-one-round" in (wiki.section(source, "Objectives") or ""),
            "required_items": [label for _, label in required],
            "steps": [tr(o) for o in objectives],
            "_objectives_en": objectives,
            "hints": hints.for_objectives(objectives, [i for i, _ in required if i]),
            "wiki_url": "https://arcraiders.wiki/wiki/" + title.replace(" ", "_"),
            "_wiki_key": key,
        })

    # Цепочки квестов: какие квесты открываются после этого (вики + arcraiders-data).
    id_by_name = {norm(q["aliases"][0]): q["id"] for q in quests}
    known_ids = {q["id"] for q in quests}
    for quest in quests:
        source = pages_by_name.get(quest["_wiki_key"], ("", ""))[1]
        names = [n for n in re.split(r"[;,]", wiki.parse_infobox(source).get("next", "")) if n.strip()]
        ids = [i for i in quest.pop("_next") if i in known_ids] + [id_by_name[norm(n)] for n in names if norm(n) in id_by_name]
        quest["next"] = list(dict.fromkeys(i for i in ids if i != quest["id"]))

    print("Загружаю карты и места на них…")
    try:
        maps = fetch_maps()
    except OSError as error:
        print(f"  не удалось: {error}; карты из прошлой базы")
        old = json.loads(OUT_PATH.read_text(encoding="utf-8")) if OUT_PATH.exists() else {}
        maps = {m["id"]: {"image": m["image"], "rooms": m["rooms"]} for m in old.get("maps", []) if m.get("rooms")}
    for quest in quests:
        quest["places"] = quest_places(quest.pop("_objectives_en"), quest["locations"], maps)
    print(f"  карт: {len(maps)}, квестов с точками: {sum(1 for q in quests if q['places'])}")

    print("Загружаю оглавление русского руководства в Steam…")
    try:
        steam = {norm_ru(title): url for title, url in steam_guide.fetch_sections().items()}
    except OSError as error:
        # Steam недоступен — оставляем ссылки из прошлой сборки, программа всё равно обновит их сама.
        print(f"  не удалось: {error}; беру ссылки из прошлой базы")
        steam = {}
        if OUT_PATH.exists():
            for old in json.loads(OUT_PATH.read_text(encoding="utf-8"))["quests"]:
                if old.get("steam_url"):
                    steam[norm_ru(old["name"])] = old["steam_url"]

    print("Скачиваю скриншоты…")
    for quest in quests:
        names = [quest["name"]] + [a for a in quest["aliases"] if re.search("[а-яё]", a, re.I)]
        quest["steam_url"] = next((steam[norm_ru(n)] for n in names if norm_ru(n) in steam), None)
        guide = guides.get(quest.pop("_wiki_key"))
        quest["guide"] = None
        if guide:
            quest["guide"] = {
                "text": [tr(p) for p in guide["text"] if re.search(r"\w", p)],
                "images": download_images(quest["id"], guide["images"], urls, tr),
            }
        quest["video_url"] = "https://www.youtube.com/results?" + urllib.parse.urlencode(
            {"search_query": f"ARC Raiders {quest['aliases'][0]} quest guide"})

    MISSING_TRANSLATIONS[:] = tr.missing
    return {
        "source": "Квесты: github.com/RaidTheory/arcraiders-data (MIT). Гайды и скриншоты: arcraiders.wiki (CC BY-SA 4.0). "
                  "Карты и места: github.com/tyler45455/Arc-Raiders-hub (данные arcraiders.wiki, CC BY-SA 4.0). "
                  "Игровые материалы © Embark Studios AB.",
        "maps": [{"id": m, "name": en, "name_ru": ru, "aliases": aliases, **maps.get(m, {})}
                 for m, (en, ru, aliases) in MAPS.items()],
        "quests": quests,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    db = build(Path(sys.argv[1]))
    # Дата сборки меняется, только если изменилось содержимое: по ней программа
    # понимает, что база на GitHub новее встроенной.
    old = json.loads(OUT_PATH.read_text(encoding="utf-8")) if OUT_PATH.exists() else {}
    old_generated = old.pop("generated_at", None)
    if old == db and old_generated:
        generated = old_generated
    else:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db = {"generated_at": generated, **db}
    OUT_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_missing_translations()
    with_guides = sum(1 for q in db["quests"] if q["guide"])
    with_steam = sum(1 for q in db["quests"] if q["steam_url"])
    print(f"Записано квестов: {len(db['quests'])}, с гайдом с вики: {with_guides}, "
          f"со ссылкой на Steam: {with_steam} → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

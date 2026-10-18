"""Загрузка страниц квестов с arcraiders.wiki и разбор раздела Guide.

Текст вики доступен по лицензии CC BY-SA 4.0.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

API = "https://arcraiders.wiki/w/api.php"
USER_AGENT = "arc-raiders-overlay/0.1 (https://github.com/r4v3r-63/arc-raiders-overlay)"


def api(**params) -> dict:
    params["format"] = "json"
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_quest_pages() -> dict[str, str]:
    """Возвращает {название страницы: викитекст} для всех страниц категории Quests."""
    titles, cont = [], {}
    while True:
        # Только статьи (namespace 0): подкатегории и шаблоны в категории — не квесты.
        members = api(action="query", list="categorymembers", cmtitle="Category:Quests", cmnamespace=0, cmlimit=500,
                      **cont)
        titles += [m["title"] for m in members["query"]["categorymembers"]]
        cont = members.get("continue", {})
        if not cont:
            break
    pages = {}
    for i in range(0, len(titles), 50):
        cont = {}
        while True:
            data = api(action="query", prop="revisions", rvprop="content", rvslots="main",
                       titles="|".join(titles[i:i + 50]), **cont)
            for page in data["query"]["pages"].values():
                if page.get("revisions"):  # без содержимого — удалённая страница или ответ не влез, придёт дальше
                    pages[page["title"]] = page["revisions"][0]["slots"]["main"]["*"]
            cont = data.get("continue", {})
            if not cont:
                break
    return pages


def item_locations(names: list[str]) -> dict[str, list[str]]:
    """{английское название предмета: типы мест с лутом из карточки предмета на вики}."""
    result = {}
    for i in range(0, len(names), 50):
        data = api(action="query", prop="revisions", rvprop="content", rvslots="main", redirects=1,
                   titles="|".join(names[i:i + 50]))
        query = data.get("query", {})
        # Вики могла поправить регистр или перенаправить: возвращаем ответ под тем названием, что спрашивали.
        renamed = {r["to"]: r["from"] for key in ("normalized", "redirects") for r in query.get(key, [])}
        for page in query.get("pages", {}).values():
            if not page.get("revisions"):
                continue
            title = page["title"]
            while title in renamed:
                title = renamed[title]
            location = parse_infobox(page["revisions"][0]["slots"]["main"]["*"], "item").get("location", "")
            types = [t.strip() for t in re.split(r"[\n,/]", location) if t.strip()]
            if types:
                result[title] = types
    return result


def image_urls(files: list[str]) -> dict[str, dict]:
    """{имя файла: {"url": прямая ссылка, "sha1": контрольная сумма текущей версии}}."""
    urls = {}
    for i in range(0, len(files), 50):
        titles = "|".join("File:" + f for f in files[i:i + 50])
        data = api(action="query", prop="imageinfo", iiprop="url|sha1", titles=titles)
        normalized = {n["to"]: n["from"] for n in data["query"].get("normalized", [])}
        for page in data["query"]["pages"].values():
            if "imageinfo" in page:
                title = normalized.get(page["title"], page["title"])
                info = page["imageinfo"][0]
                urls[title.removeprefix("File:")] = {"url": info["url"], "sha1": info.get("sha1", "")}
    return urls


def section(wikitext: str, name: str) -> str | None:
    match = re.search(r"^==\s*" + name + r"\s*==\s*$(.*?)(?=^==[^=]|\Z)", wikitext, re.S | re.M)
    return match.group(1) if match else None


def clean(text: str) -> str:
    """Убирает вики-разметку, оставляя читаемый текст."""
    text = re.sub(r"<ref[^>]*?/>|<ref.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    previous = None
    while previous != text:  # вложенные шаблоны {{a|{{b}}}} снимаются изнутри наружу
        previous, text = text, re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


IMAGE_OPTIONS = re.compile(r"^(thumb|thumbnail|frame|frameless|left|right|center|none|upright.*|\d+(x\d+)?px|alt=.*|link=.*)$")


def _caption(options: list[str]) -> str:
    """Подпись к картинке — последний параметр, который не является настройкой отображения."""
    texts = [o.strip() for o in options if o.strip() and not IMAGE_OPTIONS.match(o.strip())]
    return clean(texts[-1]) if texts else ""


def parse_guide(wikitext: str) -> dict | None:
    """{"text": [абзацы], "images": [{"file", "caption"}]} или None, если гайда нет."""
    body = None
    for name in ("Guide", "Walkthrough", "Locations?"):
        body = section(wikitext, name)
        if body is not None:
            break
    if body is None:
        return None
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    images = []
    for gallery in re.findall(r"<gallery[^>]*>(.*?)</gallery>", body, re.S):
        for line in gallery.splitlines():
            line = line.strip()
            if not line:
                continue
            file, *options = line.split("|")
            images.append({"file": file.removeprefix("File:").removeprefix("Image:").strip(), "caption": _caption(options)})
    body = re.sub(r"<gallery[^>]*>.*?</gallery>", "", body, flags=re.S)
    for match in re.finditer(r"\[\[(?:File|Image):([^|\]]+)((?:\|[^\]]*)?)\]\]", body):
        images.append({"file": match.group(1).strip(), "caption": _caption(match.group(2).split("|")[1:])})
    body = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", body)
    paragraphs = []
    for chunk in re.split(r"\n\s*\n", body):
        lines = [clean(l).lstrip("*#: ").strip() for l in chunk.splitlines()]
        lines = [l for l in lines if l and not l.startswith("{|") and not l.startswith("|")]
        if lines:
            paragraphs.append(" ".join(lines) if not chunk.lstrip().startswith(("*", "#")) else "\n".join("• " + l for l in lines))
    if not paragraphs and not images:
        return None
    return {"text": paragraphs, "images": images}


def parse_objectives(wikitext: str) -> list[str]:
    body = section(wikitext, "Objectives") or ""
    objectives = []
    for inner in re.findall(r"\{\{QuestObjective\s*\|((?:[^{}\[]|\[\[.*?\]\])*?)\}\}", body, re.S):
        params = {}
        for part in re.split(r"\|(?![^\[]*\]\])", inner):
            key, sep, value = part.partition("=")
            if sep and key.strip().isidentifier():
                params[key.strip()] = value.strip()
        label = clean(params.get("label", ""))
        if label:
            if params.get("optional") == "yes" and not label.startswith("(Optional)"):
                label = "(Optional) " + label
            objectives.append(label)
    total = len(re.findall(r"\{\{QuestObjective\b", body))
    if total > len(objectives):
        # Внутри цели вложенный шаблон или ссылка, которые регулярное выражение не разбирает.
        print(f"  внимание: разобрано целей {len(objectives)} из {total}, проверьте разбор вики-разметки")
    if not objectives:
        objectives = [clean(l.lstrip("*# ")) for l in body.splitlines() if l.strip().startswith(("*", "#"))]
    return [o for o in objectives if o]


def parse_infobox(wikitext: str, kind: str = "quest") -> dict[str, str]:
    match = re.search(r"\{\{Infobox " + kind + r"(.*?)\n\}\}", wikitext, re.S)
    fields = {}
    for line in (match.group(1) if match else "").splitlines():
        key, sep, value = line.strip().lstrip("|").partition("=")
        if sep:
            fields[key.strip()] = clean(value)
    return fields


def parse_required_items(wikitext: str) -> list[tuple[str, int]]:
    """[(английское название предмета, количество)] из раздела Required items."""
    items = []
    for name, rest in re.findall(r"\{\{Quest item\|require\|([^|}]+)((?:\|[^}]*)?)\}\}", wikitext):
        qty = re.search(r"qty=(\d+)", rest)
        items.append((name.strip(), int(qty.group(1)) if qty else 1))
    return items

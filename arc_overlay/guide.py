"""Страницы гайда: из русского руководства в Steam, с вики и из своей папки игрока.

Страница — это заголовок шага, текст и (необязательно) одна картинка.
Руководство Steam не хранится в репозитории: программа скачивает его на компьютере
игрока для личного пользования (см. arc_overlay/net.py).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from .quest_db import DATA_DIR, Quest

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
USER_GUIDES_DIR = Path(__file__).resolve().parent.parent / "мои_скриншоты"


@dataclass
class GuidePage:
    source: str  # «Steam», «вики» или «мои скриншоты»
    title: str = ""
    text: str = ""
    image: str = ""  # путь к файлу или ссылка (для Steam)


def steam_section_id(url: str | None) -> str | None:
    return url.rsplit("#", 1)[1] if url and "#" in url else None


@dataclass
class SteamQuest:
    section_id: str
    title: str
    category: str  # раздел руководства: «Любая Локация», «Космопорт»…
    steps: list[str]


def parse_steam_index(page_html: str) -> list[SteamQuest]:
    """Оглавление руководства: квесты с их шагами (заголовки шагов — официальные цели из игры)."""
    quests = []
    category = ""
    for block in re.split(r'<div class="subSection detailBox" id="', page_html)[1:]:
        section_id = block.split('"', 1)[0]
        match = re.search(r'<div class="subSectionTitle">(.*?)</div>\s*<div class="subSectionDesc">(.*?)'
                          r'(?=<div class="subSection detailBox"|\Z)', block, re.S)
        if not match:
            continue
        raw_title, desc = match.groups()
        title = _plain(raw_title).split("\n")[0].strip()
        has_images = "<img" in desc
        if "bb_h1" in raw_title or not has_images:
            category = title  # заголовок группы квестов, а не квест
            continue
        steps = [re.sub(r"^\d+\s*[.)]\s*", "", _plain(h)).strip()
                 for h in re.findall(r'<div class="bb_h3">(.*?)</div>', desc, re.S)]
        quests.append(SteamQuest(section_id, title, category, [s for s in steps if s]))
    return quests


def parse_steam_section(page_html: str, section_id: str) -> list[GuidePage]:
    """Разбивает раздел руководства на страницы: каждая картинка завершает страницу."""
    start = page_html.find(f'<div class="subSection detailBox" id="{section_id}">')
    if start < 0:
        return []
    desc = page_html.find('<div class="subSectionDesc">', start)
    end = page_html.find('<div class="subSection detailBox"', desc)
    body = page_html[desc:end if end > 0 else None]
    # Раздел «Награды» в конце для прохождения не нужен.
    body = re.split(r'<div class="bb_h[1-3]">\s*(?:<[^>]+>\s*)*Наград[аы]', body)[0]

    pages: list[GuidePage] = []
    title, lines = "", []
    tokens = re.split(r'(<div class="bb_h[1-3]">.*?</div>|<img [^>]*src="[^"]+"[^>]*>)', body, flags=re.S)
    for token in tokens:
        if token.startswith('<div class="bb_h'):
            if lines:
                pages.append(GuidePage("Steam", title, "\n".join(lines)))
                lines = []
            title = _plain(token)
        elif token.startswith("<img"):
            image = re.search(r'src="([^"]+)"', token).group(1)
            pages.append(GuidePage("Steam", title, "\n".join(lines), image))
            lines = []
        else:
            text = _plain(token)
            if text:
                lines.extend(line for line in text.splitlines() if line.strip())
    if lines:
        pages.append(GuidePage("Steam", title, "\n".join(lines)))
    return pages


def _plain(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    lines = [" ".join(line.split()) for line in fragment.splitlines()]
    return "\n".join(line for line in lines if line and line not in ("[", "]"))


def wiki_pages(quest: Quest) -> list[GuidePage]:
    if not quest.guide:
        return []
    text = "\n".join(quest.guide.get("text", []))
    images = quest.guide.get("images", [])
    if not images:
        return [GuidePage("вики", "", text)] if text else []
    pages = []
    for n, image in enumerate(images):
        caption = image.get("caption", "")
        pages.append(GuidePage("вики", "", "\n".join(filter(None, [text if n == 0 else "", caption])),
                               str(DATA_DIR / image["file"])))
    return pages


def user_folder(quest: Quest) -> Path:
    safe = re.sub(r'[<>:"/\\|?*]', "", quest.name).strip() or quest.english_name
    return USER_GUIDES_DIR / safe


def user_pages(quest: Quest) -> list[GuidePage]:
    folder = user_folder(quest)
    if not folder.is_dir():
        return []
    pages = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() == ".txt":
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                pages.append(GuidePage("мои скриншоты", path.stem, text))
        elif path.suffix.lower() in IMAGE_SUFFIXES:
            pages.append(GuidePage("мои скриншоты", path.stem, "", str(path)))
    return pages

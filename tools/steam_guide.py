"""Ссылки на разделы русского руководства по квестам в Steam.

Руководство: «[RU] Руководство по квестам Arc Raiders»
https://steamcommunity.com/sharedfiles/filedetails/?id=3672641520

Тексты и скриншоты руководства принадлежат его автору и в базу не копируются:
берём только заголовки разделов, чтобы открыть нужный раздел в браузере.
"""

from __future__ import annotations

import html
import re
import urllib.request

GUIDE_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id=3672641520"


def fetch_sections() -> dict[str, str]:
    """{заголовок раздела: ссылка на этот раздел}."""
    req = urllib.request.Request(GUIDE_URL, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ru"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    sections = {}
    for section_id, title in re.findall(
        r'<div class="subSection detailBox" id="(\d+)">\s*<div class="subSectionTitle">\s*(.*?)\s*</div>', page, re.S
    ):
        title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        if title:
            sections[title] = f"{GUIDE_URL}#{section_id}"
    return sections

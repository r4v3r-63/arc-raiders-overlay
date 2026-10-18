from arc_overlay import guide
from arc_overlay.quest_db import Quest

# Упрощённая разметка раздела руководства Steam (не настоящий текст).
STEAM_HTML = """
<div class="subSection detailBox" id="111">
  <div class="subSectionTitle">Другой квест</div>
  <div class="subSectionDesc">чужой текст</div>
</div>
<div class="subSection detailBox" id="222">
  <div class="subSectionTitle">Чистое небо</div>
  <div class="subSectionDesc">
    <div class="bb_h3"><u><b>1. Первый шаг</b></u></div><br><b>Идём к &quot;метке&quot;</b><br>
    <a href="https://img/1"><img src="https://img/1" class="sharedFilePreviewImage"></a>
    <b>Ещё картинка</b><img src="https://img/2" class="x">
    <div class="bb_h3"><b>2. Второй шаг</b></div><b>Без картинки</b>
    <div class="bb_h2">Награды</div><img src="https://img/reward">
  </div>
</div>
<div class="subSection detailBox" id="333"></div>
"""


def test_parse_steam_section():
    pages = guide.parse_steam_section(STEAM_HTML, "222")
    assert [(p.title, p.text, p.image) for p in pages] == [
        ("1. Первый шаг", 'Идём к "метке"', "https://img/1"),
        ("1. Первый шаг", "Ещё картинка", "https://img/2"),
        ("2. Второй шаг", "Без картинки", ""),
    ]
    assert all(p.source == "Steam" for p in pages)


def test_parse_missing_section():
    assert guide.parse_steam_section(STEAM_HTML, "999") == []


def test_steam_section_id():
    assert guide.steam_section_id("https://steamcommunity.com/x/?id=1#222") == "222"
    assert guide.steam_section_id(None) is None


def test_wiki_pages():
    quest = Quest(name="Тест", steps=[], guide={"text": ["Общий текст"], "images": [
        {"file": "guides/t/01.jpg", "caption": "Карта"}, {"file": "guides/t/02.jpg", "caption": "Место"}]})
    pages = guide.wiki_pages(quest)
    assert [p.text for p in pages] == ["Общий текст\nКарта", "Место"]
    assert pages[0].image.endswith("guides/t/01.jpg")


def test_user_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(guide, "USER_GUIDES_DIR", tmp_path)
    quest = Quest(name="Квест: «тест»?", steps=[])
    folder = guide.user_folder(quest)
    assert folder.name == "Квест «тест»"
    folder.mkdir()
    (folder / "1.png").write_bytes(b"")
    (folder / "заметка.txt").write_text("иди налево", encoding="utf-8")
    pages = guide.user_pages(quest)
    assert [(p.title, p.text, bool(p.image)) for p in pages] == [("1", "", True), ("заметка", "иди налево", False)]

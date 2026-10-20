"""Поиск фактов и фото: детерминированная часть (без сети)."""
from app.planning.models import ContentSlide, DeckContent, Item, SlideSpec, Source
from app.planning.variants import slide_extras
from app.research.photos import _ok_meta
from app.research.web import Fact, Research, _focus, attach_sources


def _res() -> Research:
    return Research(provider="Википедия",
                    facts=[Fact(text="В 2013 году электронной записью воспользовалось почти 5 миллионов человек. [1]", refs=[1]),
                           Fact(text="Очереди к специалистам сократились в 2,5 раза. [1]", refs=[1]),
                           Fact(text="Рынок телемедицины растёт примерно на 20 % в год. [2]", refs=[2])],
                    sources=[Source(n=1, title="ЕМИАС", url="https://ru.wikipedia.org/wiki/ЕМИАС", host="ru.wikipedia.org"),
                             Source(n=2, title="Телемедицина", url="https://ru.wikipedia.org/wiki/Телемедицина",
                                    host="ru.wikipedia.org")])


def test_research_text_lists_only_used_sources():
    t = _res().text()
    assert "Википедия" in t and "[1] ru.wikipedia.org — ЕМИАС" in t and "2,5 раза" in t


def test_attach_sources_by_distinctive_numbers():
    deck = DeckContent(title="t", slides=[
        ContentSlide(id="s1", title="Рост 20 % в год", items=[Item(head="Рынок", text="растёт быстро")]),
        ContentSlide(id="s2", title="Итоги 2013 года", items=[Item(head="3 этапа", text="план")]),   # год и счётчик — не факт
        ContentSlide(id="s3", title="Очереди короче в 2,5 раза"),
    ])
    assert attach_sources(deck, _res()) == 2
    s1, s2, s3 = deck.slides
    assert s1.source_note == "Источник: Википедия, «Телемедицина»" and "Телемедицина" in s1.notes
    assert not s2.source_note
    assert "ЕМИАС" in s3.source_note
    assert [s.n for s in deck.sources] == [1, 2]


def test_footer_carries_source_and_photo_credit():
    s = ContentSlide(id="s1", title="x", source_note="Источник: Википедия, «Телемедицина»",
                     image="p.jpg", image_credit="Фото: Иван Петров, CC BY-SA 4.0")
    ex = slide_extras(DeckContent(title="t"), SlideSpec(slide=s, recipe="image_text"))
    assert ex["footer"] == "Источник: Википедия, «Телемедицина» · Фото: Иван Петров, CC BY-SA 4.0"


def test_focus_keeps_head_and_topic_paragraphs():
    text = "\n".join(["Определение темы."] + [f"Абзац про погоду {i}." for i in range(400)] + ["Телемедицина в регионах: 20 %."])
    out = _focus(text, "телемедицина регионы", 2000)
    assert out.startswith("Определение темы.") and "Телемедицина в регионах" in out and len(out) <= 2100


def test_photo_meta_filter():
    ok = {"title": "File:Doctor at work.jpg", "mime": "image/jpeg", "width": 2000, "height": 1300, "license": "CC BY-SA 4.0"}
    assert _ok_meta(ok)
    assert not _ok_meta(dict(ok, title="File:Study.pone.0110043.g001.jpg"))        # рисунок из научной статьи
    assert not _ok_meta(dict(ok, license="CC BY-NC 2.0"))                          # некоммерческая лицензия
    assert not _ok_meta(dict(ok, width=900))                                       # мелкое
    assert not _ok_meta(dict(ok, width=1000, height=1500))                         # вертикальное
    assert not _ok_meta(dict(ok, mime="image/png"))
    assert not _ok_meta(dict(ok, title="File:Joe Biden with a student during Computer Science Education Week 2014.jpg",
                             artist="White House"))                            # узнаваемый политик

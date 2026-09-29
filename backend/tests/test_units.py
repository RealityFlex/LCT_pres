"""Модульные тесты без внешних зависимостей (LibreOffice и модели не нужны)."""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import numpy as np
import pytest
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from app.core import pptx_ops
from app.parsing.ooxml import contrast, luminance, rgb_to_hex


# ------------------------------------------------------------------ цвета

def test_contrast_wcag():
    assert contrast("000000", "FFFFFF") == pytest.approx(21.0, rel=1e-3)
    assert contrast("FFFFFF", "FFFFFF") == pytest.approx(1.0)
    # белый на насыщенном розовом не дотягивает до 4.5 — такой акцент для мелкого текста не годится
    assert contrast("FFFFFF", "DF3674") < 4.5
    assert luminance("FFFFFF") > luminance("777777") > luminance("000000")
    assert rgb_to_hex((255, 0, 128)) == "FF0080"


# ------------------------------------------------------------------ запись текста в OOXML

def _shape_with_ppr(ppr_xml: str, paras: int = 1):
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    txb = tb._element.txBody
    for p in list(txb.findall("{*}p")):
        txb.remove(p)
    for i in range(paras):
        txb.append(etree.fromstring(
            f'<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">{ppr_xml}'
            f'<a:r><a:rPr lang="ru-RU" sz="1400"/><a:t>Строка {i}</a:t></a:r></a:p>'))
    return tb._element


def test_set_text_keeps_template_paragraph_properties():
    el = _shape_with_ppr('<a:pPr algn="ctr" marL="0" indent="0"/>')
    pptx_ops.set_text(el, ["Новый текст"])
    ppr = el.find(".//{*}p/{*}pPr")
    assert ppr is not None and ppr.get("algn") == "ctr"


def test_set_text_drops_hanging_indent_without_bullet():
    el = _shape_with_ppr('<a:pPr marL="171450" indent="-171450"><a:buNone/></a:pPr>')
    pptx_ops.set_text(el, ["Длинная фраза, которая переносится на вторую строку"])
    ppr = el.find(".//{*}p/{*}pPr")
    assert ppr.get("marL") == "0" and ppr.get("indent") == "0"


def test_set_text_clamps_list_spacing_for_single_phrase():
    el = _shape_with_ppr('<a:pPr><a:lnSpc><a:spcPct val="190000"/></a:lnSpc></a:pPr>', paras=3)
    pptx_ops.set_text(el, ["Одна фраза вместо списка"])
    sp = el.find(".//{*}lnSpc/{*}spcPct")
    assert int(sp.get("val")) <= 150000


# ------------------------------------------------------------------ подбор кегля

def test_fit_size_shrinks_long_text_but_stays_in_scale():
    from app.layout import textfit as tf
    scale = [12, 14, 16, 20, 24]
    w, h = Inches(3), Inches(0.8)
    short, ok1 = tf.fit_size([("Коротко", False)], w, h, "Arial", scale, 24, 12)
    long_, ok2 = tf.fit_size([("Очень длинный текст " * 6, False)], w, h, "Arial", scale, 24, 12)
    assert ok1 and short == 24
    assert long_ < short and long_ in scale


# ------------------------------------------------------------------ структурный анализ

def test_analyzer_finds_groups_and_kinds(synthetic_pptx):
    from app.parsing.analyze import TemplateAnalyzer
    slides = TemplateAnalyzer(synthetic_pptx).run()
    kinds = [s.kind for s in slides]
    assert kinds[0] == "title" and kinds[1] == "section" and kinds[-1] == "closing"
    cards = slides[2].groups[0]
    assert cards.count == 3 and cards.arrangement == "row" and cards.container_sids
    cols = slides[3].groups[0]            # без подложек: по стилю текста
    assert cols.count == 3 and not cols.container_sids
    roles = {m["role"] for it in cols.items for m in it["members"]}
    assert {"heading", "body"} <= roles


def test_irregular_labels_are_not_a_group(tmp_path):
    """Подписи схемы, разбросанные по слайду, — не ряд карточек."""
    from tests.conftest import _text
    from app.parsing.analyze import TemplateAnalyzer
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _text(s, 0.8, 0.4, 10, 0.8, "Потоки данных", 30, bold=True)
    for x, y in ((0.5, 2.0), (5.0, 4.5), (9.5, 3.0)):
        _text(s, x, y, 2.5, 0.5, "Узел схемы", 16, bold=True)
    p = tmp_path / "diagram.pptx"
    prs.save(str(p))
    sl = TemplateAnalyzer(p).run()[0]
    assert not any(g.count == 3 for g in sl.groups)


# ------------------------------------------------------------------ растровые шаблоны

def _gradient(w=480, h=270):
    y = np.linspace(0, 1, h)[:, None, None]
    top, bottom = np.array([70, 60, 170.0]), np.array([100, 40, 170.0])
    img = np.repeat(top + (bottom - top) * y, w, axis=1)
    return img


def test_background_fit_ignores_large_white_cards():
    from app.parsing import raster
    img = _gradient()
    clean = img.copy()
    img[40:230, 60:420] = 255           # карточка на 60% слайда
    coef = raster.fit_background(img)
    fit = raster.bg_image(coef, img.shape[1], img.shape[0])
    assert np.abs(fit - clean).mean() < 6


def test_is_raster_detects_picture_slides(tmp_path):
    from app.parsing import raster
    from app.parsing.analyze import TemplateAnalyzer
    buf = io.BytesIO()
    Image.fromarray(_gradient().astype(np.uint8)).save(buf, format="PNG")
    prs = Presentation()
    for _ in range(3):
        buf.seek(0)
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_picture(buf, 0, 0, prs.slide_width, prs.slide_height)
    p = tmp_path / "raster.pptx"
    prs.save(str(p))
    an = TemplateAnalyzer(p)
    assert raster.is_raster(an, an.run())


# ------------------------------------------------------------------ промпты картинок

def test_image_prompt_sanitizer():
    from app.layout.images import GigaChatImages
    t = GigaChatImages._clean("3D-иконки (логотипы React, Redis) и «рост 45%»")
    assert "3D" not in t and "React" not in t and "45" not in t and "«" not in t
    assert "объёмные" in t


# ------------------------------------------------------------------ контекстный аудит

class _FakeRun:
    def __init__(self, answer):
        self.answer = answer

    async def call(self, name, **kw):
        return self.answer


def _layout(text):
    from app.layout.ir import SlideLayout, SlotFill
    return SlideLayout(index=1, content_id="s1", canvas="c", recipe="cards", intent="cards",
                       slots=[SlotFill(role="title", sid="1", text=text)])


def _audit(answer, text, kind="content", short=False, tmp_path=None):
    from app.audit.contextual import audit_slides
    png = tmp_path / "s.png"
    Image.new("RGB", (64, 36), "white").save(png)
    issues, _ = asyncio.run(audit_slides([_layout(text)], [png], [kind], "бриф", _FakeRun(answer), short_titles=short))
    return issues


def test_hallucinated_typos_are_dropped(tmp_path):
    ans = {"q8": {"ok": False, "comment": "опечатка"}, "typos": [{"wrong": "поведение", "right": "поведение"}]}
    assert not _audit(ans, "Неуместное поведение", tmp_path=tmp_path)
    ans = {"q8": {"ok": False}, "typos": [{"wrong": "превет", "right": "привет"}]}
    assert [i.check for i in _audit(ans, "Всем превет", tmp_path=tmp_path)] == ["typos"]


def test_short_titles_of_template_are_only_a_hint(tmp_path):
    ans = {"q1": {"ok": False, "comment": "нет вывода"}}
    assert _audit(ans, "Команда", short=True, tmp_path=tmp_path)[0].severity == "info"
    assert _audit(ans, "Команда", short=False, tmp_path=tmp_path)[0].severity == "warning"
    assert not _audit(ans, "План", kind="agenda", tmp_path=tmp_path)


# ------------------------------------------------------------------ задачи

def test_job_interrupted_by_restart_becomes_error():
    from app.pipeline import JobStore, job_dir
    from app.planning.models import Brief
    st = JobStore()
    job = st.create("tpl", Brief(topic="Тест"))
    job.status = "running"
    st.save(job)
    fresh = JobStore()                  # «новый процесс»
    j = fresh.get(job.id)
    assert j.status == "error" and "перезапущен" in (j.error or "")
    assert (job_dir(job.id) / "job.json").exists()


# ------------------------------------------------------------------ сверка чисел с брифом

def test_unsupported_numbers_are_found():
    from app.planning.facts import unsupported
    from app.planning.models import Brief, ContentSlide, DeckContent, Item
    brief = Brief(topic="Умный склад", details="Время сборки снизилось с 4,5 до 1,5 часа. План: 12 складов. Бюджет 48 млн руб.")
    c = DeckContent(title="t", slides=[
        ContentSlide(id="s1", intent="cards", title="Пилот ускорил сборку в 3 раза",
                     items=[Item(head="Шаг 1", text="Сборка за 1,5 часа"), Item(head="Бюджет", value="48 млн ₽")]),
        ContentSlide(id="s2", intent="timeline", title="План на 12 складов",
                     items=[Item(head="Группа 1", text="Внедрение на первых 4 складах"), Item(head="Q3 2026", text="Старт")]),
    ])
    bad = unsupported(c, brief)
    assert "s1" not in bad                      # числа брифа, «в 3 раза» из 4,5→1,5 и нумерация шагов — законны
    assert any("4 складах" in t for t in bad["s2"]) and any("2026" in t for t in bad["s2"])


def test_stylistic_rewrite_is_not_a_typo(tmp_path):
    ans = {"q8": {"ok": False}, "typos": [{"wrong": "как звали маму", "right": "как звали свою мать"}]}
    assert not _audit(ans, "Они помнят, как звали маму", tmp_path=tmp_path)


def test_token_template_kinds(tmp_path):
    """Шаблон с метками {{cover.title}} и одинаковым именем макета «Титульный слайд» у всех слайдов."""
    from tests.conftest import _text
    from app.parsing.analyze import TemplateAnalyzer
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    for i, tok in enumerate(["cover", "cards_3x2", "section", "row_3"]):
        s = prs.slides.add_slide(prs.slide_layouts[0])      # «Title Slide» у всех
        for ph in list(s.placeholders):
            ph._element.getparent().remove(ph._element)
        _text(s, 0.8, 0.5, 10, 1.0, "{{" + tok + ".title}}", 60 if tok == "section" else 36, bold=True)
        if tok.startswith(("cards", "row")):
            for k in range(3):
                _text(s, 0.8 + 4 * k, 2.5, 3.5, 0.5, "{{" + tok + f".item_{k}.label}}}}", 14)
    p = tmp_path / "tokens.pptx"
    prs.save(str(p))
    kinds = [s.kind for s in TemplateAnalyzer(p).run()]
    assert kinds == ["title", "content", "section", "content"]


def test_template_logos_are_not_garbage_and_empty_brief_softens_facts(tmp_path):
    from app.audit.contextual import audit_slides
    png = tmp_path / "s.png"
    Image.new("RGB", (64, 36), "white").save(png)
    run = _FakeRun({"q7": {"ok": False, "comment": "Логотипы VK Workspace в углах"},
                    "q4": {"ok": False, "comment": "Упоминание санкций не подтверждено"}})
    issues, _ = asyncio.run(audit_slides([_layout("Тема")], [png], ["content"], "бриф", run, no_data=True))
    assert [(i.check, i.severity) for i in issues] == [("facts_supported", "warning")]


# ------------------------------------------------------------------ объём колоды (ТЗ: 10–15 слайдов)

def _deck(intents):
    from app.planning.models import ContentSlide, DeckContent, Item
    slides = [ContentSlide(id=f"s{i}", intent=it, title=f"Слайд {i}",
                           items=[Item(head="a"), Item(head="b")] if it in ("bullets", "cards") else [])
              for i, it in enumerate(intents, 1)]
    return DeckContent(title="t", slides=slides)


def test_slide_count_follows_duration_and_bounds():
    from app.planning.models import Brief
    from app.planning.planner import auto_slide_count, notes_rule, target_count
    assert target_count(Brief(topic="x", slide_count=8)) == 8          # явное число пользователя главнее
    assert auto_slide_count(Brief(topic="x", duration_min=7)) == 11    # 7 мин → 10,5 → 11 слайдов
    assert auto_slide_count(Brief(topic="x", duration_min=30)) == 15   # не больше 15
    assert 11 <= auto_slide_count(Brief(topic="x")) <= 14
    assert "слов" in notes_rule(Brief(topic="x", duration_min=7), 10)


def test_trim_keeps_title_and_closing():
    from app.planning.planner import trim_deck
    d = _deck(["title"] + ["cards", "quote", "section"] * 6 + ["closing"])
    trim_deck(d, 15)
    assert len(d.slides) == 15 and d.slides[0].intent == "title" and d.slides[-1].intent == "closing"
    # сначала уходят цитаты (их 6, убрать нужно 5), разделители и содержание не тронуты
    assert sum(s.intent == "quote" for s in d.slides) == 1
    assert sum(s.intent == "section" for s in d.slides) == 6


def test_extender_fills_missing_slides():
    from app.planning.models import Brief
    from app.planning.planner import extend_deck

    class FakeRun:
        async def call(self, skill, **kw):
            assert skill == "deck_extender" and kw["missing"] == 3
            topics = ["Риски внедрения снимаются пилотом", "Обучение сотрудников занимает день",
                      "Интеграция через открытое API", "Экономия бюджета отдела", "Экономия бюджета отдела маркетинга"]
            return {"slides": [{"after": 2, "intent": "cards", "title": t,
                                "items": [{"head": "x", "text": "y"}]} for t in topics]
                    + [{"after": 3, "intent": "quote", "title": "Цитата без содержания"}]}

    d = _deck(["title", "cards", "bullets", "cards", "bullets", "cards", "closing"])
    prof = type("P", (), {"narrative": type("N", (), {"uses_kicker": False})(), "canvases": []})()
    asyncio.run(extend_deck(d, 10, Brief(topic="x"), prof, FakeRun()))
    assert len(d.slides) == 10 and d.slides[-1].intent == "closing"
    assert [s.id for s in d.slides] == [f"s{i}" for i in range(1, 11)]
    titles = [s.title for s in d.slides]
    assert "Цитата без содержания" not in titles and "Экономия бюджета отдела маркетинга" not in titles


def test_dense_merge_respects_floor():
    from app.planning.variants import _merge_for_dense
    d = _deck(["title"] + ["bullets"] * 10 + ["closing"])          # 12 слайдов, все сливаемые
    assert len(_merge_for_dense(d.slides, budget=2)) == 10
    assert len(_merge_for_dense(d.slides, budget=0)) == 12


def test_materials_extract_text_and_pptx(tmp_path):
    from app.planning.materials import combine, extract
    assert "Лекало" in extract("readme.md", "# Лекало\nСервис".encode("utf-8"))
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Выручка 48 млн"
    buf = io.BytesIO()
    prs.save(buf)
    assert "48 млн" in extract("old.pptx", buf.getvalue())
    with pytest.raises(ValueError):
        extract("photo.png", b"\x89PNG")
    both = combine([("a.md", "x" * 40_000), ("b.md", "y")])
    assert "a.md" in both and "b.md" not in both and len(both) < 31_000   # общий лимит 30 тыс. знаков


def test_empty_image_slide_becomes_quote_and_image_moves():
    from app.planning.models import ContentSlide, DeckContent, Item
    from app.planning.planner import ensure_images
    it = [Item(head="a", text="b"), Item(head="c", text="d")]
    d = DeckContent(title="t", slides=[
        ContentSlide(id="s1", intent="title", title="T"), ContentSlide(id="s2", intent="agenda", title="План", items=it),
        ContentSlide(id="s3", intent="image", title="Пустая картинка", image_prompt="векторный стиль"),
        ContentSlide(id="s4", intent="cards", title="Карточки", items=it),
        ContentSlide(id="s5", intent="bullets", title="Тезисы", items=it),
        ContentSlide(id="s6", intent="closing", title="Итог")])
    ensure_images(d, 2, "векторный стиль")
    assert d.slides[2].intent == "quote" and not d.slides[2].image_prompt
    imgs = [s for s in d.slides if s.intent == "image"]
    assert len(imgs) == 2 and all(s.items and s.image_prompt for s in imgs)

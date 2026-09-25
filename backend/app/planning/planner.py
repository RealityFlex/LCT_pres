"""Генерация структуры и текста колоды (слой «генерация», до вёрстки) + детерминированная валидация."""
from __future__ import annotations

import re
from typing import Any, Optional

from ..config import get_settings
from ..layout import icons
from ..layout.textfit import text_width
from ..llm.skills import SkillRun
from ..parsing.model import TemplateProfile
from .models import INTENTS, Brief, ChartSpec, Column, ContentSlide, DeckContent, Item, Series, TableSpec

NUM_RE = re.compile(r"[-−+]?\d+(?:[.,]\d+)?")

ARCS = {
    "фича": "проблема пользователя → как работает фича → ценность и метрики → сравнение с текущим решением → план запуска → риски → что нужно от аудитории",
    "продукт": "рынок и боль клиента → продукт → ключевые функции → преимущества и сравнение → метрики/кейсы → бизнес-модель → дорожная карта → призыв",
    "проект": "контекст → цели → подход и этапы → результаты → экономический эффект → риски → следующие шаги",
    "инициатива": "проблема → предложение → выгоды → ресурсы и бюджет → план реализации → риски → запрос на решение",
    "обучение": "цели занятия → теоретические блоки → примеры → практика → типичные ошибки → итоги",
}


def _nums(text: str) -> set[float]:
    out = set()
    for m in NUM_RE.findall(text or ""):
        try:
            out.add(abs(float(m.replace(",", ".").replace("−", "-"))))
        except ValueError:
            pass
    return out


def numbers_supported(text: str, source: set[float]) -> bool:
    vals = _nums(text)
    return all(any(abs(v - s) < 1e-6 for s in source) for v in vals)


def narrative_text(p: TemplateProfile) -> str:
    n = p.narrative
    parts = []
    if n.has_agenda:
        parts.append("после титула идёт слайд-план (agenda)")
    if n.has_sections:
        parts.append("смысловые блоки открываются слайдами-разделителями (section)")
    if n.uses_kicker:
        parts.append(f"над заголовками — кикеры в стиле «{n.kicker_example}»")
    if n.closing == "summary":
        parts.append("финальный слайд — итоги «что важно запомнить» с 3–4 выводами")
    elif n.closing == "thanks":
        parts.append("финальный слайд — благодарность и призыв к действию")
    if n.numbering:
        parts.append("шаблон любит нумерацию (01, 02, 03) и крупные цифры")
    parts.append(f"средняя длина заголовка в шаблоне — {n.avg_title_words:.0f} слов")
    if n.tone:
        parts.append(f"тон: {n.tone}")
    return "; ".join(parts) + "."


def auto_slide_count(brief: Brief) -> int:
    """Объём колоды по богатству брифа: 11 слайдов для темы без данных, до 14 — для насыщенного брифа."""
    facts = len(_nums(brief.details)) + len([ln for ln in brief.details.splitlines() if ln.strip()])
    return max(11, min(14, 11 + facts // 6))


def title_capacity(p: TemplateProfile) -> int:
    """Сколько символов заголовка помещается на типовом контентном холсте."""
    pool = [c for c in p.canvases if c.kind == "content" and c.clean]
    wide = [c for c in pool if c.title_label_sid is None and
            any(s.role == "title" and (c.title_max_w or s.box.w) >= 0.35 * p.slide_w for s in c.slots)]
    content = sorted(wide or pool, key=lambda c: -c.score)[:3]
    caps = []
    sample = "Пилот сократил время сборки заказа втрое за квартал"
    for c in content:
        t = next((s for s in c.slots if s.role == "title"), None)
        if t is None:
            continue
        w = (c.title_max_w or t.box.w) - 2 * 91440
        per_char = text_width(sample.upper() if (t.style.caps or p.typography.title_caps) else sample,
                              t.style.font, t.style.size * 0.9, t.style.bold) / len(sample)
        lines = 1 if c.title_label_sid else 2
        caps.append(int(w / max(1, per_char) * lines * 0.92))
    return max(28, min(80, int(sorted(caps)[len(caps) // 2]) if caps else 70))


def _s(x: Any, limit: int = 400) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()[:limit]


def normalize(raw: dict, brief: Brief, profile: TemplateProfile) -> DeckContent:
    source_nums = _nums(" ".join([brief.topic, brief.details, brief.audience]))
    slides_raw = raw.get("slides") or []
    slides: list[ContentSlide] = []
    for i, s in enumerate(slides_raw):
        if not isinstance(s, dict):
            continue
        intent = s.get("intent") if s.get("intent") in INTENTS else "bullets"
        items = []
        for it in (s.get("items") or [])[:6]:
            if isinstance(it, str):
                it = {"head": it}
            if not isinstance(it, dict):
                continue
            val = _s(it.get("value"), 16) or None
            if val and not numbers_supported(val, source_nums):
                val = None      # цифра не из брифа — не показываем
            items.append(Item(head=_s(it.get("head"), 60), text=_s(it.get("text"), 160), value=val,
                              icon=icons.find_icon(_s(it.get("icon"), 40)) if it.get("icon") else None))
        chart = None
        ch = s.get("chart")
        if isinstance(ch, dict) and ch.get("categories") and ch.get("series"):
            try:
                series = [Series(name=_s(se.get("name"), 40), values=[float(str(v).replace(",", ".")) for v in se.get("values", [])])
                          for se in ch["series"] if isinstance(se, dict)]
                cats = [_s(c, 24) for c in ch["categories"]][:12]
                ok = series and all(len(se.values) >= 2 for se in series)
                ok = ok and all(any(abs(abs(v) - n) < 1e-6 for n in source_nums) for se in series for v in se.values)
                if ok:
                    chart = ChartSpec(type=ch.get("type") if ch.get("type") in ("bar", "column", "line", "pie", "doughnut") else "column",
                                      categories=cats, series=series[:5], unit=_s(ch.get("unit"), 20), title=_s(ch.get("title"), 60))
            except (TypeError, ValueError):
                chart = None
        table = None
        tb = s.get("table")
        if isinstance(tb, dict) and tb.get("columns") and tb.get("rows"):
            cols = [_s(c, 30) for c in tb["columns"]][:5]
            rows = [[_s(c, 60) for c in r][: len(cols)] for r in tb["rows"] if isinstance(r, list)][:6]
            rows = [r for r in rows if numbers_supported(" ".join(r), source_nums)] or []
            if rows:
                table = TableSpec(columns=cols, rows=rows)
        columns = []
        for c in (s.get("columns") or [])[:3]:
            if isinstance(c, dict) and c.get("points"):
                columns.append(Column(title=_s(c.get("title"), 40), points=[_s(p, 90) for p in c["points"]][:6]))
        if intent == "chart" and chart is None:
            intent = "stats" if sum(1 for it in items if it.value) >= 2 else "cards"
        if intent == "stats" and sum(1 for it in items if it.value) < 3:
            intent = "cards"
        if intent == "table" and table is None:
            intent = "cards" if items else "bullets"
        if intent == "comparison" and len(columns) < 2:
            intent = "cards"
        if intent in ("bullets", "cards", "process", "timeline", "agenda") and not items:
            if columns:
                intent = "comparison"
            elif s.get("quote") or s.get("lead"):
                intent = "quote"
        slides.append(ContentSlide(
            id=f"s{len(slides) + 1}", intent=intent, title=_s(s.get("title"), 140) or "—", lead=_s(s.get("lead"), 200),
            kicker=_s(s.get("kicker"), 40) if profile.narrative.uses_kicker else "", section=_s(s.get("section"), 40),
            items=items, chart=chart, table=table, columns=columns, quote=_s(s.get("quote"), 220),
            image_prompt=_s(s.get("image_prompt"), 400), notes=_s(s.get("notes"), 600)))
    if not slides or slides[0].intent != "title":
        slides.insert(0, ContentSlide(id="s0", intent="title", title=_s(raw.get("title")) or brief.topic))
    if slides[-1].intent != "closing":
        slides.append(ContentSlide(id="sx", intent="closing", title="Спасибо за внимание!",
                                   items=[Item(head=it.head) for it in slides[-1].items[:3]]))
    for i, s in enumerate(slides, 1):
        s.id = f"s{i}"
    return DeckContent(title=_s(raw.get("title"), 90) or brief.topic, subtitle=_s(raw.get("subtitle"), 140),
                       author=brief.author, date="", language=brief.language, slides=slides,
                       facts=[_s(f, 200) for f in (raw.get("facts") or []) if f][:40])


async def plan_deck(brief: Brief, profile: TemplateProfile, run: SkillRun) -> DeckContent:
    s = get_settings()
    n = brief.slide_count
    if not n:
        n = auto_slide_count(brief)
    slide_rule = f"ровно {n} (включая титульный и финальный)"
    img_ok = s.images.get("provider") != "none" and bool(s.gigachat_key)
    mode = (brief.images or "auto").lower()
    max_images = 0 if (not img_ok or mode == "off") else int(s.images.get("max_per_deck", 3))
    image_rule = ("обязательно сделай 2–3 слайда с intent \"image\" (иллюстрация + тезисы)" if mode == "on" and max_images
                  else "используй intent \"image\" только там, где иллюстрация реально помогает (0–2 слайда)" if max_images
                  else "не используй intent \"image\"")
    image_style = profile.image_style or (
        f"современная минималистичная 3D-иллюстрация, чистый фон, фирменные цвета #{profile.palette.primary}"
        + (f" и #{profile.palette.accents[0]}" if profile.palette.accents else "") + ", мягкий свет, без текста")
    target = n or 12
    max_sections = 0 if not profile.narrative.has_sections else (3 if target >= 13 else 2 if target >= 9 else 0)
    purpose_key = next((k for k in ARCS if k in (brief.purpose or "").lower()), "проект")
    raw = await run.call(
        "deck_planner", language="русский" if brief.language == "ru" else brief.language, slide_rule=slide_rule,
        arc=ARCS[purpose_key], max_sections=max_sections,
        kicker_rule="шаблон использует кикеры — заполни у всех содержательных слайдов" if profile.narrative.uses_kicker
        else "шаблон не использует кикеры — оставь пустым",
        narrative=narrative_text(profile), title_max=title_capacity(profile), icons=icons.icon_catalog_hint(),
        max_images=max_images, image_style=image_style, image_rule=image_rule,
        topic=brief.topic, purpose=brief.purpose, audience=brief.audience or "руководители и команда",
        details=brief.details or "(дополнительных данных нет — не используй цифры)")
    if not isinstance(raw, dict):
        raise ValueError("планировщик вернул не объект")
    deck = normalize(raw, brief, profile)
    if not max_images:
        for sl in deck.slides:
            if sl.intent == "image":
                sl.intent = "bullets"
    limit_sections(deck, max_sections)
    return deck


def limit_sections(deck: DeckContent, max_sections: int) -> None:
    """Модель иногда ставит разделитель перед каждым слайдом — оставляем не больше лимита, равномерно."""
    idx = [i for i, s in enumerate(deck.slides) if s.intent == "section"]
    if len(idx) <= max_sections:
        return
    keep = set()
    if max_sections > 0:
        step = len(idx) / max_sections
        keep = {idx[int(k * step)] for k in range(max_sections)}
    deck.slides = [s for i, s in enumerate(deck.slides) if s.intent != "section" or i in keep]
    for i, s in enumerate(deck.slides, 1):
        s.id = f"s{i}"

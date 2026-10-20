"""Генерация структуры и текста колоды (слой «генерация», до вёрстки) + детерминированная валидация."""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ..config import get_settings
from ..layout import icons
from ..layout.textfit import text_width
from ..llm.skills import SkillRun
from ..parsing.model import TemplateProfile
from .models import (INTENTS, MAX_SLIDES, MIN_SLIDES, Brief, ChartSpec, CodeSpec, Column, ContentSlide, DeckContent, Item,
                     Series, TableSpec)

log = logging.getLogger("planner")
NUM_RE = re.compile(r"[-−+]?\d+(?:[.,]\d+)?")

ARCS = {
    "фича": "проблема пользователя → как работает фича → ценность и метрики → сравнение с текущим решением → план запуска → риски → что нужно от аудитории",
    "продукт": "рынок и боль клиента → продукт → ключевые функции → преимущества и сравнение → метрики/кейсы → бизнес-модель → дорожная карта → призыв",
    "проект": "контекст → цели → подход и этапы → результаты → экономический эффект → риски → следующие шаги",
    "инициатива": "проблема → предложение → выгоды → ресурсы и бюджет → план реализации → риски → запрос на решение",
    "обучение": "цели занятия → теоретические блоки → примеры → практика → типичные ошибки → итоги",
    # доклад, объяснение, мнение — без бизнес-разделов «бюджет/риски», которых в такой теме нет
    "другое": "главный вопрос или тезис → контекст → 3–4 ключевые идеи с аргументами → примеры → неочевидный вывод → итоги",
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



WORDS_PER_MIN = 130                   # темп спокойной устной речи


def auto_slide_count(brief: Brief) -> int:
    """Объём колоды: по длительности выступления (≈1,5 слайда в минуту), иначе по богатству брифа — 11–14."""
    if brief.duration_min:
        return max(MIN_SLIDES, min(MAX_SLIDES, int(brief.duration_min * 1.5 + 0.5)))   # обычное округление, как в интерфейсе
    if len(brief.source_text) > 15000:
        # длинный документ (методичка, отчёт): как Kimi — объём по размеру материала, 15–20 слайдов
        return max(15, min(20, 13 + len(brief.source_text) // 10000))
    facts = len(_nums(brief.details)) + len([ln for ln in brief.details.splitlines() if ln.strip()])
    return max(11, min(14, 11 + facts // 6))


def target_count(brief: Brief) -> int:
    """Сколько слайдов обязан держать каждый вариант: заданное пользователем число или 10–15 по ТЗ."""
    return brief.slide_count or auto_slide_count(brief)


def notes_rule(brief: Brief, n: int) -> str:
    if brief.duration_min:
        words = max(25, round(brief.duration_min * WORDS_PER_MIN / max(1, n)))
        return (f"{words} слов, не меньше {round(words * 0.85)} (≈{round(words / WORDS_PER_MIN * 60)} с речи); "
                "на титуле и финале можно вдвое короче")
    return "2–4 предложения (≈20–30 с речи)"


def talk_rule(brief: Brief) -> str:
    if brief.duration_min:
        return (f"{brief.duration_min} мин. Колода и заметки спикера вместе должны укладываться в этот тайминг, "
                "не больше одной мысли на слайд.")
    return "длительность не задана — ориентируйся на 30–40 секунд на слайд."


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
    source_nums = _nums(" ".join([brief.topic, brief.details, brief.audience, brief.source_text]))
    slides: list[ContentSlide] = []
    for s in raw.get("slides") or []:
        sl = norm_slide(s, source_nums, profile, len(slides) + 1)
        if sl is not None:
            slides.append(sl)
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


def norm_slide(s: Any, source_nums: set[float], profile: TemplateProfile, idx: int) -> Optional[ContentSlide]:
    """Один слайд из ответа модели → ContentSlide; цифры не из брифа отбрасываются."""
    if not isinstance(s, dict):
        return None
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
            # модель иногда отдаёт пункты объектами {"head", "text"} — на слайд идёт текст, а не JSON
            pts = [" — ".join(x for x in (_s(p.get("head"), 40), _s(p.get("text"), 90)) if x) if isinstance(p, dict)
                   else _s(p, 90) for p in c["points"]]
            columns.append(Column(title=_s(c.get("title"), 40), points=[p for p in pts if p][:6]))
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
    code = None
    cd = s.get("code")
    if isinstance(cd, str):
        cd = {"text": cd}
    if isinstance(cd, dict) and str(cd.get("text") or "").strip():
        # код — построчно и с отступами, без схлопывания пробелов (как у остальных полей)
        lines = [ln.rstrip()[:100] for ln in str(cd["text"]).replace("\t", "    ").splitlines()][:18]
        code = CodeSpec(lang=_s(cd.get("lang"), 20), text="\n".join(lines).strip("\n"), caption=_s(cd.get("caption"), 90))
    if intent == "code" and code is None:
        intent = "bullets" if items else "quote"
    return ContentSlide(
        id=f"s{idx}", intent=intent, title=_s(s.get("title"), 140) or "—", lead=_s(s.get("lead"), 200),
        kicker=_s(s.get("kicker"), 40) if profile.narrative.uses_kicker else "", section=_s(s.get("section"), 40),
        items=items, chart=chart, table=table, columns=columns, quote=_s(s.get("quote"), 220), code=code,
        image_prompt=_s(s.get("image_prompt"), 400), notes=_s(s.get("notes"), 1500))


async def plan_deck(brief: Brief, profile: TemplateProfile, run: SkillRun) -> DeckContent:
    s = get_settings()
    n = target_count(brief)
    slide_rule = f"ровно {n} (включая титульный и финальный)"
    gen_ok = s.images.get("provider") != "none" and bool(s.gigachat_key)
    src = (brief.image_source or "auto").lower()
    # фото Wikimedia Commons не требуют ключей; генератор — ключа GigaChat
    img_ok = (gen_ok and src != "web") or src in ("auto", "web")
    mode = (brief.images or "auto").lower()
    max_images = 0 if (not img_ok or mode == "off") else int(s.images.get("max_per_deck", 3))
    image_rule = ("обязательно сделай 2–3 слайда с intent \"image\" (иллюстрация + тезисы)" if mode == "on" and max_images
                  else "используй intent \"image\" только там, где иллюстрация реально помогает (0–2 слайда)" if max_images
                  else "не используй intent \"image\"")
    image_style = profile.image_style or (
        f"современная минималистичная 3D-иллюстрация, чистый фон, фирменные цвета #{profile.palette.primary}"
        + (f" и #{profile.palette.accents[0]}" if profile.palette.accents else "") + ", мягкий свет, без текста")
    target = n or 12
    # разделители съедают место под содержание: три — только в длинной колоде
    max_sections = 0 if not profile.narrative.has_sections else (3 if target >= 15 else 2 if target >= 9 else 0)
    purpose_key = next((k for k in ARCS if k in (brief.purpose or "").lower()), "другое")
    raw = await run.call(
        "deck_planner", language="русский" if brief.language == "ru" else brief.language, slide_rule=slide_rule,
        arc=ARCS[purpose_key], max_sections=max_sections,
        kicker_rule="шаблон использует кикеры — заполни у всех содержательных слайдов" if profile.narrative.uses_kicker
        else "шаблон не использует кикеры — оставь пустым",
        narrative=narrative_text(profile), title_max=title_capacity(profile), icons=icons.icon_catalog_hint(),
        max_images=max_images, image_style=image_style, image_rule=image_rule,
        topic=brief.topic, purpose=brief.purpose, audience=brief.audience or "руководители и команда",
        details=brief.details or "(дополнительных данных нет — не используй цифры)",
        talk_rule=talk_rule(brief), notes_rule=notes_rule(brief, n),
        duration=f"{brief.duration_min} мин" if brief.duration_min else "не задана")
    if not isinstance(raw, dict):
        raise ValueError("планировщик вернул не объект")
    deck = normalize(raw, brief, profile)
    if not max_images:
        for sl in deck.slides:
            if sl.intent == "image":
                sl.intent = "bullets"
    elif mode == "on":
        ensure_images(deck, 2, image_style)
    else:
        # «где уместно» — хотя бы одна иллюстрация на колоду: без картинок колода читается как отчёт
        ensure_images(deck, 1 if len(deck.slides) >= 9 else 0, image_style)
    limit_sections(deck, max_sections)
    if len(deck.slides) < n:
        await extend_deck(deck, n, brief, profile, run)
    trim_deck(deck, n if brief.slide_count else max(MAX_SLIDES, n))
    deck.target_slides = min(n, len(deck.slides))
    changed = diversify(deck, bool(max_images)) + ensure_code(deck, f"{brief.source_text}\n{brief.details}")
    await enrich_thin(deck, brief, profile, run, changed)
    if max_images:
        from ..layout.images import palette_words
        await illustrate(deck, brief, palette_words(profile), run)
    await fill_notes(deck, brief, run)
    return deck


THIN_INTENTS = {"cards", "bullets", "process", "timeline", "stats", "comparison", "image", "quote"}


def is_thin(s: ContentSlide) -> bool:
    """Почти пустой содержательный слайд: никакая вёрстка его не спасёт — его надо дописать."""
    if s.intent not in THIN_INTENTS:
        return False
    if s.intent == "quote":       # главная мысль одна в пустом слайде — нужны опорные тезисы рядом
        return len([it for it in s.items if it.text or it.head]) < 2
    if s.intent == "comparison":
        words = sum(len(pt.split()) for c in s.columns for pt in c.points)
        return len(s.columns) < 2 or sum(len(c.points) for c in s.columns) < 4 or words < 24
    words = sum(len(f"{it.head} {it.text}".split()) for it in s.items)
    return len(s.items) < 3 or words < max(18, 7 * len(s.items))


STRUCTURAL = {"title", "agenda", "section", "closing"}
YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
CONTRAST = re.compile(r"\b(против|vs|или|отлич|разниц|противополож|сравнен|до и после|раньше|теперь)", re.I)

# как переписать слайд в другой тип: что именно должно получиться (сценарист видит и старое содержание)
REWRITE = {
    "timeline": "перепиши как таймлайн (intent timeline): 3–5 вех по порядку, value — год или период, head — событие, "
                "text — что изменилось",
    "comparison": "перепиши как сравнение двух сторон (intent comparison): columns — две колонки с короткими "
                  "заголовками и 3 пунктами каждая",
    "quote": "перепиши как слайд главной мысли (intent quote): quote — одна сильная фраза до 18 слов, items — 2–3 "
             "опорных тезиса (head 1–3 слова + text 6–12 слов)",
    "process": "перепиши как процесс (intent process): 3–4 шага по порядку, value «Шаг 1»…, head — действие, "
               "text — что происходит",
    "bullets": "перепиши как список (intent bullets): 3–5 пунктов, head — суть, text — пояснение",
    "image": "перепиши как слайд с иллюстрацией (intent image): 3 тезиса (head + text) рядом с картинкой; "
             "image_prompt — буквальная сцена по смыслу слайда",
}


def _pick_intent(s: ContentSlide, avoid: set[str], allow_image: bool, used: dict[str, int]) -> str:
    """Тип по содержанию: даты → таймлайн, противопоставление → сравнение, иначе — реже всего встречавшийся."""
    txt = " ".join([s.title, s.lead] + [f"{it.value or ''} {it.head} {it.text}" for it in s.items])
    if len(set(YEAR.findall(txt))) >= 3 and "timeline" not in avoid:
        return "timeline"
    if (CONTRAST.search(txt) or len(s.items) == 2) and "comparison" not in avoid:
        return "comparison"
    pool = ["quote", "bullets", "comparison", "process"] + (["image"] if allow_image else [])
    pool = [p for p in pool if p not in avoid] or ["bullets"]
    return min(pool, key=lambda p: (used.get(p, 0), pool.index(p)))


def diversify(deck: DeckContent, allow_image: bool = False) -> list[ContentSlide]:
    """Одинаковые слайды подряд и колода из одних карточек читаются как шаблон: карточек — не больше трети
    содержательных слайдов, один тип два раза подряд — нельзя. Лишние слайды получают другой тип по смыслу
    и указание сценаристу переписать их (содержание сохраняется). Возвращает изменённые слайды."""
    body = [s for s in deck.slides if s.intent not in STRUCTURAL]
    if len(body) < 4:
        return []
    used: dict[str, int] = {}
    for s in body:
        used[s.intent] = used.get(s.intent, 0) + 1
    cap = max(2, -(-len(body) // 3))
    changed: list[ContentSlide] = []
    slides = deck.slides
    for i, s in enumerate(slides):
        if s.intent in STRUCTURAL or s.chart or s.table:
            continue
        if s.intent == "code":
            continue
        prev = slides[i - 1].intent if i else ""
        nxt = slides[i + 1].intent if i + 1 < len(slides) else ""
        # процесс за процессом и таймлайн за таймлайном — части одной методики, их не трогаем;
        # одинаковыми подряд нельзя только «плоские» слайды
        repeat = s.intent == prev and s.intent in ("cards", "bullets", "quote", "image", "stats")
        excess = s.intent in ("cards", "bullets") and used.get(s.intent, 0) > cap
        if not (repeat or excess):
            continue
        new = _pick_intent(s, {s.intent, prev, nxt}, allow_image and used.get("image", 0) < 2, used)
        if new == s.intent:
            continue
        old = "; ".join(f"{it.head}: {it.text}" if it.text else it.head for it in s.items) or s.lead or s.quote
        used[s.intent] -= 1
        used[new] = used.get(new, 0) + 1
        s.intent = new
        s.instruction = f"{REWRITE[new]}. Сохрани смысл и факты прежнего содержания: {old[:600]}. Ничего не выдумывай"
        if new == "image" and not s.image_prompt:
            s.image_prompt = _scene(s)
        changed.append(s)
    return changed


def ensure_code(deck: DeckContent, material: str, max_slides: int = 2) -> list[ContentSlide]:
    """В материалах есть код, а в колоде нет ни одного слайда с ним — добавить 1–2 слайда с листингами дословно
    (рядом со слайдом, который ближе всего по смыслу); тексты-пояснения допишет сценарист."""
    have = [s for s in deck.slides if s.intent == "code" and s.code]
    if len(have) >= max_slides:
        return []
    from .code import find_snippets, group_snippets
    groups = group_snippets(find_snippets(material, 10), max_slides=max_slides)
    shown = " ".join(re.sub(r"\s+", "", s.code.text) for s in have)
    # фрагмент, который сценарист уже поставил на слайд, второй раз не нужен
    groups = [g for g in groups if not any(re.sub(r"\s+", "", ln) in shown for ln in g.lines
                                           if ln.strip() and not ln.lstrip().startswith(("#", "//", "def ")))]
    groups = groups[:max_slides - len(have)]
    if not groups:
        return []
    added = []
    for g in groups:
        ctx = material[max(0, g.pos - 1500):g.pos + 600].lower()
        words = {w[:6] for w in re.findall(r"[а-яёa-z]{5,}", ctx)}
        best, score = None, -1
        for k, s in enumerate(deck.slides):
            if s.intent in ("title", "agenda"):
                continue
            if s.intent == "closing":
                break
            txt = " ".join([s.title] + [f"{it.head} {it.text}" for it in s.items]).lower()
            sc = sum(1 for w in set(w[:6] for w in re.findall(r"[а-яёa-z]{5,}", txt)) if w in words)
            if sc > score:
                best, score = k, sc
        pos = (best if best is not None else len(deck.slides) - 2) + 1
        if added:                               # фрагменты идут в порядке материала: следующий — не раньше предыдущего
            pos = max(pos, deck.slides.index(added[-1]) + 1)
        what = g.caption or g.lead or "пример кода из материалов"
        s = ContentSlide(id="new", intent="code", title=what[:80],
                         code=CodeSpec(lang=g.lang, text=g.text, caption=g.caption))
        s.instruction = (f"слайд с примером кода ({what}). Код уже стоит на слайде — НЕ переписывай и не возвращай code. "
                         "Дай заголовок-вывод (что показывает пример, до 8 слов) и 2–3 items: head — что в коде, "
                         "text — зачем это и что получится (6–12 слов), по материалам. Код:\n" + g.text[:900])
        deck.slides.insert(pos, s)
        added.append(s)
    for i, s in enumerate(deck.slides, 1):        # позиционные id, как после normalize
        s.id = f"s{i}"
    return added


async def enrich_thin(deck: DeckContent, brief: Brief, profile: TemplateProfile, run: SkillRun,
                      extra: Optional[list[ContentSlide]] = None) -> list[str]:
    """Слайды с одним-двумя тезисами или почти без текста дописываются по брифу и материалам (без выдумок).
    extra — слайды, уже помеченные к переписыванию (например, сменившие тип в diversify): один вызов на всё."""
    todo = list(extra or [])
    for s in deck.slides:
        if s in todo or not is_thin(s):
            continue
        s.instruction = ("слайд почти пустой: дай 3–4 тезиса (head 1–4 слова + text 8–14 слов) с конкретикой "
                         "из брифа и материалов, сохрани уже написанное, ничего не выдумывай")
        if s.intent == "quote":
            s.instruction = ("сохрани главную мысль (quote) дословно и добавь 2–3 опорных тезиса в items (head 1–3 слова + "
                             "text 6–12 слов), которые её подтверждают по брифу и материалам; ничего не выдумывай")
        s.notes = s.notes or ""
        todo.append(s)
    if not todo:
        return []
    from .outline import write_slides
    try:
        await write_slides(deck, todo, brief, profile, run)
    except Exception as e:
        log.warning("enrich_thin failed: %s", e)
    return [s.id for s in todo]


async def illustrate(deck: DeckContent, brief: Brief, style: str, run: SkillRun) -> None:
    """Буквальные сцены по теме колоды и тезисам слайда вместо абстрактных метафор сценариста."""
    need = [s for s in deck.slides if s.intent == "image"]
    if not need:
        return
    lines = "\n".join(f"{s.id}: {s.title}. " + "; ".join(f"{it.head} — {it.text}" if it.text else it.head
                                                        for it in s.items[:4]) for s in need)
    try:
        raw = await run.call("illustrator", topic=brief.topic, audience=brief.audience or "руководители и команда",
                             style=style, slides=lines)
    except Exception as e:      # остаются промпты сценариста
        log.warning("illustrator failed: %s", e)
        return
    got = raw.get("prompts") if isinstance(raw, dict) else None
    qs = raw.get("queries") if isinstance(raw, dict) else None
    for s in need:
        p = _s((got or {}).get(s.id), 400)
        if len(p.split()) >= 5:
            s.image_prompt = p
        q = _s((qs or {}).get(s.id), 60)
        if q:
            s.image_query = q


def _scene(s: ContentSlide) -> str:
    """Промпт иллюстрации из смысла слайда, если модель его не написала."""
    # без перечня подписей: Kandinsky рисует перечисленные слова буквами
    return _s(f"Метафорическая иллюстрация к мысли: {s.title.lower()}. Только предметы и люди крупным планом, "
              "никаких надписей, подписей, табличек, схем и экранов с текстом", 400)


def ensure_images(deck: DeckContent, minimum: int, style: str = "") -> None:
    """У слайдов-иллюстраций всегда есть промпт и тезисы; в режиме «обязательно» таких слайдов не меньше minimum."""
    for s in deck.slides:
        if s.intent != "image":
            continue
        if not s.items and not s.lead:
            # картинка рядом с пустой колонкой — не слайд; заголовок остаётся ключевой мыслью
            s.intent, s.quote, s.image_prompt = "quote", s.quote or s.title, ""
            continue
        # модель иногда подставляет вместо сцены сам стиль шаблона
        if not s.image_prompt or (style and s.image_prompt.strip()[:40].lower() == style.strip()[:40].lower()):
            s.image_prompt = _scene(s)
    have = sum(1 for s in deck.slides if s.intent == "image")
    body = deck.slides[2:-1]           # не титул, не план и не финал
    cands = [s for s in body if s.intent in ("cards", "bullets") and 2 <= len(s.items) <= 4
             and not s.chart and not s.table]
    step = max(1, len(cands) // max(1, minimum - have)) if minimum > have else 1
    for s in cands[::step][:max(0, minimum - have)]:
        s.intent = "image"
        s.image_prompt = _scene(s)


def notes_words(brief: Brief, n: int) -> int:
    return round(brief.duration_min * WORDS_PER_MIN / max(1, n)) if brief.duration_min else 45


def _slide_digest(s: ContentSlide) -> str:
    parts = [s.title, s.lead, s.quote] + [f"{it.value or ''} {it.head}: {it.text}".strip() for it in s.items]
    parts += [f"{c.title}: {'; '.join(c.points)}" for c in s.columns]
    return " / ".join(p for p in parts if p)[:400]


async def fill_notes(deck: DeckContent, brief: Brief, run: SkillRun) -> None:
    """Текст спикера нужен к каждому слайду: пустые и слишком короткие заметки дописывает отдельный вызов."""
    n = len(deck.slides)
    # титул и финал короче по правилу, остальным нужно ≥75% нормы, иначе выступление не займёт заданное время
    need = [s for s in deck.slides
            if len(s.notes.split()) < notes_words(brief, n) * (0.35 if s.intent in ("title", "closing") else 0.75)]
    if not need:
        return
    outline = "\n".join(f"{s.id} [{s.intent}] {_slide_digest(s)}" for s in deck.slides)
    try:
        raw = await run.call(
            "speaker_notes", notes_rule=notes_rule(brief, n), topic=brief.topic,
            audience=brief.audience or "руководители и команда",
            duration=f"{brief.duration_min} мин" if brief.duration_min else "не задана",
            outline=outline, need=", ".join(s.id for s in need))
    except Exception as e:      # без заметок колода всё равно собирается
        log.warning("speaker_notes failed: %s", e)
        return
    got = raw.get("notes") if isinstance(raw, dict) else None
    if not isinstance(got, dict):
        return
    for s in need:
        text = _s(got.get(s.id), 1500)
        if len(text.split()) > len(s.notes.split()):
            s.notes = text


async def extend_deck(deck: DeckContent, n: int, brief: Brief, profile: TemplateProfile, run: SkillRun) -> None:
    """Сценарист вернул меньше слайдов, чем нужно: недостающие просим отдельным коротким вызовом."""
    missing = n - len(deck.slides)
    outline = "\n".join(f"{i}. [{s.intent}] {s.title}" for i, s in enumerate(deck.slides, 1))
    try:
        raw = await run.call(
            "deck_extender", missing=missing, count=len(deck.slides), target=n, outline=outline,
            title_max=title_capacity(profile), icons=icons.icon_catalog_hint(), notes_rule=notes_rule(brief, n),
            topic=brief.topic, audience=brief.audience or "руководители и команда",
            details=brief.details or "(дополнительных данных нет — не используй цифры)")
    except Exception as e:      # колода без добора лучше, чем упавшая задача
        log.warning("deck_extender failed: %s", e)
        return
    source_nums = _nums(" ".join([brief.topic, brief.details, brief.audience, brief.source_text]))
    new = []
    for s in (raw.get("slides") if isinstance(raw, dict) else None) or []:
        sl = norm_slide(s, source_nums, profile, 0)
        if sl is None or sl.intent in ("title", "closing", "section", "agenda", "quote"):
            continue
        if not sl.items and not sl.columns:
            continue        # слайд из одного заголовка — не добор, а пустота
        if any(_same_topic(sl.title, x.title) for x in deck.slides + [t[1] for t in new]):
            continue
        try:
            after = int(s.get("after"))
        except (TypeError, ValueError):
            after = len(deck.slides) - 1
        new.append((max(1, min(after, len(deck.slides) - 1)), sl))
    # вставляем с конца, чтобы номера «after» ещё указывали на исходные слайды
    for after, sl in sorted(new[:missing], key=lambda t: -t[0]):
        deck.slides.insert(after, sl)
    for i, s in enumerate(deck.slides, 1):
        s.id = f"s{i}"


def _same_topic(a: str, b: str) -> bool:
    """Заголовки об одном и том же: больше половины значимых слов (по основе) совпадает."""
    def stems(t: str) -> set[str]:
        return {w[:5] for w in re.findall(r"[а-яёa-z0-9]+", t.lower()) if len(w) > 3}
    sa, sb = stems(a), stems(b)
    return bool(sa and sb) and len(sa & sb) / min(len(sa), len(sb)) > 0.5


def trim_deck(deck: DeckContent, limit: int) -> None:
    """Сверх лимита убираем цитаты, затем разделители, затем содержательные слайды с конца; финал остаётся."""
    for kind in ("quote", "section", None):
        while len(deck.slides) > limit:
            idx = [i for i, s in enumerate(deck.slides[1:-1], 1) if kind is None or s.intent == kind]
            if not idx:
                break
            deck.slides.pop(idx[-1])
    for i, s in enumerate(deck.slides, 1):
        s.id = f"s{i}"


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

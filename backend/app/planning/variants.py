"""Три варианта вёрстки поверх одной контент-модели (детерминированно).

Ось различий — «плотность × способ визуализации»:
  A faithful — ближе всего к шаблону: его паттерны, сбалансированная плотность;
  B visual   — визуальные рецепты: крупные цифры, диаграммы, иконки, картинки, чередование тёмных/светлых холстов;
  C dense    — меньше слайдов: таблицы, сравнения, слияние коротких слайдов, без разделителей.
"""
from __future__ import annotations

import re
from typing import Optional

from ..parsing.model import Canvas, TemplateProfile
from .models import MIN_SLIDES, Column, ContentSlide, DeckContent, Item, SlideSpec, TableSpec, VariantPlan

RECIPES = {
    #  intent       faithful        visual          dense
    "bullets":    ("bullets",      "cards",        "rows"),
    "cards":      ("cards",        "cards",        "rows"),
    "process":    ("process",      "process",      "rows"),
    "timeline":   ("timeline",     "timeline",     "table"),
    "stats":      ("stats",        "stats",        "stats"),
    "chart":      ("chart",        "chart",        "chart"),
    "table":      ("table",        "cards",        "table"),
    "comparison": ("comparison",   "comparison",   "table"),
    "quote":      ("quote",        "quote",        "quote"),
    "image":      ("image_text",   "image_text",   "bullets"),
    "agenda":     ("agenda",       "agenda",       "agenda"),
}
IDX = {"faithful": 0, "visual": 1, "dense": 2}


class CanvasPicker:
    def __init__(self, profile: TemplateProfile):
        self.p = profile
        cs = profile.canvases
        self.content = sorted([c for c in cs if c.kind in ("content", "agenda") and c.clean], key=lambda c: -c.score)
        if not self.content:
            self.content = sorted([c for c in cs if c.kind in ("content", "agenda")], key=lambda c: -c.score)
        if not self.content:
            self.content = sorted(cs, key=lambda c: -c.score)   # есть хотя бы титул/раздел — верстаем на нём
        if not self.content:
            raise ValueError("В шаблоне не найдено ни одного слайда, пригодного как холст: "
                             "загрузите шаблон с заголовками и фоном (слайды не должны быть пустыми)")
        W = profile.slide_w
        wide = [c for c in self.content if c.content_box.w >= 0.75 * profile.margins.w and c.content_box.h >= 0.45 * profile.margins.h]
        self.wide = wide or self.content
        self.light = [c for c in self.wide if not c.dark] or self.wide
        self.dark = [c for c in self.wide if c.dark]
        self.title = self._best("title")
        self.section = self._best("section")
        self.closing = self._best("closing")
        self._rot = 0
        del W

    def _best(self, kind: str) -> Optional[Canvas]:
        cands = [c for c in self.p.canvases if c.kind == kind]
        if not cands:
            return None
        # титул — обложка шаблона: первый по порядку слайд этого вида (дизайнеры ставят обложку первой);
        # для остальных видов — холсты с подзаголовком/телом, в них больше слотов для текста
        if kind == "title":
            return min(cands, key=lambda c: c.source_slide)
        if kind == "section":
            # разделитель — слайд с самым крупным заголовком (а не «раздел» с диаграммой или карточкой)
            def tsize(c):
                return max((sl.style.size for sl in c.slots if sl.role == "title"), default=0)
            return max(cands, key=lambda c: (tsize(c), -c.source_slide))
        return sorted(cands, key=lambda c: (-len([s for s in c.slots if s.role in ("subtitle", "body")]), -c.score))[0]

    def alternatives(self, c: Canvas) -> list[str]:
        same = [x for x in self.wide if x.id != c.id and x.dark == c.dark]
        other = [x for x in self.wide if x.id != c.id and x.dark != c.dark]
        key = lambda x: (x.title_label_sid is not None, -x.score)
        return [x.id for x in sorted(same, key=key) + sorted(other, key=key)][:4]

    def content_canvas(self, tone: str, strategy: str, i: int) -> Canvas:
        if tone == "dark" and self.dark:
            return self.dark[i % len(self.dark)] if strategy == "visual" else self.dark[0]
        pool = self.light
        if strategy == "faithful" and len(pool) > 1:
            # основной холст + изредка второй по популярности (как в самом шаблоне)
            return pool[0] if i % 4 != 3 else pool[1]
        return pool[0]


RECIPE_INTENT = {"cards": "cards", "stats": "stats", "rows": "bullets", "table": "table", "process": "process",
                 "timeline": "timeline", "chart": "chart", "comparison": "comparison", "image_text": "image",
                 "bullets": "bullets", "agenda": "agenda"}


class PatternPicker:
    """Выбор слайда-паттерна шаблона: разнообразие (штраф за повтор) + предпочтения стратегии."""

    def __init__(self, profile: TemplateProfile):
        from collections import Counter
        self.pats = list(profile.patterns)
        self.used: Counter = Counter()
        self.last: Optional[str] = None

    def pick(self, s: ContentSlide, intent: str, strategy: str) -> Optional[Canvas]:
        from ..layout.patterns import eligible
        best = None
        for p in self.pats:
            sc = eligible(p, s, intent)
            if sc is None:
                continue
            kind = p.pattern.kind
            sc -= 1.2 * self.used[p.id]
            if p.id == self.last:
                sc -= 3
            if strategy == "visual":
                sc += 1.2 if (kind in ("stats", "image", "chart") or p.pattern.image_sids) else -0.8
            elif strategy == "dense":
                sc += 1.2 if kind in ("table", "rows") else -0.8
            if best is None or sc > best[0]:
                best = (sc, p)
        if best is None:
            return None
        sc, p = best
        threshold = {"faithful": -1.5, "visual": 0.8, "dense": 0.8}.get(strategy, 0)
        if sc < threshold:
            return None
        self.used[p.id] += 1
        self.last = p.id
        return p


def _short(text: str, words: int) -> str:
    w = text.split()
    return text if len(w) <= words else " ".join(w[:words]).rstrip(",;:—-") + "…"


def build_variant(content: DeckContent, profile: TemplateProfile, vid: str, name: str, strategy: str,
                  description: str = "") -> VariantPlan:
    pick = CanvasPicker(profile)
    pats = PatternPicker(profile)
    k = IDX.get(strategy, 0)
    plan = VariantPlan(id=vid, name=name, strategy=strategy, description=description)
    slides = list(content.slides)
    # объём по ТЗ держат все варианты: компактный уплотняет только то, что сверх целевого числа слайдов
    floor = content.target_slides or MIN_SLIDES
    spare = 0      # сколько служебных слайдов (разделители, план) компактный вариант ещё может убрать
    if strategy == "dense":
        slides = _merge_for_dense(slides, budget=max(0, len(slides) - floor))
        spare = max(0, len(slides) - floor)
    sec_no = 0
    content_i = 0
    for s in slides:
        intent = s.intent if s.intent in RECIPES or s.intent in ("title", "section", "closing") else "bullets"
        if intent == "title":
            c = pick.title or pick.content_canvas("dark", strategy, 0)
            plan.slides.append(SlideSpec(slide=s, recipe="title" if pick.title else "section_synth", canvas=c.id))
            continue
        if intent == "section":
            sec_no += 1
            if strategy == "dense" and spare > 0:
                spare -= 1
                continue
            if pick.section:
                plan.slides.append(SlideSpec(slide=s, recipe="section", canvas=pick.section.id,
                                             opts={"number": f"{sec_no:02d}"}))
            else:
                c = pick.content_canvas("dark", strategy, sec_no) if pick.dark else (pick.title or pick.content_canvas("light", strategy, 0))
                plan.slides.append(SlideSpec(slide=s, recipe="section" if c.kind == "title" else "section_synth", canvas=c.id,
                                             opts={"number": f"{sec_no:02d}"}))
            continue
        if intent == "closing":
            c = pick.closing or pick.title
            has_body = c is not None and any(sl.role == "body" for sl in c.slots)
            if c is not None and (has_body or len(s.items) < 2):
                plan.slides.append(SlideSpec(slide=s, recipe="closing", canvas=c.id))
            elif s.items:
                cc = pick.content_canvas("dark" if pick.dark else "light", strategy, 0)
                s2 = s.model_copy(update={"items": [it.model_copy(update={"value": it.value or f"{k + 1:02d}"})
                                                    for k, it in enumerate(s.items[:4])]})
                plan.slides.append(SlideSpec(slide=s2, recipe="cards", canvas=cc.id,
                                             opts={"numbers": True, "icons": False}, alts=pick.alternatives(cc)))
            else:
                plan.slides.append(SlideSpec(slide=s, recipe="cards" if s.items else "quote",
                                             canvas=pick.content_canvas("dark" if pick.dark else "light", strategy, 0).id))
            continue
        if intent == "agenda" and strategy == "dense" and spare > 0:
            spare -= 1
            continue
        recipe = RECIPES[intent][k]
        opts: dict = {}
        tone = "light"
        s2 = s
        if strategy == "visual":
            if intent in ("quote", "stats") and pick.dark:
                tone = "dark"
            if recipe == "cards":
                opts["icons"] = True
                if len(s.items) in (3, 4):
                    opts["accent_index"] = 0
            if recipe == "stats":
                opts["cards"] = True
            if intent == "table" and s.table:
                s2 = _table_to_stats(s)
                recipe = "stats" if s2.items else "table"
                if not s2.items:
                    s2 = s
                else:
                    opts["cards"] = True
            if intent == "agenda":
                recipe = "cards"
                s2 = s.model_copy(update={"items": [it.model_copy(update={"value": f"{i + 1:02d}"}) for i, it in enumerate(s.items)]})
                opts["numbers"] = True
                opts["icons"] = False
        elif strategy == "dense":
            if recipe == "table" and intent == "timeline":
                s2 = s.model_copy(update={"table": TableSpec(columns=["Этап", "Что происходит", "Результат"],
                                                             rows=[[it.value or f"{i + 1}", it.head, it.text] for i, it in enumerate(s.items)])})
            if recipe == "table" and intent == "comparison" and s.columns:
                s2 = _comparison_to_table(s)
            if intent == "stats" and sum(1 for it in s.items if it.value) >= 3:
                # компактный вариант показывает цифры таблицей: показатель · значение · пояснение
                recipe = "table"
                s2 = s.model_copy(update={"table": TableSpec(
                    columns=["Показатель", "Значение", "Что это значит"],
                    rows=[[it.head, it.value or "—", it.text] for it in s.items[:6]])})
            if recipe == "rows" and len(s.items) > 6:
                recipe = "table"
                s2 = s.model_copy(update={"table": TableSpec(columns=["Пункт", "Описание"], rows=[[it.head, it.text] for it in s.items])})
        else:  # faithful
            if recipe == "cards":
                opts["icons"] = bool(profile.card_styles) and any(it.icon for it in s.items)
            if intent == "bullets" and len(s.items) >= 5:
                recipe = "rows"
        c = pick.content_canvas(tone, strategy, content_i)
        content_i += 1
        chosen = pats.pick(s2, RECIPE_INTENT.get(recipe, intent), strategy)
        if chosen is not None:
            plan.slides.append(SlideSpec(slide=s2, recipe="pattern", canvas=chosen.id, tone=tone,
                                         opts={**opts, "fallback": recipe}, alts=[c.id] + pick.alternatives(c)))
            continue
        plan.slides.append(SlideSpec(slide=s2, recipe=recipe, canvas=c.id, tone=tone, opts=opts, alts=pick.alternatives(c)))
    return plan


def _table_to_stats(s: ContentSlide) -> ContentSlide:
    """Таблица с короткими значениями в последней колонке → 2–4 крупные цифры."""
    t = s.table
    if not t or len(t.columns) < 2 or not t.rows:
        return s.model_copy(update={"items": []})
    last = [r[-1] for r in t.rows if r]
    if not all(v and len(v) <= 10 and any(ch.isdigit() for ch in v) for v in last):
        return s.model_copy(update={"items": []})
    items = []
    for r in t.rows[:4]:
        mid = ", ".join(f"{c.lower()} {v}" for c, v in zip(t.columns[1:-1], r[1:-1]) if v)
        items.append(Item(value=r[-1], head=r[0], text=mid))
    return s.model_copy(update={"items": items, "table": None})


def _table_to_cards(s: ContentSlide) -> ContentSlide:
    t = s.table
    items = []
    for r in t.rows[:6]:
        head = r[0] if r else ""
        rest = "; ".join(f"{c}: {v}" for c, v in zip(t.columns[1:], r[1:]) if v)
        items.append(Item(head=head, text=rest))
    return s.model_copy(update={"items": items, "table": None})


def _comparison_to_table(s: ContentSlide) -> ContentSlide:
    cols = s.columns[:3]
    n = max(len(c.points) for c in cols)
    rows = []
    for i in range(min(n, 6)):
        rows.append([c.points[i] if i < len(c.points) else "" for c in cols])
    return s.model_copy(update={"table": TableSpec(columns=[c.title for c in cols], rows=rows)})


def _merge_for_dense(slides: list[ContentSlide], budget: int = 99) -> list[ContentSlide]:
    """Сливает короткие соседние слайды: цитата → лид следующего, два коротких списка → сравнение.
    budget — сколько слайдов можно убрать, не опустившись ниже целевого объёма колоды."""
    out: list[ContentSlide] = []
    i = 0
    while i < len(slides):
        s = slides[i]
        nxt = slides[i + 1] if i + 1 < len(slides) else None
        if budget <= 0:
            out.append(s)
            i += 1
            continue
        if s.intent == "quote" and nxt is not None and nxt.intent not in ("section", "closing", "title") and not nxt.lead:
            out.append(nxt.model_copy(update={"lead": _short(s.quote or s.title, 24)}))
            i += 2
            budget -= 1
            continue
        small = lambda x: x.intent in ("bullets", "cards") and 2 <= len(x.items) <= 3 and not x.chart and not x.table
        if nxt is not None and small(s) and small(nxt):
            merged = s.model_copy(update={
                "intent": "comparison",
                "columns": [Column(title=_short(s.title, 6), points=[it.head + (": " + it.text if it.text else "") for it in s.items]),
                            Column(title=_short(nxt.title, 6), points=[it.head + (": " + it.text if it.text else "") for it in nxt.items])],
                "notes": (s.notes + "\n" + nxt.notes).strip()})
            out.append(merged)
            i += 2
            budget -= 1
            continue
        out.append(s)
        i += 1
    return out


def slide_extras(content: DeckContent, spec: SlideSpec) -> dict:
    ex = {"subtitle": content.subtitle if spec.slide.intent == "title" else spec.slide.lead,
          "meta": " · ".join(x for x in (content.author, content.date) if x) if spec.slide.intent in ("title", "closing") else ""}
    if spec.opts.get("number"):
        ex["number"] = spec.opts["number"]
    return ex


def clean_title(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()

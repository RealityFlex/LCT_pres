"""Применение выбранных пользователем исправлений.

Детерминированные правки меняют IR (SlideLayout) или план (SlideSpec) без модели;
контекстные — через скиллы text_condenser / fixer. После правок затронутые слайды
пересобираются композером, колода собирается заново и повторно проходит аудит.
"""
from __future__ import annotations

import logging
from typing import Optional

from ..layout.ir import SlideLayout
from ..layout.recipes import Composer
from ..layout.style import readable
from ..llm.skills import SkillRun
from ..parsing.model import TemplateProfile
from ..parsing.ooxml import color_distance
from ..planning.models import Column, ContentSlide, DeckContent, Item, SlideSpec, VariantPlan
from ..planning.planner import title_capacity
from ..planning.variants import slide_extras
from .model import Issue

log = logging.getLogger("fixes")


def _find_el(lay: SlideLayout, eid: Optional[str]):
    if not eid:
        return None
    return next((e for e in lay.elements if e.id == eid), None)


def _slide_json(s: ContentSlide) -> dict:
    return {"title": s.title, "lead": s.lead, "quote": s.quote,
            "items": [{"head": i.head, "text": i.text, "value": i.value} for i in s.items],
            "columns": [{"title": c.title, "points": c.points} for c in s.columns]}


def _apply_json(s: ContentSlide, d: dict) -> None:
    if not isinstance(d, dict):
        return
    if d.get("title"):
        s.title = str(d["title"])[:140]
    if "lead" in d:
        s.lead = str(d.get("lead") or "")[:220]
    if "quote" in d and s.quote:
        s.quote = str(d.get("quote") or s.quote)[:240]
    items = d.get("items")
    if isinstance(items, list) and s.items:
        new = []
        for k, it in enumerate(items[: max(len(s.items), 1) + 1]):
            if not isinstance(it, dict):
                continue
            old = s.items[k] if k < len(s.items) else Item()
            new.append(Item(head=str(it.get("head") or "")[:60], text=str(it.get("text") or "")[:160],
                            value=(str(it["value"])[:16] if it.get("value") else None), icon=old.icon))
        if new:
            s.items = new
    cols = d.get("columns")
    if isinstance(cols, list) and s.columns:
        s.columns = [Column(title=str(c.get("title") or ""), points=[str(p) for p in c.get("points") or []][:6])
                     for c in cols if isinstance(c, dict)] or s.columns


async def apply_fixes(profile: TemplateProfile, content: DeckContent, plan: VariantPlan, layouts: list[SlideLayout],
                      issues: list[Issue], source: str, run: SkillRun) -> tuple[list[SlideLayout], set[int], list[str]]:
    """Возвращает (новые layouts, номера изменённых слайдов, журнал)."""
    log_lines: list[str] = []
    recompose: set[int] = set()
    rebuild: set[int] = set()
    llm_tasks: dict[int, list[str]] = {}
    split: set[int] = set()
    drop: set[int] = set()
    for iss in issues:
        if not iss.fix:
            continue
        a = iss.fix.get("action")
        n = iss.slide
        if n < 1 or n > len(layouts):
            if a == "llm_fix" and iss.fix.get("kind") == "language":
                for k in range(1, len(layouts) + 1):
                    llm_tasks.setdefault(k, []).append("весь текст — строго на русском языке")
            continue
        lay = layouts[n - 1]
        spec = plan.slides[n - 1]
        el = _find_el(lay, iss.element)
        if a in ("clamp", "recompose", "recrop", "overlap"):
            recompose.add(n)
        elif a == "enlarge":
            spec.opts["fill"] = True
            recompose.add(n)
        elif a == "remove_shape" and iss.fix.get("sid"):
            sid = iss.fix["sid"]
            if any(sf.sid == sid for sf in lay.slots):
                llm_tasks.setdefault(n, []).append(f"убери служебный текст-заглушку: {iss.message}")
            else:
                lay.remove_sids.append(sid)
                rebuild.add(n)
        elif a == "recolor_text":
            bg = iss.fix.get("bg") or profile.palette.bg_light
            pal = profile.palette
            col = readable([pal.text_dark, pal.text_light, "000000", "FFFFFF"], bg, 4.5)
            if el is not None:
                el.color = col
                for p in el.paras:
                    for r in p.runs:
                        r.color = None
                rebuild.add(n)
            else:
                for sf in lay.slots:
                    if sf.sid == iss.element:
                        sf.color = col
                        rebuild.add(n)
        elif a == "recolor" and el is not None:
            allowed = profile.palette.allowed()
            for attr in ("fill", "line", "color"):
                v = getattr(el, attr)
                if v:
                    setattr(el, attr, min(allowed, key=lambda c: color_distance(c, v)))
            rebuild.add(n)
        elif a == "refont":
            for e in lay.elements:
                if e.font and e.font not in (profile.typography.heading_font, profile.typography.body_font):
                    e.font = profile.typography.body_font
            rebuild.add(n)
        elif a == "snap_size" and el is not None and el.size:
            sc = profile.typography.scale
            el.size = max([z for z in sc if z <= el.size] or [min(sc)])
            rebuild.add(n)
        elif a == "condense":
            llm_tasks.setdefault(n, []).append(f"сократи тексты, которые не помещаются: {iss.message}")
        elif a == "set_title" and iss.fix.get("text"):
            spec.slide.title = iss.fix["text"]
            recompose.add(n)
        elif a == "fix_typos":
            pairs = iss.fix.get("pairs") or []
            s = spec.slide
            for pr in pairs:
                w, r = str(pr.get("wrong", "")), str(pr.get("right", ""))
                if not w or not r:
                    continue
                s.title = s.title.replace(w, r)
                s.lead = s.lead.replace(w, r)
                for it in s.items:
                    it.head, it.text = it.head.replace(w, r), it.text.replace(w, r)
            recompose.add(n)
        elif a in ("remove_unsupported", "llm_fix"):
            llm_tasks.setdefault(n, []).append(f"{iss.title}: {iss.message}")
        elif a == "split":
            split.add(n)
        elif a == "drop_slide":
            drop.add(n)
        elif a == "trim_series":
            if spec.slide.chart:
                spec.slide.chart.series = spec.slide.chart.series[:5]
            recompose.add(n)
    # LLM-правки контента
    import asyncio

    async def llm_fix(n: int, notes: list[str]):
        s = plan.slides[n - 1].slide
        try:
            res = await run.call("fixer", slide=_slide_json(s), issues="\n".join(f"- {x}" for x in notes),
                                 source=source[:3000], title_max=title_capacity(profile))
            _apply_json(s, res)
            log_lines.append(f"слайд {n}: исправлен моделью ({len(notes)} замеч.)")
        except Exception as e:
            log_lines.append(f"слайд {n}: модель недоступна ({e.__class__.__name__})")

    await asyncio.gather(*(llm_fix(n, notes) for n, notes in llm_tasks.items()))
    recompose |= set(llm_tasks)
    # разбиение перегруженных слайдов
    for n in sorted(split, reverse=True):
        spec = plan.slides[n - 1]
        s = spec.slide
        if len(s.items) > 3:
            half = (len(s.items) + 1) // 2
            s2 = s.model_copy(update={"id": s.id + "b", "items": s.items[half:], "title": s.title + " (продолжение)"})
            spec.slide = s.model_copy(update={"items": s.items[:half]})
            plan.slides.insert(n, spec.model_copy(update={"slide": s2}))
            layouts.insert(n, layouts[n - 1].model_copy())
            recompose |= {n, n + 1}
            log_lines.append(f"слайд {n}: разбит на два")
        elif s.table and len(s.table.rows) > 7:
            s.table.rows = s.table.rows[:7]
            recompose.add(n)
    for n in sorted(drop, reverse=True):
        del plan.slides[n - 1]
        del layouts[n - 1]
        log_lines.append(f"слайд {n}: удалён дубль")
    # пересборка слайдов композером
    comp = Composer(profile)
    changed = set(rebuild)
    for n in sorted(recompose):
        if n - 1 >= len(plan.slides):
            continue
        spec = plan.slides[n - 1]
        old = layouts[n - 1]
        new = comp.compose_best(spec, n, content.title, slide_extras(content, spec))
        new.remove_sids = list(dict.fromkeys(old.remove_sids + new.remove_sids))
        layouts[n - 1] = new
        changed.add(n)
    for i, lay in enumerate(layouts, 1):
        lay.index = i
        for sf in lay.slots:
            if sf.role == "pagenum":
                sf.text = str(i)
    if split or drop:
        changed = set(range(1, len(layouts) + 1))
    log_lines.append(f"изменено слайдов: {len(changed)}")
    return layouts, changed, log_lines

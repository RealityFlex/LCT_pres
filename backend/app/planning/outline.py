"""План колоды как артефакт (как outline у Kimi/Gamma): пользователь правит заголовки, порядок, типы и тезисы
до сборки; изменённые и новые слайды дописывает скилл slide_writer, остальные сохраняются как есть."""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from ..llm.skills import SkillRun
from ..parsing.model import TemplateProfile
from ..layout import icons
from .models import INTENTS, Brief, ContentSlide, DeckContent, Item
from .planner import _nums, fill_notes, norm_slide, notes_rule, title_capacity

log = logging.getLogger("outline")

# типы, которые пользователь выбирает в редакторе плана (подписи — на фронтенде)
EDITABLE = ["bullets", "cards", "process", "timeline", "stats", "chart", "table", "comparison", "quote", "image",
            "section", "agenda", "title", "closing"]


class OutlineSlide(BaseModel):
    id: Optional[str] = None          # id слайда из content.json; нет — новый слайд
    intent: str = "bullets"
    title: str
    points: list[str] = Field(default_factory=list)
    instruction: str = ""             # пожелание к слайду («добавь пример», «сделай таблицей»)


class Outline(BaseModel):
    title: str = ""
    slides: list[OutlineSlide]


def _points(s: ContentSlide) -> list[str]:
    if s.columns:
        return [c.title for c in s.columns]
    if s.table and s.table.rows:
        return [" · ".join(r[:2]) for r in s.table.rows[:6]]
    return [it.head or it.text for it in s.items if it.head or it.text]


def to_outline(content: DeckContent) -> Outline:
    return Outline(title=content.title, slides=[OutlineSlide(id=s.id, intent=s.intent, title=s.title, points=_points(s))
                                                for s in content.slides])


def apply_outline(content: DeckContent, outline: Outline) -> tuple[DeckContent, list[ContentSlide]]:
    """Новая колода по правленому плану и список слайдов, которые нужно дописать."""
    by_id = {s.id: s for s in content.slides}
    out: list[ContentSlide] = []
    dirty: list[ContentSlide] = []
    for o in outline.slides:
        intent = o.intent if o.intent in INTENTS else "bullets"
        title = (o.title or "").strip() or "Без названия"
        pts = [p.strip() for p in o.points if p and p.strip()]
        old = by_id.get(o.id or "")
        if old is not None:
            s = old.model_copy(deep=True)
            changed = intent != old.intent or title != old.title or pts != _points(old) or bool(o.instruction)
            s.intent, s.title = intent, title
            if changed:
                s.items = [Item(head=p) for p in pts]
                s.notes = s.notes if title == old.title else ""
                s.instruction = o.instruction
                dirty.append(s)
        else:
            s = ContentSlide(id="new", intent=intent, title=title, items=[Item(head=p) for p in pts],
                             instruction=o.instruction)
            dirty.append(s)
        out.append(s)
    for i, s in enumerate(out, 1):          # позиционные id, как после planner.normalize
        s.id = f"s{i}"
    new = content.model_copy(update={"slides": out, "title": outline.title or content.title,
                                     "target_slides": len(out)})
    return new, dirty


async def write_slides(deck: DeckContent, todo: list[ContentSlide], brief: Brief, profile: TemplateProfile,
                       run: SkillRun) -> None:
    """Содержание для изменённых/новых слайдов одним вызовом; структурные слайды заполняются как есть."""
    need = [s for s in todo if s.intent not in ("title", "section", "agenda")]
    if need:
        deck_lines = "\n".join(f"{i}. [{s.intent}] {s.title}" for i, s in enumerate(deck.slides, 1))
        ask = "\n".join(f"- id {s.id}: [{s.intent}] «{s.title}». Тезисы: {'; '.join(it.head for it in s.items) or '—'}"
                        + (f". Указание: {s.instruction}" if s.instruction else "") for s in need)
        try:
            raw = await run.call("slide_writer", topic=brief.topic, purpose=brief.purpose,
                                 audience=brief.audience or "руководители и команда",
                                 details=(brief.details or "(данных нет — не используй цифры)")[:9000],
                                 deck=deck_lines, slides=ask, title_max=title_capacity(profile),
                                 notes_rule=notes_rule(brief, len(deck.slides)), icons=icons.icon_catalog_hint())
            got = {str(x.get("id")): x for x in (raw or {}).get("slides", []) if isinstance(x, dict)}
        except Exception as e:      # без модели слайды остаются с тезисами человека
            log.warning("slide_writer failed: %s", e)
            got = {}
        src = _nums(" ".join([brief.topic, brief.details, brief.audience, brief.source_text]))
        for s in need:
            g = got.get(s.id)
            if not g:
                continue
            g = dict(g, intent=s.intent, title=g.get("title") or s.title)
            if s.code is not None:          # листинг из материалов — дословно, сценарист его не переписывает
                g["code"] = s.code.model_dump()
            sl = norm_slide(g, src, profile, int(s.id[1:]) if s.id[1:].isdigit() else 0)
            if sl is None:
                continue
            for f in ("lead", "kicker", "items", "chart", "table", "columns", "quote", "code", "notes"):
                v = getattr(sl, f)
                if v and not (f == "code" and s.code is not None):
                    setattr(s, f, v)
            s.intent = sl.intent
    for s in todo:
        s.instruction = ""
    await fill_notes(deck, brief, run)

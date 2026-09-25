"""Контекстные (недетерминированные) проверки: VLM по картинке слайда + текстовый ревью колоды."""
from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from ..layout.ir import SlideLayout
from ..llm.skills import SkillRun
from ..planning.models import DeckContent
from .model import Issue

log = logging.getLogger("audit.ctx")

QUESTIONS = {
    "q1": ("title_conclusion", "Заголовок не содержит вывода", "warning"),
    "q2": ("content_matches_title", "Содержимое не соответствует заголовку", "warning"),
    "q3": ("one_sentence", "Слайд не пересказывается одним предложением", "info"),
    "q4": ("facts_supported", "Цифры или факты отсутствуют в исходных материалах", "error"),
    "q5": ("has_content", "На слайде только заголовок", "error"),
    "q6": ("visuals_relevant", "Картинки или иконки не относятся к теме", "warning"),
    "q7": ("no_garbage", "Служебный мусор на слайде", "error"),
    "q8": ("typos", "Опечатки в тексте", "warning"),
    "q10": ("table_relevant", "Строки таблицы или легенда не работают на мысль слайда", "info"),
}
FIX_FOR = {
    "q1": "rewrite_title", "q4": "remove_unsupported", "q8": "fix_typos", "q7": "remove_garbage",
    "q2": "rewrite_title", "q5": "recompose",
}


def slide_text(lay: SlideLayout) -> str:
    parts = [f"[{s.role}] {s.text}" for s in lay.slots if s.text and s.role not in ("pagenum",)]
    for e in lay.elements:
        t = " ".join(p.text for p in e.paras)
        if t:
            parts.append(f"[{e.role}] {t}")
        if e.table:
            parts.append("[таблица] " + " | ".join(e.table["columns"]) + " / " +
                         " / ".join(" | ".join(r) for r in e.table["rows"]))
        if e.chart:
            parts.append("[диаграмма] " + ", ".join(e.chart["categories"]) + " : " +
                         "; ".join(f"{s['name']}={s['values']}" for s in e.chart["series"]))
        if e.icon:
            parts.append(f"[иконка] {e.icon}")
    return "\n".join(parts)[:2500]


def _small_png(path: Path, width: int = 1024) -> bytes:
    im = Image.open(path).convert("RGB")
    if im.width > width:
        im = im.resize((width, int(im.height * width / im.width)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


async def audit_slides(layouts: list[SlideLayout], pngs: list[Path], kinds: list[str], source: str,
                       run: SkillRun, title_max: int = 70, deadline: Optional[float] = None,
                       short_titles: bool = False) -> tuple[list[Issue], dict]:
    """short_titles — шаблон сам использует короткие заголовки-темы: «нет вывода» тогда лишь подсказка."""
    import time
    issues: list[Issue] = []
    raw: dict = {}
    total = len(layouts)

    async def one(i: int, lay: SlideLayout, png: Path):
        if deadline and time.time() > deadline:
            return
        try:
            res = await run.call("slide_auditor", images=[_small_png(png)], kind=kinds[i - 1], index=i, total=total,
                                 text=slide_text(lay), source=source[:3500], title_max=title_max)
        except Exception as e:
            log.warning("slide audit %s failed: %s", i, e)
            return
        if not isinstance(res, dict):
            return
        raw[i] = res
        for q, (check, title, sev) in QUESTIONS.items():
            a = res.get(q)
            if not isinstance(a, dict) or a.get("ok", True) is not False:
                continue
            if kinds[i - 1] in ("title", "section", "closing", "agenda") and q in ("q1", "q2", "q3", "q5"):
                continue
            text = slide_text(lay).casefold()
            if q == "q8":
                # VLM иногда «находит» опечатку, которой нет: слово должно быть в тексте и отличаться от исправления
                pairs = [t for t in (res.get("typos") or []) if isinstance(t, dict)
                         and str(t.get("wrong") or "").strip() and str(t.get("wrong")).casefold() in text
                         and str(t.get("wrong")).strip().casefold() != str(t.get("right") or "").strip().casefold()]
                if not pairs:
                    continue
                res["typos"] = pairs
            if q == "q1" and short_titles:
                sev = "info"
            fix = None
            act = FIX_FOR.get(q)
            if act == "rewrite_title" and res.get("better_title"):
                fix = {"action": "set_title", "text": str(res["better_title"])[:140]}
            elif act == "fix_typos" and res.get("typos"):
                fix = {"action": "fix_typos", "pairs": [t for t in res["typos"] if isinstance(t, dict)][:10]}
            elif act == "remove_unsupported" and res.get("unsupported"):
                fix = {"action": "remove_unsupported", "items": [str(x) for x in res["unsupported"]][:10]}
            elif act in ("remove_garbage", "recompose"):
                fix = {"action": "llm_fix", "kind": check}
            issues.append(Issue(id=f"{check}-{i}", check=check, title=title, category="content", severity=sev,
                                deterministic=False, slide=i, message=str(a.get("comment") or title)[:300], fix=fix,
                                fixable=fix is not None))

    await asyncio.gather(*(one(i, lay, png) for i, (lay, png) in enumerate(zip(layouts, pngs), 1)))
    return issues, raw


async def audit_deck(layouts: list[SlideLayout], run: SkillRun) -> list[Issue]:
    lines = []
    for i, lay in enumerate(layouts, 1):
        title = next((s.text for s in lay.slots if s.role == "title"), "")
        body = " ".join(" ".join(p.text for p in e.paras) for e in lay.elements)[:220]
        lines.append(f"{i}. {title} — {body}")
    try:
        res = await run.call("deck_auditor", slides="\n".join(lines))
    except Exception as e:
        log.warning("deck audit failed: %s", e)
        return []
    out: list[Issue] = []
    if isinstance(res, dict):
        q9 = res.get("q9") or {}
        if isinstance(q9, dict) and q9.get("ok") is False:
            out.append(Issue(id="deck_language", check="deck_language", title="Колода не на одном языке",
                             category="content", severity="warning", deterministic=False, slide=0,
                             message=str(q9.get("comment") or "")[:300],
                             fix={"action": "llm_fix", "kind": "language"}, fixable=True))
        for t in res.get("transitions") or []:
            if isinstance(t, dict) and t.get("ok") is False and str(t.get("problem") or "").strip():
                try:
                    to = int(t.get("to"))
                except (TypeError, ValueError):
                    continue
                out.append(Issue(id=f"transition-{to}", check="transition", title="Соседние слайды не связаны по логике",
                                 category="content", severity="info", deterministic=False, slide=to,
                                 message=str(t.get("comment") or "")[:300]))
    return out

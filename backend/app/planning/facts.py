"""Сверка чисел сценария с брифом — до вёрстки, без модели.

Цифры, сроки и количества на слайдах должны браться только из брифа. Модель иногда «додумывает»
(«первые 4 склада», «Q3 2026», «исследования показывают 70%»). Такие числа находятся здесь,
а слайды с ними отправляются корректору (скилл fixer) до сборки, чтобы не доходить до аудита.
"""
from __future__ import annotations

import re
from itertools import combinations
from typing import Iterable

from .models import Brief, ContentSlide, DeckContent

NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+(?:[.,]\d+)?)(?![\w])")
# служебная нумерация, а не факт: «01», «Шаг 2», «Этап 3», «Неделя 1»
INDEX_LABEL = re.compile(r"^\s*(?:(?:шаг|этап|step|неделя|пункт|часть|блок|раздел|группа|волна|фаза|уровень)\s*)?0?\d{1,2}\s*[.)]?\s*$", re.I)
# производные величины допустимы только в явном обороте: «в 3 раза», «на 2,7 п.п.»
DERIVED = re.compile(r"(\bв\s+\d+(?:[.,]\d+)?\s+раз|\d+(?:[.,]\d+)?\s*п\.\s?п\.)", re.I)


def _norm(tok: str) -> float | None:
    t = re.sub(r"[ \u00a0\u202f]", "", tok).replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def numbers(text: str) -> list[float]:
    return [v for v in (_norm(m.group(1)) for m in NUM.finditer(text or "")) if v is not None]


def source_numbers(brief: Brief) -> set[float]:
    return set(numbers(" ".join([brief.topic, brief.audience, brief.details])))


def _derived_ok(v: float, src: set[float]) -> bool:
    """«Втрое», «в 3 раза»: отношение или разность двух чисел брифа тоже подтверждено."""
    vals = [x for x in src if x]
    for a, b in combinations(vals, 2):
        for r in (a / b, b / a, abs(a - b)):
            if abs(r - v) <= max(0.1 * v, 0.051):
                return True
    return False


def _fields(s: ContentSlide) -> Iterable[tuple[str, str]]:
    yield "title", s.title
    yield "lead", s.lead
    yield "quote", s.quote
    for it in s.items:
        yield "head", it.head
        yield "text", it.text
        if it.value and not INDEX_LABEL.match(it.value):
            yield "value", it.value
    for c in s.columns:
        yield "col", c.title
        for p in c.points:
            yield "point", p
    if s.table:
        for c in s.table.columns:
            yield "cell", c
        for row in s.table.rows:
            for c in row:
                yield "cell", c
    if s.chart:
        for se in s.chart.series:
            for v in se.values:
                yield "chart", str(v).replace(".", ",")


def unsupported(content: DeckContent, brief: Brief) -> dict[str, list[str]]:
    """{slide_id: [«текст с числом»]} — числа на слайдах, которых нет в брифе."""
    src = source_numbers(brief)
    out: dict[str, list[str]] = {}
    for s in content.slides:
        if s.intent in ("title", "section"):
            continue      # подзаголовки разделов и нумерация «01» — оформление
        bad: list[str] = []
        for kind, text in _fields(s):
            if not text:
                continue
            for v in numbers(text):
                if v in src or (0 < v <= 12 and float(v).is_integer() and kind in ("head", "value") and INDEX_LABEL.match(text)):
                    continue
                if DERIVED.search(text) and _derived_ok(v, src):
                    continue
                bad.append(text.strip()[:120])
                break
        if bad:
            out[s.id] = list(dict.fromkeys(bad))[:6]
    return out


async def enforce(content: DeckContent, brief: Brief, run, title_max: int) -> list[str]:
    """Слайды с неподтверждёнными числами правит корректор (fixer); возвращает журнал правок."""
    import asyncio

    from ..audit.fixes import _apply_json, _slide_json
    found = unsupported(content, brief)
    if not found:
        return []
    by_id = {s.id: s for s in content.slides}
    source = f"Тема: {brief.topic}\nАудитория: {brief.audience}\nДанные: {brief.details}"
    log: list[str] = []

    async def one(sid: str, bad: list[str]):
        s = by_id[sid]
        notes = "\n".join(f"- «{t}»" for t in bad)
        try:
            res = await run.call("fixer", slide=_slide_json(s), source=source[:3000], title_max=title_max,
                                 issues="Числа, сроки и количества, которых нет в ИСТОЧНИКЕ. Убери их или замени "
                                        "качественной формулировкой, не выдумывай новых:\n" + notes)
            _apply_json(s, res)
            log.append(f"{sid}: убраны неподтверждённые числа ({len(bad)})")
        except Exception as e:  # корректор недоступен — аудит всё равно покажет замечание
            log.append(f"{sid}: не удалось исправить ({e.__class__.__name__})")

    await asyncio.gather(*(one(k, v) for k, v in found.items()))
    return log

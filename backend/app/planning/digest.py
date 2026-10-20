"""Длинные материалы: документ читается целиком по кускам (map) и сводится в выжимку (reduce).

Kimi читает методичку на 35–70 тыс. знаков полностью; раньше планировщик Лекала получал только первые 30 тыс.
Здесь каждый кусок конспектирует скилл material_digest (параллельно), конспекты сводит material_merge,
а цифры, которых нет в исходном тексте, из выжимки выбрасываются — контроль фактов работает по оригиналу.
"""
from __future__ import annotations

import asyncio
import logging
import re

from ..llm.skills import SkillRun
from .planner import _nums, numbers_supported

log = logging.getLogger("digest")

HEADING = re.compile(r"^\s*(#{1,6}\s|=== |\d+(\.\d+)*[.)]?\s+\S|[A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9 ,.:;«»\"()\-–—]{6,}$)")
SECTIONS = [("outline", "РАЗДЕЛЫ"), ("theses", "ТЕЗИСЫ"), ("definitions", "ТЕРМИНЫ"), ("steps", "ЭТАПЫ"),
            ("examples", "ПРИМЕРЫ"), ("facts", "ФАКТЫ")]


def chunk(text: str, size: int = 8000) -> list[str]:
    """Режет по строкам; кусок закрывается на заголовке, если уже набрано больше 60% размера."""
    parts, cur, n = [], [], 0
    for line in text.splitlines():
        if cur and n >= size * 0.6 and HEADING.match(line):
            parts.append("\n".join(cur))
            cur, n = [], 0
        while len(line) > size:              # строка-простыня (PDF без переносов)
            head, line = line[:size], line[size:]
            if cur:
                parts.append("\n".join(cur))
                cur, n = [], 0
            parts.append(head)
        cur.append(line)
        n += len(line) + 1
        if n >= size:
            parts.append("\n".join(cur))
            cur, n = [], 0
    if cur and "".join(cur).strip():
        parts.append("\n".join(cur))
    return [p for p in parts if p.strip()]


def _render(d: dict) -> str:
    out = []
    for key, ru in SECTIONS:
        items = [str(x).strip() for x in (d.get(key) or []) if str(x).strip()]
        if items:
            out.append(ru + ":\n" + "\n".join(f"- {x}" for x in items))
    return "\n".join(out)


def drop_unsupported(text: str, source: str) -> str:
    """Строки выжимки с цифрами, которых нет в исходнике, — выдумка модели: убираем их."""
    src = _nums(source)
    keep = [ln for ln in text.splitlines() if not ln.strip() or numbers_supported(ln, src)]
    return "\n".join(keep)


async def digest(text: str, topic: str, run: SkillRun, chunk_chars: int = 8000, limit: int = 12000) -> str:
    parts = chunk(text, chunk_chars)
    total = len(parts)

    async def one(i: int, part: str) -> str:
        try:
            raw = await run.call("material_digest", topic=topic, index=i + 1, total=total, part=part)
            return _render(raw if isinstance(raw, dict) else {})
        except Exception as e:      # кусок не прочитан — остальные всё равно пригодятся
            log.warning("digest part %s failed: %s", i + 1, e)
            return ""

    notes = [n for n in await asyncio.gather(*(one(i, p) for i, p in enumerate(parts))) if n]
    merged = "\n\n".join(f"[Фрагмент {i + 1}]\n{n}" for i, n in enumerate(notes))
    if len(merged) > limit:
        try:
            raw = await run.call("material_merge", topic=topic, digests=merged[:60000], limit=limit)
            got = (raw or {}).get("digest") if isinstance(raw, dict) else None
            if got and len(got) > 500:
                merged = got
        except Exception as e:
            log.warning("digest merge failed: %s", e)
    return drop_unsupported(merged, text)[:limit]

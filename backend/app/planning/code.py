"""Листинги кода из материалов: для практических и учебных колод пример кода — главный слайд.

Из PDF и DOCX код приходит без отступов и вперемешку с текстом методички («Листинг 1. …», комментарии,
перенесённые на следующую строку). Здесь он находится по виду строк, собирается во фрагменты с подписью,
а для Python отступы восстанавливаются по двоеточиям в конце строк.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CODE_START = re.compile(
    r"^\s*(def |class |return\b|import |from [\w.]+ import |assert |if .+:$|elif .+:$|else:|for .+:$|while .+:$|"
    r"try:|except\b|finally:|with .+:$|@\w|print\(|public |private |protected |static |void |function |const |"
    r"let |var |#include|package |SELECT |INSERT |UPDATE |CREATE |[{}]\s*$|\w[\w.\[\]]*\s*(=|\+=|-=)\s*\S)")
LISTING = re.compile(r"^\s*(Листинг|Пример кода|Listing)\s*\d*", re.I)


@dataclass
class Snippet:
    lines: list[str]
    caption: str = ""
    lead: str = ""                      # фраза перед фрагментом («Замена оператора проверки остатка на деление:»)
    pos: int = 0                        # позиция в тексте — по ней ищется слайд-сосед
    lang: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _strip_comment(line: str) -> str:
    return re.split(r"\s(#|//)\s", line, maxsplit=1)[0].rstrip()


def _is_code(line: str) -> bool:
    core = _strip_comment(line).strip()
    if not core or len(core) > 120:
        return False
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", core)
    latin = sum(1 for c in letters if c.isascii())
    return bool(CODE_START.match(core)) and (not letters or latin / len(letters) >= 0.8)


def _lang(lines: list[str]) -> str:
    t = "\n".join(lines)
    if re.search(r"^\s*(def |class \w+.*:$|assert |import \w+$)", t, re.M) or re.search(r":\s*$", t, re.M):
        return "python"
    if re.search(r"\b(public|private|static)\b.*[{;]", t):
        return "java"
    if re.search(r"\b(function|const|let)\b", t):
        return "javascript"
    if re.search(r"\b(SELECT|INSERT|CREATE)\b", t):
        return "sql"
    return ""


def _reindent_python(lines: list[str]) -> list[str]:
    """Отступы Python по структуре: def/class — с нуля, тело — +4, после строки с «:» — ещё +4 на одну строку."""
    out, base, extra = [], 0, 0
    for ln in lines:
        core = ln.strip()
        if re.match(r"^(def |class |@)", core):
            base, extra = 0, 0
            out.append(core)
            if core.endswith(":"):
                base = 4
            continue
        out.append(" " * (base + extra) + core)
        extra = 4 if core.endswith(":") else 0
    return out


def find_snippets(text: str, limit: int = 6) -> list[Snippet]:
    lines = (text or "").splitlines()
    out: list[Snippet] = []
    i, offset = 0, 0
    offsets = []
    for ln in lines:
        offsets.append(offset)
        offset += len(ln) + 1
    while i < len(lines):
        if not _is_code(lines[i]):
            i += 1
            continue
        start = i
        block: list[str] = []
        gap = 0
        while i < len(lines):
            if _is_code(lines[i]):
                block.append(_strip_comment(lines[i]).strip())
                gap = 0
            elif gap == 0 and len(lines[i].strip()) < 60 and block:
                gap = 1                     # перенос комментария на следующую строку — пропускаем
            else:
                break
            i += 1
        if len(block) < 2 and not (block and re.match(r"^(def|class|function|public)\b", block[0])):
            continue
        prev = [ln.strip() for ln in lines[max(0, start - 3):start] if ln.strip()]
        caption = next((p for p in reversed(prev) if LISTING.match(p)), "")
        lead = next((p for p in reversed(prev) if p.endswith(":") and not LISTING.match(p)), "")
        sn = Snippet(lines=block[:16], caption=caption.rstrip(" :"), lead=lead.rstrip(":"), pos=offsets[start])
        sn.lang = _lang(sn.lines)
        if sn.lang == "python":
            sn.lines = _reindent_python(sn.lines)
        out.append(sn)
    return out[:limit]


def group_snippets(snips: list[Snippet], max_lines: int = 14, max_slides: int = 2) -> list[Snippet]:
    """Соседние короткие фрагменты (функция + тест, несколько мутантов) — на один слайд, через пустую строку;
    подпись короткого фрагмента без «Листинга» становится комментарием над ним."""
    out: list[Snippet] = []
    cur: Snippet | None = None
    for sn in snips:
        body = list(sn.lines)
        if sn.lead and not sn.caption:
            mark = "#" if sn.lang in ("python", "") else "//"
            body = [f"{mark} {sn.lead[:60]}"] + body
        # листинги с подписью и безымянные варианты (мутанты, «было/стало») — разные слайды
        same_kind = cur is not None and bool(cur.caption) == bool(sn.caption)
        if cur is not None and same_kind and len(cur.lines) + 1 + len(body) <= max_lines and sn.pos - cur.pos < 4000:
            cur.lines += [""] + body
            continue
        if cur is not None:
            out.append(cur)
        cur = Snippet(lines=body, caption=sn.caption, lead=sn.lead, pos=sn.pos, lang=sn.lang)
    if cur is not None:
        out.append(cur)
    return out[:max_slides]

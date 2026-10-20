"""Исследование темы перед планированием (как у Genspark/Kimi): модель формулирует запросы, источник
(по умолчанию бесплатный API Википедии; платный Яндекс Поиск — по настройке search.provider) даёт тексты,
модель выписывает из них факты, факты с источниками попадают в бриф как проверяемые данные.

Цифры из ответов становятся «цифрами брифа» — контроль фактов их пропускает, а слайды, где они
использованы, получают подпись источника в подвале и ссылки в заметках спикера.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re

from pydantic import BaseModel, Field

from ..config import get_settings
from ..llm.skills import SkillRun
from ..planning.facts import numbers
from ..planning.models import Brief, DeckContent, Source
from .yandex import host_of, searcher

log = logging.getLogger("research")
REF = re.compile(r"\[(\d{1,2})\]")


class Fact(BaseModel):
    text: str
    refs: list[int] = Field(default_factory=list)


class Research(BaseModel):
    provider: str = ""
    supplement: bool = False                               # дополнение к подробному материалу пользователя
    queries: list[str] = Field(default_factory=list)
    articles: list[dict] = Field(default_factory=list)     # прочитанные статьи (главные картинки — кандидаты в фото)
    facts: list[Fact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)

    def text(self, limit: int = 7000) -> str:
        if not self.facts:
            return ""
        today = dt.date.today().strftime("%d.%m.%Y")
        lines = [f"ДАННЫЕ ИЗ ИНТЕРНЕТА ({self.provider}, {today}). Цифры бери только отсюда или из брифа; "
                 "в квадратных скобках — номер источника. Это материал для тезисов: заголовок слайда — твой вывод "
                 "для аудитории (до 8 слов), а не пересказ факта; не строй колоду как пересказ статей"
                 + ("; ГЛАВНЫЙ ИСТОЧНИК — материал пользователя выше, отсюда — только 1–2 дополнения "
                    "(история, применение)" if self.supplement else "")]
        for f in self.facts:
            lines.append(f"• {f.text}")
        used = {n for f in self.facts for n in f.refs}
        lines.append("Источники: " + "; ".join(f"[{s.n}] {s.host} — {s.title[:80]}" for s in self.sources if s.n in used))
        out = "\n".join(lines)
        return out[:limit]


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"^\s*[-*•]\s*", "", text, flags=re.M)
    parts = re.split(r"(?<=[.!?…])\s+(?=[А-ЯA-Z«\"(\d])|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 20]


async def _queries(brief: Brief, run: SkillRun, n: int, where: str) -> list[str]:
    try:
        raw = await run.call("web_researcher", topic=brief.topic, purpose=brief.purpose,
                             audience=brief.audience or "руководители и команда",
                             details=(brief.details or "")[:3000] or "(нет)", n=n, where=where,
                             year=dt.date.today().year)
        qs = [str(q).strip() for q in (raw.get("queries") if isinstance(raw, dict) else []) or [] if str(q).strip()]
    except Exception as e:
        log.warning("web_researcher failed: %s", e)
        qs = []
    return (qs or [brief.topic])[:n]


async def research(brief: Brief, run: SkillRun, supplement: bool = False) -> Research:
    """Ошибки поиска не роняют пайплайн: без данных из сети колода строится по брифу, как раньше.
    supplement — пользователь сам дал подробный материал: из сети берём только дополнение (2 статьи)."""
    cfg = get_settings().raw.get("search", {}) or {}
    provider = cfg.get("provider", "wikipedia")
    try:
        if provider == "wikipedia":
            return await _wiki_research(brief, run, int(cfg.get("queries", 4)),
                                        2 if supplement else int(cfg.get("max_articles", 4)), supplement)
        if provider == "yandex":
            return await _yandex_research(brief, run, int(cfg.get("queries", 4)))
    except Exception as e:
        log.warning("research failed: %s", e)
    return Research()


STOP = {"россии", "россия", "истори", "развит", "пробле", "статис", "использ", "внедре", "цифров", "систем"}


def _stems(text: str) -> set[str]:
    """Основы значимых слов (первые 6 букв) — грубая, но устойчивая к падежам мера совпадения."""
    words = {w.lower()[:6] for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", text)}
    core = words - STOP
    return core or words


def _focus(text: str, topic: str, limit: int) -> str:
    """Длинная статья: начало (определения) + абзацы со словами темы, в пределах limit знаков."""
    if len(text) <= limit:
        return text
    stems = {w.lower()[:6] for w in re.findall(r"[A-Za-zА-Яа-яЁё]{5,}", topic)}
    paras = [p for p in text.split("\n") if p.strip()]
    head, out, used = [], [], 0
    for p in paras:
        if used > limit * 0.35:
            break
        head.append(p)
        used += len(p)
    rest = paras[len(head):]
    scored = sorted(rest, key=lambda p: -sum(1 for st in stems if st in p.lower()) - (0.5 if re.search(r"\d", p) else 0))
    for p in scored:
        if used + len(p) > limit:
            continue
        out.append(p)
        used += len(p)
    keep = set(out)
    return "\n".join(head + [p for p in rest if p in keep])


async def _wiki_research(brief: Brief, run: SkillRun, n_queries: int, max_articles: int,
                         supplement: bool = False) -> Research:
    from .wiki import wiki
    w = wiki()
    res = Research(provider="Википедия")
    where = "Википедия (названия статей и ключевые понятия)"
    if supplement:
        where += ("; материал пользователя уже подробный — ищи только то, чего в нём обычно нет: историю "
                  "появления, применение в индустрии, известные примеры")
    res.queries = await _queries(brief, run, n_queries, where)
    res.supplement = supplement
    found = await asyncio.gather(*(w.search(q, 6) for q in res.queries), *(w.titles(q, 3) for q in res.queries),
                                 return_exceptions=True)
    hits: dict[str, str] = {}               # название → фрагмент
    scored = []
    nq = len(res.queries)
    for k, f in enumerate(found):
        if isinstance(f, BaseException):
            log.warning("wiki search failed: %r", f)
            continue
        q = res.queries[k % nq]
        stems = _stems(q)
        for i, hit in enumerate(f):
            title, snip = (hit["title"], hit["snippet"]) if isinstance(hit, dict) else (hit, "")
            hits.setdefault(title, snip)
            low = title.lower()
            score = 2 * sum(1 for st in stems if st in low) + sum(1 for st in stems if st in snip.lower())
            scored.append((-score - (2 if k >= nq else 0), i, title))
    # полнотекстовый поиск Википедии приносит и случайные статьи (персоны, школы, соседние страны) —
    # нужные выбирает модель по названиям и фрагментам; без ответа модели — по совпадению слов
    titles: list[str] = []
    if hits:
        cands = "\n".join(f"- {t}: {s[:160]}" for t, s in list(hits.items())[:30])
        try:
            raw = await run.call("wiki_picker", topic=brief.topic, audience=brief.audience or "руководители и команда",
                                 n=max_articles, candidates=cands)
            titles = [t for t in (raw.get("titles") if isinstance(raw, dict) else []) or [] if t in hits]
        except Exception as e:
            log.warning("wiki_picker failed: %s", e)
        if not titles:
            for sc, _, t in sorted(scored):
                if sc <= -2 and t not in titles:
                    titles.append(t)
    arts = await asyncio.gather(*(w.article(t) for t in titles[:max_articles]), return_exceptions=True)
    arts = [a for a in arts if isinstance(a, dict) and len(a.get("text", "")) > 400]
    res.articles = [{"title": a["title"], "url": a["url"], "image": a.get("image")} for a in arts]

    async def read(a: dict, n: int) -> list[Fact]:
        body = _focus(a["text"], f"{brief.topic} {brief.audience}", 10000)
        try:
            raw = await run.call("wiki_reader", topic=brief.topic, audience=brief.audience or "руководители и команда",
                                 title=a["title"], text=body)
        except Exception as e:
            log.warning("wiki_reader %s failed: %s", a["title"], e)
            return []
        if isinstance(raw, dict) and raw.get("relevant") is False:
            return []
        art_nums = set(numbers(a["text"]))
        out = []
        for f in (raw.get("facts") if isinstance(raw, dict) else []) or []:
            t = re.sub(r"\s+", " ", str(f)).strip()
            # число, которого нет в статье, модель додумала — такой факт не берём
            if len(t) < 25 or not set(numbers(t)) <= art_nums:
                continue
            out.append(Fact(text=f"{t} [{n}]", refs=[n]))
        return out[:8]

    srcs = [Source(n=i, title=a["title"], url=a["url"], host=host_of(a["url"])) for i, a in enumerate(arts, 1)]
    got = await asyncio.gather(*(read(a, i) for i, a in enumerate(arts, 1)))
    res.facts = [f for fs in got for f in fs]
    res.sources = srcs
    return res


async def _yandex_research(brief: Brief, run: SkillRun, n_queries: int) -> Research:
    srch = searcher()
    res = Research(provider="Яндекс Поиск")
    if not srch.enabled:
        return res
    res.queries = await _queries(brief, run, n_queries, "поисковая система (вопросы о свежих фактах и цифрах)")
    answers = await asyncio.gather(*(srch.answer(q) for q in res.queries), return_exceptions=True)
    by_url: dict[str, Source] = {}
    for q, a in zip(res.queries, answers):
        if isinstance(a, BaseException) or not a.get("text"):
            if isinstance(a, BaseException):
                log.warning("search %r failed: %s", q, a)
            continue
        local: dict[int, int] = {}
        for i, s in enumerate(a["sources"], 1):
            src = by_url.get(s["url"])
            if src is None:
                src = Source(n=len(by_url) + 1, title=s["title"] or host_of(s["url"]), url=s["url"], host=host_of(s["url"]))
                by_url[s["url"]] = src
            local[i] = src.n
        for sent in _sentences(a["text"]):
            refs = sorted({local[int(m)] for m in REF.findall(sent) if int(m) in local})
            clean = REF.sub("", sent).strip()
            clean = re.sub(r"\s+([.,;:])", r"\1", clean)
            if refs:
                res.facts.append(Fact(text=f"{clean} [{', '.join(map(str, refs))}]", refs=refs))
    res.sources = sorted(by_url.values(), key=lambda s: s.n)
    return res


def _distinctive(vals: list[float]) -> set[float]:
    """Числа, по которым можно узнать факт: без годов и мелких счётчиков («3 этапа», «2024 год»)."""
    return {v for v in vals if not (v == int(v) and (v < 10 or 1900 <= v <= 2100))}


def _label(src: Source) -> str:
    """Подпись в подвале: у Википедии важна статья, у сайтов — домен."""
    return f"Википедия, «{src.title[:40]}»" if src.host.endswith("wikipedia.org") else src.host


def attach_sources(deck: DeckContent, res: Research) -> int:
    """Слайд, где стоит цифра из найденного ответа, получает источник: в подвал (домен) и в заметки (ссылка)."""
    if not res.facts:
        return 0
    by_n = {s.n: s for s in res.sources}
    fact_nums = [(_distinctive(numbers(f.text)), f.refs) for f in res.facts]
    used: set[int] = set()
    marked = 0
    for s in deck.slides:
        txt = " ".join([s.title, s.lead, s.quote] + [f"{it.value or ''} {it.head} {it.text}" for it in s.items]
                       + [" ".join(c.points) for c in s.columns]
                       + ([" ".join(" ".join(r) for r in s.table.rows)] if s.table else [])
                       + ([" ".join(str(v) for se in s.chart.series for v in se.values)] if s.chart else []))
        mine = _distinctive(numbers(txt))
        refs: list[int] = []
        for nums, rr in fact_nums:
            if mine & nums:
                refs += [r for r in rr if r not in refs]
        if not refs:
            continue
        refs = refs[:3]
        used.update(refs)
        labels = list(dict.fromkeys(_label(by_n[r]) for r in refs if r in by_n))
        s.source_note = ("Источник: " if len(labels) == 1 else "Источники: ") + "; ".join(labels[:2])
        links = "; ".join(f"{by_n[r].title[:70]} — {by_n[r].url}" for r in refs if r in by_n)
        s.notes = (s.notes.rstrip() + f"\n\nИсточники: {links}").strip()
        marked += 1
    deck.sources = [s for s in res.sources if s.n in used]
    return marked

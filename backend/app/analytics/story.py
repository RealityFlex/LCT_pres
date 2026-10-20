"""Слайды аналитики: посчитанное кодом (analyze.py) → слайд-диаграмма с выводом в заголовке.

Модель пишет только слова — вывод, интерпретацию, подписи и текст спикера; числа берутся из фактов
кода, а всё, что модель «досчитала», отбрасывается (заголовок тогда остаётся детерминированным).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from ..llm.skills import SkillRun
from ..parsing.model import TemplateProfile
from ..planning.models import Brief, ChartSpec, ContentSlide, DeckContent, Item, Series, TableSpec
from ..planning.planner import _nums, numbers_supported, title_capacity
from .analyze import Insight, analyze, facts_text, fpct
from .ingest import load
from .recommend import TASK_RU, build_chart, explain, goal_for

log = logging.getLogger("analytics")


def load_insights(paths: list[Path], goals: dict[str, str] | None = None, brief_text: str = "",
                  failed: list[dict] | None = None, cross: list[str] | None = None) -> tuple[list[Insight], list[str]]:
    """Все датасеты из файлов и текст вокруг таблиц (из текстовых файлов).

    goals — цель к конкретному датасету (id файла → «показать связь цены и продаж»); brief_text — бриф:
    из него к датасету идут только предложения, которые говорят о его колонках или о файле.
    failed — сюда попадают датасеты, которые не удалось разобрать: {file, name, reason} (слайд-сообщение вместо пропуска).
    """
    failed = failed if failed is not None else []
    pairs = []
    # цели брифа распределяются между датасетами заранее: фраза — тому, кто совпал с ней лучше всех
    brief_goals: dict[str, str] = {}
    if brief_text:
        from .analyze import describe, profile
        from .recommend import assign_goals
        cand = []
        for p in paths:
            try:
                tabs, _ = load(p.name.split("__", 1)[-1], p.read_bytes())
            except Exception:
                continue
            for t in tabs:
                try:
                    dfp, cols = profile(t.df)
                    mets = describe(dfp, cols).metrics
                except Exception:
                    mets = []
                cand.append((f"{p.name}::{t.name}", [str(c) for c in t.df.columns], mets))
        brief_goals = assign_goals(brief_text, cand)
    out: list[Insight] = []
    texts: list[str] = []
    goals = goals or {}
    for p in paths:
        try:
            tables, text = load(p.name.split("__", 1)[-1], p.read_bytes())
        except Exception as e:
            log.warning("dataset %s unreadable: %s", p.name, e)
            failed.append({"file": p.name.split("__", 1)[-1], "name": p.name.split("__", 1)[-1],
                           "reason": f"файл не читается как таблица ({e.__class__.__name__})"})
            continue
        if not tables:
            failed.append({"file": p.name.split("__", 1)[-1], "name": p.name.split("__", 1)[-1],
                           "reason": "в файле не найдено ни одной таблицы с заголовками колонок"})
        if text.strip():
            texts.append(f"=== {p.name.split('__', 1)[-1]} ===\n{text.strip()[:6000]}")
        for t in tables:
            goal = " ".join(x for x in (goals.get(p.name, ""), brief_goals.get(f"{p.name}::{t.name}", "")) if x)
            try:
                ins = analyze(t, goal)
            except Exception as e:
                log.warning("analyze %s failed: %s", t.name, e)
                ins = None
            if ins is not None and (ins.agg.get("categories") or ins.agg.get("points")):
                ins.file = p.name.split("__", 1)[-1]
                out.append(ins)
                pairs.append((ins, t))
            else:
                from .analyze import unreadable_reason
                failed.append({"file": p.name.split("__", 1)[-1], "name": t.name,
                               "reason": unreadable_reason(t) or "не нашлось ни метрики, ни измерения, по которым можно что-то показать"})
    # порядок рассказа: динамика → структура (кто, из чего) → поведение (распределение) → связи → справочник →
    # качество данных; внутри природы — по размеру датасета
    rank = {"timeseries": 0, "comparison": 1, "shares": 2, "distribution": 3, "relationship": 4, "reference": 5, "gaps": 6}
    out.sort(key=lambda x: (rank.get(x.nature, 9), -x.rows))
    if cross is not None and len(pairs) >= 2:
        from .cross import cross_facts
        try:
            cross.extend(cross_facts(pairs))
        except Exception as e:
            log.warning("cross facts failed: %s", e)
    return out, texts


def _describe(ins: Insight, i: int) -> str:
    ch = ins.chart
    kp = "; ".join(f"{k['value']} — {k['head']} ({k['text']})" for k in ins.kpis)
    opt = ins.options[0] if ins.options else {}
    return (f"[Д{i}] «{ins.dataset}»: {ins.nature_ru}, {ins.rows} строк. Задача: {TASK_RU.get(ins.nature, ins.nature)}. "
            f"Метод: {ins.method}.\n"
            f"  Профиль: {ins.profile.get('summary', '')}\n"
            f"  Визуализация: {opt.get('label', ch.get('type'))} — {opt.get('why', '')}; "
            f"оси: {ch.get('x_title', '')} / {ch.get('y_title', '')}.\n"
            f"  Факты: " + " | ".join(ins.facts) + f"\n  kpis (в этом порядке): {kp}")


EMPTY_PHRASES = re.compile(r"(требу\w+ внимани|важно учитывать|необходимо (анализ|учитыв)|стоит обратить внимание|"
                           r"нужна оптимизац|требу\w+ оптимизац|создаёт риски\W*$|данные показывают|как видно)", re.I)


# причинная связка между показателями: «рост за счёт открытий», «подтверждает эффективность» — корреляция ≠ причина
# в заголовках сюжета причинность шире: «рост обеспечен расширением», «продажи следуют за открытиями»
STORY_CAUSAL = re.compile(r"(обеспеч(ен|ива|ил|ат)\w*|следу\w+\s+за\s|привод\w+\s+к\s|вызван\w*|двига\w+\s+рост)", re.I)
# «ускорился», «замедлился» — только если это прямо есть в фактах кода
TREND = re.compile(r"(ускор|замедл)\w*", re.I)


def trend_ok(t: str, facts: str) -> bool:
    return all(re.search(m.group(1), facts, re.I) and not re.search(r"почти не изменил", facts, re.I)
               for m in TREND.finditer(t or ""))
CAUSAL = re.compile(r"(за\s+сч[её]т|благодаря|подтвержда\w+\s+эффективност|доказыва\w+|напрямую\s+(завис|связан|коррелир))", re.I)


GENERIC_HEAD = re.compile(r"^(вывод\w*|итог\w*|что делать|что следует|следстви\w*|рекомендац\w*|важно|почему важно|"
                          r"почему это важно|что из этого следует|инсайт|главное)$", re.I)


def _head(v, ok) -> str:
    """Заголовок-мысль блока «и что?»: 2–5 слов, без шаблонных «Вывод/Итог», без чисел вне фактов."""
    t = re.sub(r"\s+", " ", str(v or "")).strip().strip(".:—- «»\"")
    if not t or len(t.split()) > 5 or len(t) > 40 or GENERIC_HEAD.match(t) or not ok(t) or CAUSAL.search(t):
        return ""
    return t[:1].upper() + t[1:]


def _takeaway_text(v, ok, words: int) -> str:
    """Ответ на «и что?» — только предметный: без пустых формул, без чисел вне фактов, не длиннее words слов."""
    t = re.sub(r"\s+", " ", str(v or "")).strip().rstrip(".")
    parts = re.split(r"(?<=[.!?;])\s+", t)
    if len(t.split()) > 15 and len(parts) > 1 and len(parts[0].split()) >= 5:
        t = parts[0].rstrip(".;")         # длинный ответ — первая мысль целиком, а не обрезок
    if not t or not ok(t) or EMPTY_PHRASES.search(t) or CAUSAL.search(t) or len(t.split()) > words:
        return ""
    return t[:1].upper() + t[1:]


def apply_viz(slide: ContentSlide, ins: Insight, viz: str) -> None:
    """Вариант визуализации → поля слайда: диаграмма, таблица или карточки с цифрами."""
    ch = build_chart(ins, viz)
    slide.table = None
    slide.chart = None
    if viz == "table":
        t = ch.get("table") or {}
        slide.intent = "table"
        slide.table = TableSpec(columns=[str(c) for c in t.get("columns", [])],
                                rows=[[str(v) for v in r] for r in t.get("rows", [])])
    elif viz == "kpi":
        slide.intent = "stats"
    else:
        slide.intent = "chart"
        slide.chart = ChartSpec(type=ch["type"], categories=[str(c) for c in ch.get("categories", [])],
                                series=[Series(name=s["name"], values=[float(v) for v in s["values"]]) for s in ch.get("series", [])],
                                unit=ch.get("unit", ""), number_format=ch.get("number_format", ""),
                                highlight=ch.get("highlight", []), labels=ch.get("labels", True), gap=ch.get("gap"),
                                x_title=ch.get("x_title", ""), y_title=ch.get("y_title", ""),
                                points=ch.get("points") or {}, trend=ch.get("trend") or [],
                                x_format=ch.get("x_format", ""), y_format=ch.get("y_format", ""),
                                y_min=ch.get("y_min"), y_max=ch.get("y_max"), viz=viz)
    slide.data = {**slide.data, "viz": viz}


async def data_slides(insights: list[Insight], brief: Brief, profile: TemplateProfile, run: SkillRun) -> list[ContentSlide]:
    if not insights:
        return []
    tmax = title_capacity(profile)
    try:
        raw = await run.call("data_analyst", topic=brief.topic, audience=brief.audience or "руководители и команда",
                             purpose=brief.purpose, details=(brief.details or "")[:1500], title_max=tmax,
                             datasets="\n\n".join(_describe(x, i) for i, x in enumerate(insights, 1)))
        got = {str(s.get("id", "")).strip(): s for s in (raw or {}).get("slides", []) if isinstance(s, dict)}
    except Exception as e:
        log.warning("data_analyst failed: %s", e)
        got = {}
    slides = []
    for i, ins in enumerate(insights, 1):
        g = got.get(f"Д{i}") or got.get(f"D{i}") or {}
        src = _nums(" ".join(ins.facts + [f"{k['value']} {k['head']} {k['text']}" for k in ins.kpis] + [ins.title]))
        src |= set(float(y) for y in range(1990, 2036))     # годы — контекст периода, а не «досчитанная» цифра
        ok = lambda t: bool(t) and numbers_supported(t, src) and trend_ok(t, " ".join(ins.facts))          # noqa: E731
        title = str(g.get("title") or "").strip().rstrip(".")
        title = title if ok(title) and len(title) <= tmax + 10 else ins.title
        lead = str(g.get("lead") or "").strip()
        lead = lead if ok(lead) and len(lead.split()) <= 26 else ""
        # «и что?»: почему важно и что из этого следует — без пустых формул и без досчитанных чисел
        why, then = (_takeaway_text(g.get(k), ok, w) for k, w in (("why", 20), ("then", 18)))
        why_head, then_head = _head(g.get("why_head"), ok) if why else "", _head(g.get("then_head"), ok) if then else ""
        if why or then:
            lead = ""             # вывод под графиком заменяет вводную фразу — третий уровень текста не нужен
        # заметки — текст спикера: числа профиля (строки, выбросы, точки) тоже посчитаны кодом; неподтверждённое
        # предложение выпадает само, а не уносит с собой весь текст
        src_n = src | _nums(f"{ins.profile.get('summary', '')} {ins.method} {explain(ins)}")
        sents = re.split(r"(?<=[.!?])\s+", str(g.get("notes") or "").strip())
        sents = [t for t in sents if t and numbers_supported(t, src_n) and trend_ok(t, " ".join(ins.facts))]
        notes = " ".join(sents) if len(sents) >= 2 else " ".join(ins.facts)
        notes += (f"\n\nДанные: «{ins.file or ins.dataset}» — {ins.profile.get('summary', '')}. Метод: {ins.method}. "
                  + explain(ins))
        raw_items = [h for h in (g.get("items") or []) if isinstance(h, dict)] if isinstance(g.get("items"), list) else []
        norm = lambda v: str(v or "").replace(" ", " ").replace(" ", "").lower()     # noqa: E731
        items = []
        for k, kp in enumerate(ins.kpis):
            # подпись берётся только у пункта с тем же значением: иначе к «240 записей» модель приписывает «лидер цен»
            h = next((x for x in raw_items if norm(x.get("value")) == norm(kp["value"])), None)
            if h is None and k < len(raw_items) and not raw_items[k].get("value"):
                h = raw_items[k]
            h = h or {}
            head = str(h.get("head") or kp["head"]).strip()[:40]
            text = str(h.get("text") or kp["text"]).strip()[:90]
            # подпись не повторяет саму цифру («376 ₽ — …медиана 376 ₽»): тогда — подпись кода
            if norm(kp["value"]) and norm(kp["value"]) in norm(text):
                text = kp["text"]
            if not ok(f"{head} {text}") or (head == kp["head"] and text == kp["text"]):
                head, text = kp["head"], kp["text"]
            items.append(Item(value=kp["value"], head=head, text=text))
        kicker = str(g.get("kicker") or "ДАННЫЕ · АНАЛИЗ").strip()[:28] if profile.narrative.uses_kicker else ""
        if why or then:
            notes += "".join(f" {lab}: {t}." for lab, t in (("Почему это важно", why), ("Что из этого следует", then)) if t)
        sl = ContentSlide(id=f"d{i}", intent="chart", title=title, lead=lead, kicker=kicker, items=items, notes=notes,
                          why=why, then=then, why_head=why_head, then_head=then_head,
                          source_note=f"Источник: {ins.file or ins.dataset}",
                          data={"index": i - 1, "dataset": ins.dataset, "file": ins.file, "task": ins.nature,
                                "task_ru": TASK_RU.get(ins.nature, ins.nature), "options": ins.options,
                                "profile": ins.profile.get("summary", "")})
        apply_viz(sl, ins, ins.viz)
        slides.append(sl)
        extra = tail_slide(ins, sl)
        if extra is not None:
            slides.append(extra)
    return slides


def failed_slides(failed: list[dict], profile: TemplateProfile) -> list[ContentSlide]:
    """Датасет, который не удалось разобрать, — не молча выпадает, а честно показан со способом исправить."""
    out = []
    for k, f in enumerate(failed[:3], 1):
        out.append(ContentSlide(
            id=f"x{k}", intent="cards", title=("Один файл не вошёл в анализ: в нём нет чисел" if "чис" in f["reason"]
                                      else "Один файл не вошёл в анализ"),
            kicker="ДАННЫЕ · ПРОВЕРКА" if profile.narrative.uses_kicker else "",
            items=[Item(head="Что не так", text=f"{f['file']}: {f['reason']}"[:110], icon="alert-triangle"),
                   Item(head="Что сделать", text="Первая строка — названия колонок, хотя бы одна колонка с числами", icon="table"),
                   Item(head="Что в презентации", text="Выводы по этому файлу не делались — цифр из него нет", icon="info")],
            source_note=f"Источник: {f['file']}",
            notes=f"Файл «{f['file']}» (таблица «{f['name']}») не вошёл в анализ: {f['reason']}. "
                  "Чтобы он попал в презентацию, сохраните таблицу с заголовками колонок и числовыми значениями (CSV, XLSX или JSON)."))
    return out


def tail_slide(ins: Insight, first: ContentSlide) -> ContentSlide | None:
    """Много категорий и тяжёлый хвост (> 25% итога): вторая часть списка — отдельным слайдом, а не «Прочие»."""
    full = ins.agg.get("full") or {}
    if ins.nature != "comparison" or ins.agg.get("tail_share", 0) <= 0.25 or len(full.get("categories", [])) <= 12:
        return None
    cats, vals = full["categories"], full["values"]
    head = dict(ins.agg, categories=cats[:10], series=[{"name": ins.agg["series"][0]["name"], "values": vals[:10]}],
                highlight=[cats[0]], full={})
    rest_c, rest_v = cats[10:30], vals[10:30]
    if len(cats) > 30:
        rest_c, rest_v = rest_c + ["Прочие"], rest_v + [sum(vals[30:]) if ins.agg.get("agg") == "sum" else sum(vals[30:]) / len(vals[30:])]
    tail = dict(ins.agg, categories=rest_c, series=[{"name": ins.agg["series"][0]["name"], "values": rest_v}],
                highlight=[rest_c[0]], full={})
    from copy import copy
    a, b = copy(ins), copy(ins)
    a.agg, b.agg = head, tail
    apply_viz(first, a, "bar" if ins.viz in ("bar", "column") else ins.viz)
    sl = first.model_copy(deep=True)
    sl.id = first.id + "b"
    share = ins.agg["tail_share"] * 100
    sl.title = f"Остальные {len(cats) - 10} категорий дают {fpct(share, 0)} итога"
    sl.lead = ""
    sl.items = []
    sl.why = sl.then = sl.why_head = sl.then_head = ""          # «и что?» — на основном слайде датасета
    sl.notes = (f"Продолжение «{ins.dataset}»: категории с 11-й по {min(len(cats), 30)}-ю"
                + (", дальше — «Прочие»" if len(cats) > 30 else "") + f". На них приходится {fpct(share)} итога, "
                "поэтому они показаны отдельно, а не свёрнуты в одну строку.")
    apply_viz(sl, b, "bar")
    sl.data = {**sl.data, "part": 2, "options": []}      # продолжение списка не переключается отдельно
    return sl


def insert_data_slides(deck: DeckContent, slides: list[ContentSlide]) -> None:
    """Слайды данных — после вступления (первый содержательный слайд после плана) и до выводов."""
    if not slides:
        return
    pos = 1
    for k, s in enumerate(deck.slides):
        if s.intent in ("title", "agenda"):
            pos = k + 1
            continue
        pos = k + 1            # первый содержательный слайд — вступление; данные сразу после него
        break
    deck.slides[pos:pos] = slides
    for i, s in enumerate(deck.slides, 1):
        s.id = f"s{i}"
    deck.target_slides = len(deck.slides)


def planner_note(insights: list[Insight]) -> str:
    """Указание сценаристу: слайды с данными добавит система — ему вступление, выводы и рекомендации."""
    names = "; ".join(f"Д{i} «{x.dataset}» ({x.nature_ru})" for i, x in enumerate(insights, 1))
    return ("\n\nСЛАЙДЫ С ДАННЫМИ ДОБАВИТ СИСТЕМА — по одному на датасет, сразу после вступления: " + names + ".\n"
            "Ты делаешь только: титул; план (один из пунктов — «Анализ данных»); вступление — контекст и вопросы, "
            "на которые отвечают данные; 1–2 слайда выводов и рекомендаций, опираясь на РЕЗУЛЬТАТЫ АНАЛИЗА ДАННЫХ "
            "(цифры — только оттуда); финал. Не делай слайдов chart, table и stats по этим датасетам.\n\n"
            + facts_text(insights))


def save(insights: list[Insight], path: Path) -> None:
    path.write_text(json.dumps([x.as_dict() for x in insights], ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def table_card(t, ins: Insight | None) -> dict:
    """Карточка датасета для формы: размер, профиль, задача и предлагаемая визуализация — или причина отказа."""
    from .analyze import unreadable_reason
    card = {"name": t.name, "rows": int(t.df.shape[0]), "cols": int(t.df.shape[1])}
    if ins is None:
        return {**card, "nature": "не распознано", "status": "error",
                "reason": unreadable_reason(t) or "не удалось определить, что показывать: нет метрик и измерений"}
    p = ins.profile
    opt = ins.options[0] if ins.options else {}
    return {**card, "nature": ins.nature_ru, "status": "ok", "task": TASK_RU.get(ins.nature, ins.nature),
            "viz": opt.get("label", ""), "why": opt.get("why", ""), "dimensions": p.get("dimensions", [])[:4],
            "metrics": p.get("metrics", [])[:5], "time_axis": p.get("time_axis", ""),
            "missing": p.get("missing_share", 0), "summary": p.get("summary", ""),
            "options": [{"type": o["type"], "label": o["label"]} for o in ins.options]}


# ====================================================================== цельная история (каркас колоды по данным)
def _norm(v) -> str:
    return str(v or "").replace(" ", "").replace(" ", "").replace("−", "-").lower()


def _refs(x) -> list[str]:
    return [str(r).strip().upper().replace("D", "Д") for r in x if str(r).strip()] if isinstance(x, list) else []


def _plural_ds(n: int) -> str:
    return "датасет" if n % 10 == 1 and n % 100 != 11 else "датасета" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "датасетов"


async def data_deck(insights: list[Insight], failed: list[dict], cross: list[str], brief: Brief,
                    profile: TemplateProfile, run: SkillRun, texts: list[str] | None = None) -> DeckContent:
    """Колода по данным — детерминированный каркас, модель пишет только слова:
    титул → «Главное» (мысль и 3 цифры) → план → слайды данных в порядке сюжета → выводы → рекомендации → финал.
    Каждое число сверяется с фактами кода. Служебное — какие файлы, задачи и альтернативы, что не распознано — в
    презентацию не идёт: это видно в интерфейсе (карточки датасетов, панель «Визуализация») и в заметках спикера."""
    from .analyze import fnum
    tmax = title_capacity(profile)
    n = len(insights)
    facts = facts_text(insights)
    try:
        raw = await run.call("data_story", topic=brief.topic, audience=brief.audience or "руководители и команда",
                             purpose=brief.purpose, details=(brief.details.split("\n\nСЛАЙДЫ С ДАННЫМИ")[0] or "")[:1500],
                             title_max=tmax, n=n, facts=facts, cross="\n".join(f"  • {c}" for c in cross) or "  (нет)",
                             texts="\n\n".join(texts or [])[:4000] or "(нет)")
        st = raw if isinstance(raw, dict) else {}
    except Exception as e:
        log.warning("data_story failed: %s", e)
        st = {}
    src = _nums(facts + " " + " ".join(cross) + " " + " ".join(x.title for x in insights) + " " + " ".join(texts or []))
    src |= set(float(y) for y in range(1990, 2036))
    ok = lambda t: bool(t) and numbers_supported(str(t), src) and trend_ok(str(t), facts)          # noqa: E731
    clip = lambda t, k: str(t or "").strip().rstrip(".")[:k]            # noqa: E731
    uses_k = profile.narrative.uses_kicker
    # порядок сюжета: все датасеты по одному разу; чего модель не назвала — в конец в исходном порядке
    idx = {f"Д{i}": x for i, x in enumerate(insights, 1)}
    order = [r for r in _refs(st.get("order")) if r in idx]
    order = list(dict.fromkeys(order + [k for k in idx if k not in order]))
    ordered = [idx[k] for k in order]
    sec_raw = st.get("sections") if isinstance(st.get("sections"), dict) else {}
    sections = {str(k).upper().replace("D", "Д"): clip(v, 24) for k, v in sec_raw.items()}
    dslides = await data_slides(ordered, brief, profile, run)
    # кикер — раздел сюжета; связки — во вводную фразу слайда (если она пуста) и в заметки
    links = [x for x in (st.get("links") or []) if isinstance(x, dict) and ok(x.get("text"))]
    by_ds: dict[str, ContentSlide] = {}
    for sl in dslides:
        if sl.data.get("dataset"):
            by_ds.setdefault(sl.data["dataset"], sl)
    for key, ins in zip(order, ordered):
        sl = by_ds.get(ins.dataset)
        if sl is None:
            continue
        if uses_k and sections.get(key):
            sl.kicker = ("ДАННЫЕ · " + sections[key].upper())[:28]
        sl.section = sections.get(key, "")
        for ln in links:
            if str(ln.get("to", "")).upper().replace("D", "Д") == key:
                txt = clip(ln["text"], 160)
                causal = CAUSAL.search(txt) or STORY_CAUSAL.search(txt)
                if not sl.lead and not (sl.why or sl.then) and len(txt.split()) <= 22 and not causal:
                    sl.lead = txt + "."
                sl.notes += f"\n\nСвязь с другими данными: {txt}."
    # «Главное»: мысль и три цифры, каждая — дословно kpi одного из датасетов
    kp_all = [k for x in insights for k in x.kpis]
    keys: list[Item] = []
    for h in (st.get("key_numbers") or [])[:3]:
        if not isinstance(h, dict):
            continue
        m = next((k for k in kp_all if _norm(k["value"]) == _norm(h.get("value"))), None)
        if m is None or any(_norm(m["value"]) == _norm(it.value) for it in keys):
            continue
        head, text = clip(h.get("head"), 40), clip(h.get("text"), 90)
        if not ok(f"{head} {text}"):
            head, text = m["head"], m["text"]
        keys.append(Item(value=m["value"], head=head or m["head"], text=text or m["text"]))
    for x in ordered:
        if len(keys) >= 3:
            break
        k = x.kpis[0] if x.kpis else None
        if k and all(_norm(k["value"]) != _norm(it.value) for it in keys):
            keys.append(Item(value=k["value"], head=k["head"], text=k["text"]))
    main = clip(st.get("main"), tmax + 10)
    main = main if ok(main) and not CAUSAL.search(main) and not STORY_CAUSAL.search(main) else (ordered[0].title if ordered else brief.topic)
    slides: list[ContentSlide] = [
        ContentSlide(id="t", intent="title", title=brief.topic[:120], lead=f"Анализ данных: {n} {_plural_ds(n)}"),
        ContentSlide(id="m", intent="stats", title=main, kicker="ГЛАВНОЕ" if uses_k else "", items=keys[:3],
                     why=_takeaway_text(st.get("main_why"), ok, 26), then=_takeaway_text(st.get("main_then"), ok, 22),
                     why_head=_head(st.get("main_why_head"), ok), then_head=_head(st.get("main_then_head"), ok),
                     notes="Главная мысль выступления и три цифры, на которых она держится. "
                           + " ".join(f"{it.value} — {it.head}: {it.text}." for it in keys[:3])),
    ]
    sec_names = list(dict.fromkeys((sections.get(k) or TASK_RU.get(idx[k].nature, "")).strip() for k in order))
    # пункт плана — раздел и его главный вывод (заголовок первого слайда раздела), а не одно слово
    # пункт плана — не одно слово, а смысл раздела: номер, вывод и что из него следует
    first: dict[str, ContentSlide] = {}
    for k in order:
        sec = (sections.get(k) or TASK_RU.get(idx[k].nature, "")).strip()
        sl = by_ds.get(idx[k].dataset)
        if sec and sec not in first and sl is not None:
            first[sec] = sl

    def point(sl: Optional[ContentSlide]) -> str:
        if sl is None:
            return ""
        t = sl.title.rstrip(".")
        nxt = f" Что из этого следует: {sl.then[:1].lower() + sl.then[1:]}." if sl.then else ""
        return (t + "." + nxt) if len(t) + len(nxt) <= 150 else t + "."
    names = [x for x in sec_names if x][:5]
    # без своей нумерации: у макетов плана шаблонов номера часто уже есть («01 01 · Рост»)
    agenda = [Item(head=x[:1].upper() + x[1:].lower(), text=point(first.get(x))) for x in names]
    rec_head = clip(st.get("recommendations_title"), 90)
    agenda.append(Item(head="Выводы и решения",
                       text=(rec_head + ". " if ok(rec_head) and rec_head else "")
                       + f"{len(st.get('recommendations') or []) or 3} рекомендации по итогам анализа"))
    slides.append(ContentSlide(id="a", intent="agenda", title="План", items=agenda))
    intro = st.get("intro") if isinstance(st.get("intro"), dict) else {}
    if n <= 4 and intro:
        it = [Item(head=clip(x.get("head"), 40), text=clip(x.get("text"), 90)) for x in intro.get("items", [])
              if isinstance(x, dict) and ok(f"{x.get('head', '')} {x.get('text', '')}")][:3]
        if len(it) >= 2 and ok(intro.get("title")):
            slides.append(ContentSlide(id="i", intent="cards", title=clip(intro["title"], tmax + 10), items=it,
                                       kicker="ВОПРОСЫ" if uses_k else ""))
    slides += dslides

    def block(key: str, title: str, kicker: str, icon: str) -> Optional[ContentSlide]:
        t = clip(st.get(f"{key}_title"), tmax + 10)
        title = t if ok(t) and len(t) >= 12 and not CAUSAL.search(t) and not STORY_CAUSAL.search(t) else title
        items, notes = [], []
        for x in (st.get(key) or [])[:3]:
            txt = f"{x.get('head', '')} {x.get('text', '')}" if isinstance(x, dict) else ""
            if not txt or not ok(txt) or CAUSAL.search(txt) or STORY_CAUSAL.search(txt):
                continue
            refs = [r for r in _refs(x.get("refs")) if r in idx]
            head, body = clip(x.get("head"), 60), clip(x.get("text"), 110)
            if len(head.split()) > 5:        # длинный «заголовок» пункта — это уже текст: в карточке он не поместится
                head, body = "", clip(f"{head}: {body[:1].lower() + body[1:]}", 130)
            items.append(Item(head=head, text=body, icon=icon))
            if refs:
                notes.append(f"«{items[-1].head or items[-1].text[:40]}» — по данным: " + ", ".join(idx[r].file or idx[r].dataset for r in refs) + ".")
        if len(items) < 2:
            return None
        if title in ("Выводы", "Рекомендации"):     # заголовок модели отброшен — назовём сами пункты
            heads = [it.head.lower() for it in items if it.head]
            if len(heads) == len(items):
                lead = "Три вывода" if title == "Выводы" and len(items) == 3 else "Что делать" if title == "Рекомендации" else title
                cand = f"{lead}: " + ", ".join(heads)
                title = cand if len(cand) <= tmax + 10 else title
        return ContentSlide(id=key[:2], intent="cards", title=title, items=items, kicker=kicker if uses_k else "",
                            notes=" ".join(notes))

    concl = block("conclusions", "Выводы", "ВЫВОДЫ", "lightbulb")
    if concl is None:      # без модели — выводы из заголовков-выводов датасетов
        concl = ContentSlide(id="co", intent="cards", title="Выводы", kicker="ВЫВОДЫ" if uses_k else "",
                             items=[Item(head=TASK_RU.get(x.nature, "").capitalize(), text=x.title[:140], icon="lightbulb")
                                    for x in ordered[:3]])
    slides.append(concl)
    rec = block("recommendations", "Рекомендации", "ЧТО ДЕЛАТЬ", "target")
    if rec is not None:
        slides.append(rec)
    # как выбирались диаграммы — в заметки финального слайда данных, а не отдельной таблицей на слайде
    if dslides:
        dslides[-1].notes += "\n\nМетодика: " + " ".join(f"{x.file or x.dataset}: {x.profile.get('summary', '')}. {explain(x)}"
                                                         for x in ordered)
    close = st.get("closing") if isinstance(st.get("closing"), dict) else {}
    ct = clip(close.get("title"), tmax + 10)
    slides.append(ContentSlide(id="cl", intent="closing", title=ct if ok(ct) else "Спасибо! Вопросы и обсуждение"))
    for i, s_ in enumerate(slides, 1):
        s_.id = f"s{i}"
    deck = DeckContent(title=brief.topic[:120], subtitle=slides[0].lead, author=brief.author, slides=slides,
                       facts=[f for x in insights for f in x.facts] + cross)
    deck.target_slides = len(slides)
    return deck

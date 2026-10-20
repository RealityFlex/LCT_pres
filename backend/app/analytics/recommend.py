"""Аналитическая задача и рекомендатель визуализаций (требования 2 и 3) — правила, без модели.

1. Задача выбирается по профилю датасета: природа данных даёт +3, другие выполнимые задачи — 1–2 балла,
   цель из текста («показать связь цены и продаж») — ещё +2,5 той задаче, о которой она говорит.
2. Под задачу оцениваются визуализации: число категорий и точек, число рядов, длина подписей,
   есть ли целое, объём таблицы. Выход — 2–3 варианта по убыванию балла, у каждого — объяснение.
3. build_chart(insight, type) собирает диаграмму любого варианта из одного агрегата — переключение
   визуализации не требует пересчёта, а тип не зависит ни от формата файла, ни от шаблона.
"""
from __future__ import annotations

import math
import re
from typing import Optional


import pandas as pd

from .analyze import (CAT_PREF, FREQ_RU, MEAN_NAME, PRICE_NAME, VAL_PREF, Col, DataProfile, Insight,
                      _label, fnum, fpct)

TASK_RU = {"timeseries": "динамика", "comparison": "сравнение", "shares": "структура (доли)",
           "distribution": "распределение", "relationship": "взаимосвязь", "reference": "справочные значения",
           "gaps": "качество данных"}
VIZ_RU = {"line": "линейный график", "column": "столбцы", "clustered": "сгруппированные столбцы",
          "bar": "горизонтальные полосы", "histogram": "гистограмма", "doughnut": "кольцевая диаграмма",
          "pie": "круговая диаграмма", "scatter": "диаграмма рассеяния", "stacked_column": "накопительные столбцы",
          "stacked_bar": "накопительная полоса 100%", "table": "таблица", "kpi": "карточки с ключевыми цифрами"}

GOAL_WORDS = {
    "timeseries": r"(рост|раст[её]т|динамик|тренд|измен\w* во времени|сезон|по месяцам|по годам|по кварталам|за период|growth|trend)",
    "comparison": r"(сравн|лидер|рейтинг|лучш|худш|\bтоп\b|отста|по регионам|по городам|по филиалам|compare|rank)",
    "shares": r"(дол[яиюейя]|структур|из чего|состав|вклад|share|\bmix\b)",
    "distribution": r"(распредел|типичн|разброс|медиан|диапазон|выброс|outlier|distribution)",
    "relationship": r"(связ|зависим|влия|коррел|чем больше|чем выше|чем ниже|relation|correl)",
    "gaps": r"(пропуск|полнот|качеств\w* данных|заполнен)",
}
TABLE_ROWS = 7          # таблица на слайде — не больше 7 строк (иначе её не прочитать из зала)
TABLE_WORDS = re.compile(r"(таблиц|точн\w* значени|перечень|список|table)", re.I)


# ------------------------------------------------------------------ цель
def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zа-яё]+", text.lower()) if len(w) >= 3]


def _close(a: str, b: str) -> bool:
    """Одно слово в разных формах: «цена» ~ «цены», «продажи» ~ «продаж»."""
    k = min(len(a), len(b))
    p = 0
    while p < k and a[p] == b[p]:
        p += 1
    # общая основа и короткие окончания: «цена» ~ «цены», но «цена» ≠ «центры» (после «цен» — «тры»)
    return p >= 5 or (p >= 3 and p >= k - 1 and len(a) - p <= 2 and len(b) - p <= 2)


def goal_for(text: str, name: str, columns: list[str]) -> str:
    """Предложения брифа, которые говорят об этом датасете (о его колонках или файле)."""
    if not text:
        return ""
    keys = _words(" ".join(columns) + " " + re.sub(r"\.\w+$", "", name).replace("_", " "))
    out = []
    for sent in re.split(r"(?<=[.!?;\n])\s*", text):
        ws = _words(sent)
        if ws and any(_close(w, k) for w in ws for k in keys):
            out.append(sent.strip())
    return " ".join(out)[:600]


def goal_score(sent: str, name: str, columns: list[str], metrics: list[str]) -> float:
    """Насколько фраза говорит об этом датасете: совпавшие слова колонок (метрика — вдвое весомее) и имени файла."""
    ws = _words(sent)
    if not ws:
        return 0.0
    sc = 0.0
    for w in dict.fromkeys(ws):            # каждое слово фразы — один раз, по лучшей совпавшей колонке
        best = 0.0
        for c in columns:
            if any(_close(w, k) for k in _words(c)):
                best = max(best, 2.0 if c in metrics else 1.0)
        sc += best
    if any(_close(w, k) for w in ws for k in _words(re.sub(r"\.\w+$", "", name).replace("_", " "))):
        sc += 1.0
    return sc


def assign_goals(text: str, tables: list[tuple[str, list[str], list[str]]]) -> dict[str, str]:
    """Каждая фраза брифа — тем датасетам, которые совпадают с ней сильнее всего. tables: (имя, колонки, метрики)."""
    out: dict[str, list[str]] = {}
    for sent in re.split(r"(?<=[.!?;\n])\s*", text or ""):
        sent = sent.strip()
        if not sent:
            continue
        scores = {name: goal_score(sent, name, cols, mets) for name, cols, mets in tables}
        best = max(scores.values(), default=0)
        if best <= 0:
            continue
        for name, sc in scores.items():
            if sc == best:
                out.setdefault(name, []).append(sent)
    return {k: " ".join(v)[:600] for k, v in out.items()}


def goal_tasks(goal: str) -> list[str]:
    return [t for t, rx in GOAL_WORDS.items() if goal and re.search(rx, goal, re.I)]


def _mentioned(goal: str, cols: list[Col]) -> list[Col]:
    ws = _words(goal)
    return [c for c in cols if ws and any(_close(w, k) for w in ws for k in _words(c.name))]


# ------------------------------------------------------------------ задача
def _metrics(prof: DataProfile, cols: list[Col]) -> list[Col]:
    names = set(prof.metrics)
    return [c for c in cols if c.name in names]


def _best_pair(df: pd.DataFrame, mets: list[Col], goal: str) -> Optional[tuple[Col, Col, float]]:
    pinned = _mentioned(goal, mets)
    best = None
    for i, a in enumerate(mets):
        for b in mets[i + 1:]:
            d = df[[a.name, b.name]].dropna()
            if len(d) < 8 or not d[a.name].std() or not d[b.name].std():
                continue
            r = float(d[a.name].astype(float).corr(d[b.name].astype(float)))
            if math.isnan(r):
                continue
            pri = sum(c in pinned for c in (a, b))
            if best is None or (pri, abs(r)) > (best[3], abs(best[2])):
                best = (a, b, r, pri)
    if best is None:
        return None
    a, b, r, _ = best
    # X — «рычаг» (цена, скидка, бюджет), Y — результат (продажи, выручка)
    if (VAL_PREF.search(a.name) and not PRICE_NAME.search(a.name)) or (PRICE_NAME.search(b.name) and not PRICE_NAME.search(a.name)):
        a, b = b, a
    # цель «как X влияет на Y» задаёт направление явно
    m = re.search(r"как\s+(\w+)\s+влия\w*\s+на\s+(\w+)", goal or "", re.I)
    if m:
        cause = m.group(1).lower()
        if any(_close(cause, k) for k in _words(b.name)) and not any(_close(cause, k) for k in _words(a.name)):
            a, b = b, a
    return a, b, r


def choose_tasks(df: pd.DataFrame, cols: list[Col], prof: DataProfile, nature: str, arg: dict, goal: str,
                 name: str = "") -> list[dict]:
    """Все выполнимые задачи с баллами и объяснением, по убыванию. Первая — та, что ляжет на слайд."""
    n = len(df)
    use = [c for c in cols if c.kind != "id"]
    mets = _metrics(prof, use)
    nums = [c for c in use if c.kind == "num"]
    dates = [c for c in use if c.kind == "date"]
    cats = [c for c in use if c.kind == "cat" and 2 <= c.unique <= 60]
    pinned = _mentioned(goal, nums)
    out: dict[str, dict] = {}

    def add(task, score, why, a):
        out[task] = {"task": task, "score": score, "why": why, "arg": a}

    if dates and nums and n >= 3:
        add("timeseries", 1.5, f"есть ось времени «{_label(dates[0].name)}» и метрика", {"dcol": dates[0]})
    if cats and nums:
        ccol = next((c for c in cats if CAT_PREF.search(c.name)), cats[0])
        vcol = (pinned or [None])[0] or next((c for c in nums if VAL_PREF.search(c.name)), nums[0])
        add("comparison", 1.5, f"измерение «{_label(ccol.name)}» ({ccol.unique} значений) и метрика «{_label(vcol.name)}»",
            {"ccol": ccol, "vcol": vcol})
        small = [c for c in cats if c.unique <= 12]
        # доля — это колонка «доля/share» или проценты, которые в сумме дают 100 (маржа в % — не доля)
        share = next((c for c in nums if re.search(r"(дол[яи]|share)", c.name, re.I)
                      or (c.pct and 98 <= float(df[c.name].sum()) <= 102)), None)
        if small and (share or not MEAN_NAME.search(vcol.name)):
            sc = small[0] if ccol not in small else ccol
            add("shares", 2.0 if share else 1.5 if sc.unique <= 6 else 0.8,
                f"«{_label((share or vcol).name)}» {'— это доли' if share else 'складывается в итог'} по «{_label(sc.name)}» ({sc.unique} значений)",
                {"ccol": sc, "vcol": share or vcol})
    if mets and n >= 30:
        vcol = (pinned or [None])[0] or next((c for c in mets if VAL_PREF.search(c.name)), mets[0])
        add("distribution", 1.2 if n >= 50 else 0.8, f"{fnum(n, 0)} значений метрики «{_label(vcol.name)}»", {"vcol": vcol})
    if len(mets) >= 2 and n >= 8:
        pair = _best_pair(df, mets, goal)
        if pair:
            a, b, r = pair
            add("relationship", 2.0 if abs(r) >= 0.4 else 1.0,
                f"две метрики «{_label(a.name)}» и «{_label(b.name)}», корреляция {fnum(r, 2)}", {"a": a, "b": b})
    if n >= 200:
        add("reference", 1.0, f"{fnum(n, 0)} строк — справочник, на слайд идёт агрегат", {})
    if max((c.missing for c in use), default=0) >= 0.1:
        add("gaps", 1.0, "в колонках есть пропуски", {})
    # природа данных
    base_why = {"timeseries": "значения упорядочены во времени", "comparison": "категории с одной метрикой",
                "shares": "значения — части одного целого", "distribution": "много значений одной метрики",
                "reference": "большая таблица позиций", "gaps": "пропуски мешают выводам — сначала полнота данных"}
    # справочник — природа «по умолчанию» (нет очевидной задачи): даёт меньше, чем явная природа
    bonus = 2.0 if nature == "reference" else 3.0
    if nature in out:
        out[nature]["score"] += bonus
        out[nature]["why"] = base_why.get(nature, "") + "; " + out[nature]["why"]
        out[nature]["arg"] = arg or out[nature]["arg"]
    else:
        add(nature, bonus, base_why.get(nature, "природа данных"), arg)
    # цель из брифа или карточки датасета
    for task in goal_tasks(goal):
        if task in out:
            out[task]["score"] += 3.5
            out[task]["why"] += f"; так сформулирована цель: «{goal[:80]}»"
    order = list(TASK_RU)
    return sorted(out.values(), key=lambda x: (-x["score"], order.index(x["task"]) if x["task"] in order else 9))


# ------------------------------------------------------------------ визуализации
def _opt(typ: str, score: float, why: str) -> dict:
    return {"type": typ, "label": VIZ_RU.get(typ, typ), "score": round(score, 2), "why": why}


def recommend(ins: Insight, goal: str = "") -> list[dict]:
    """2–3 варианта визуализации для задачи датасета; у первого — ещё и почему не подошли остальные типы."""
    a = ins.agg
    task = ins.nature
    cats = [str(c) for c in a.get("categories", [])]
    n = len(cats)
    series = a.get("series", [])
    k = len(series) + len(a.get("extra_series", []))
    maxlen = max((len(c) for c in cats), default=0)
    longl = maxlen > 10
    whole = bool(a.get("whole"))
    opts: list[dict] = []
    rejected: list[str] = []
    if task == "timeseries":
        fr = FREQ_RU.get(a.get("freq", ""), "периодам")
        opts.append(_opt("line", 3 + 2 * (n > 8) - 2 * (n <= 4),
                         f"{n} точек с шагом «{fr}»: линия показывает тренд" + (" и сезонность" if n >= 24 else "") +
                         (f"; {k} ряда — на одной оси" if k > 1 else "")))
        col_s = 2 + 2 * (n <= 8) + (a.get("freq") in ("Q", "Y")) - 3 * (n > 14)
        opts.append(_opt("clustered" if k > 1 else "column", col_s,
                         ("каждый период — отдельная величина, столбцы удобно сравнивать" if n <= 14 else
                          f"при {n} точках столбцы сливаются в «расчёску»") +
                         (f"; {k} ряда — рядом в каждом периоде" if k > 1 else "")))
        if k >= 3 and a.get("same_unit") and a.get("agg") == "sum":
            opts.append(_opt("stacked_column", 4.2, f"{k} ряда — части одного итога: накопительные столбцы показывают "
                                                    "и общий рост, и смену структуры по периодам"))
            opts[-1]["label"] = "накопительные столбцы"
        if n <= TABLE_ROWS:
            opts.append(_opt("table", 1.5, f"точные значения по {n} периодам, но тренд виден хуже"))
        opts.append(_opt("kpi", 1.2, "только ключевые цифры (изменение за период, пик) — форма ряда теряется"))
        rejected.append("круговая не подходит: периоды — не части целого")
    elif task in ("comparison", "reference"):
        opts.append(_opt("bar", 3 + 2 * (longl or n > 7) + (task == "reference"),
                         f"{n} категорий" + (f", подписи до {maxlen} символов" if longl else "") +
                         ": полосы читаются без поворота подписей, лидер — сверху"))
        col_s = 3 + (not longl and n <= 7) - 2 * (n > 12)
        opts.append(_opt("clustered" if a.get("extra_series") else "column", col_s,
                         "столбцы — привычное сравнение" + (" при коротких подписях" if not longl else
                                                            ", но длинные подписи придётся поворачивать")))
        if a.get("parts"):
            pn = ", ".join(f"«{x['name']}»" for x in a["parts"][:3])
            opts.append(_opt("stacked_bar", 4.4, f"итог складывается из {len(a['parts'])} частей ({pn}): полосы показывают "
                                                 "и размер категории, и вклад каждой части"))
            opts[-1]["label"] = "накопительные полосы"
            if not longl:
                opts.append(_opt("stacked_column", 3.2, "накопительные столбцы — то же, но при коротких подписях"))
        if whole and n <= 6:
            opts.append(_opt("doughnut", 2.5, f"значения складываются в общий итог, категорий {n} — можно показать как доли"))
        else:
            rejected.append("круговая не подходит: " + ("значения — средние, у них нет общего целого" if not whole
                                                        else f"{n} категорий — больше 6 секторов не читаются"))
        if a.get("table"):
            opts.append(_opt("table", 2.5 if task == "reference" else 1.5,
                             f"топ-{len(a['table']['rows'])} позиций таблицей — точные значения для справки"))
        elif n <= TABLE_ROWS:
            opts.append(_opt("table", 1.5 + 0.5 * (k >= 2), f"точные значения по {n} категориям"))
        else:
            rejected.append(f"таблица не подходит: {n} строк — больше {TABLE_ROWS} со слайда не читаются")
        opts.append(_opt("kpi", 1.0 + (n <= 4), "только ключевые цифры: лидер, доля, разрыв"))
        rejected.append("линия не подходит: у категорий нет порядка во времени")
    elif task == "shares":
        total = sum(series[0]["values"]) if series else 0
        opts.append(_opt("doughnut", 4 + (n <= 6),
                         f"части одного целого ({fpct(total, 0)}), {n} категорий: кольцо показывает структуру целиком"))
        opts.append(_opt("pie", 4.2 if n <= 5 else 3.6, f"классическая круговая: {n} секторов одного целого"
                                                         + (" — читается, пока секторов не больше пяти" if n > 5 else "")))
        opts.append(_opt("bar", 3.5 + (n > 6), "доли точнее сравнивать между собой: длину полосы глаз читает лучше угла"))
        opts.append(_opt("stacked_bar", 2.5, "одна полоса 100% — компактно, но мелкие доли трудно подписать"))
        if n <= TABLE_ROWS:
            opts.append(_opt("table", 1.5, "точные доли таблицей"))
        rejected.append("линия не подходит: доли не упорядочены во времени")
    elif task == "distribution":
        st = a.get("stats", {})
        opts.append(_opt("histogram", 5, f"{fnum(st.get('n', 0), 0)} значений одной метрики: гистограмма показывает форму, "
                                         "типичный диапазон и хвост"))
        opts.append(_opt("kpi", 2.5, "медиана, квартили и 90-й процентиль — компактно, но без формы распределения"))
        if n <= TABLE_ROWS:
            opts.append(_opt("table", 1.5, f"частоты по {n} интервалам таблицей"))
        rejected.append("круговая не подходит: интервалы значений — не доли целого")
        rejected.append("линия не подходит: это не динамика")
    elif task == "relationship":
        pts = len(a.get("points", {}).get("x", []))
        opts.append(_opt("scatter", 5, f"две метрики, {fnum(pts, 0)} пар значений: точки и линия тренда показывают направление, "
                                       "силу связи и выбросы"))
        opts.append(_opt("column", 3, f"средняя «{a.get('y_title', '')}» по {n} группам «{a.get('x_title', '')}» — проще читать, "
                                      "но разброс внутри групп не виден"))
        opts.append(_opt("kpi", 2, "коэффициент корреляции и наклон — без картинки"))
        rejected.append("круговая не подходит: связь двух метрик — не доли")
    elif task == "gaps":
        opts.append(_opt("bar", 5, f"полнота по {n} колонкам: полосы с долей заполненных значений, худшая колонка — сверху"))
        if n <= 8:
            opts.append(_opt("column", 2.5, "столбцы — если колонок немного и названия короткие"))
        opts.append(_opt("kpi", 2, "доля полных строк и худшая колонка — без разбивки"))
        if n <= TABLE_ROWS:
            opts.append(_opt("table", 2, "доля пропусков по колонкам таблицей"))
    if goal and TABLE_WORDS.search(goal):
        for o in opts:
            if o["type"] == "table":
                o["score"] += 3
                o["why"] += "; в цели просят точные значения"
    order = list(VIZ_RU)
    opts.sort(key=lambda o: (-o["score"], order.index(o["type"])))
    for o in opts[1:]:
        if o["score"] <= 0:
            rejected.append(f"{o['label']}: {o['why']}")
    opts = [o for o in opts if o["score"] > 0][:3] or opts[:1]
    if opts:
        opts[0]["rejected"] = rejected
    return opts


# ------------------------------------------------------------------ сборка диаграммы любого варианта
def _cell(v: float, unit: str) -> str:
    if unit == "%":
        return fpct(v)
    return fnum(v) + (f" {unit}" if unit and unit not in ("шт",) else "")


def _table(a: dict) -> dict:
    if a.get("table"):
        return a["table"]
    cats = [str(c) for c in a.get("categories", [])]
    series = a.get("series", []) + a.get("extra_series", [])
    unit = a.get("unit", "")
    cols = [a.get("x_title") or "Категория"] + [s["name"] + (f", {unit}" if unit and unit != "%" and len(series) == 1 else "")
                                                for s in series[:4]]
    rows = [[c] + [_cell(float(s["values"][i]), unit if len(series) == 1 and unit == "%" else "") for s in series[:4]]
            for i, c in enumerate(cats[:TABLE_ROWS])]
    return {"columns": cols, "rows": rows}


def build_chart(ins: Insight, typ: str) -> dict:
    """Поля ChartSpec для варианта typ (+ viz — исходное имя варианта, table — для табличного)."""
    a = ins.agg
    cats = [str(c) for c in a.get("categories", [])]
    series = [{"name": s["name"], "values": [float(v) for v in s["values"]]} for s in a.get("series", [])]
    unit = a.get("unit", "")
    nf = a.get("number_format", "")
    base = {"viz": typ, "unit": unit, "number_format": nf, "x_title": a.get("x_title", ""), "y_title": a.get("y_title", ""),
            "highlight": [], "labels": True, "gap": None, "y_min": None, "y_max": None}
    allv = [float(v) for s_ in series for v in s_["values"]]
    if unit == "%" and allv and max(allv) <= 100 and min(allv) >= 0:
        base["y_max"] = 100.0           # доли и полнота — шкала до 100%, а не до «круглых» 120%
    if typ == "table":
        return {**base, "type": "table", "categories": cats, "series": series, "table": _table(a)}
    if typ == "kpi":
        return {**base, "type": "kpi", "categories": cats, "series": series}
    if typ == "scatter":
        p = a.get("points", {})
        if p.get("y") and min(p["y"]) >= 0:
            base["y_min"] = 0.0
        return {**base, "type": "scatter", "categories": [], "series": [], "points": p, "trend": a.get("trend", []),
                "labels": False, "x_format": a.get("x_format", ""), "y_format": a.get("y_format", "")}
    hl = list(a.get("highlight", []))
    out_type = {"histogram": "column", "clustered": "column"}.get(typ, typ)
    if typ == "clustered":
        series += [{"name": s["name"], "values": [float(v) for v in s["values"]]} for s in a.get("extra_series", [])]
    if typ in ("doughnut", "pie"):
        vals = series[0]["values"] if series else []
        if a.get("kind") != "parts":           # сравнение → доли от итога, хвост — в «Прочие»
            tot = sum(vals) or 1
            vals = [v / tot * 100 for v in vals]
        if len(vals) > 6:
            cats, vals = cats[:5] + ["Прочие"], vals[:5] + [sum(vals[5:])]
        series = [{"name": "Доля", "values": [round(v, 1) for v in vals]}]
        return {**base, "type": typ, "categories": cats, "series": series, "unit": "%", "number_format": '0"%"', "labels": True}
    if typ in ("stacked_bar", "stacked_column") and a.get("parts"):
        # части итога по категориям: каждая часть — отдельный ряд
        series = [{"name": x["name"], "values": [float(v) for v in x["values"]]} for x in a["parts"]]
        if typ == "stacked_bar":
            cats = cats[::-1]
            series = [{"name": x["name"], "values": x["values"][::-1]} for x in series]
        return {**base, "type": typ, "categories": cats, "series": series, "labels": len(cats) <= 10,
                "number_format": nf or "# ##0"}
    if typ == "stacked_bar" and a.get("kind") == "parts":
        # одна полоса 100%: каждая категория — отдельный сегмент
        vals = series[0]["values"]
        return {**base, "type": "stacked_bar", "y_max": 100.0, "categories": [a.get("y_title") or "Структура"],
                "series": [{"name": c, "values": [v]} for c, v in zip(cats, vals)], "labels": True}
    if out_type in ("bar", "stacked_bar"):      # у полос PowerPoint рисует первую категорию снизу — первая должна быть сверху
        cats = cats[::-1]
        series = [{"name": s["name"], "values": s["values"][::-1]} for s in series]
    n = len(cats)
    labels = n <= (12 if typ == "histogram" else 14 if out_type == "line" else 20)
    gap = 8 if typ == "histogram" else None
    highlight = [cats.index(h) for h in hl if h in cats] if out_type in ("column", "bar") and len(series) == 1 else []
    if a.get("kind") == "points" and out_type == "column":
        highlight = []
    return {**base, "type": out_type, "categories": cats, "series": series, "labels": labels, "gap": gap, "highlight": highlight}


def explain(ins: Insight) -> str:
    """Почему так: задача, выбранная визуализация и альтернативы — в заметки и в приложение."""
    if not ins.options:
        return ""
    task = next((t for t in ins.tasks if t["task"] == ins.nature), None)
    cur = next((o for o in ins.options if o["type"] == ins.viz), ins.options[0])
    alts = [o for o in ins.options if o is not cur]
    s = f"Задача — {TASK_RU.get(ins.nature, ins.nature)}" + (f" ({task['why']})" if task else "") + ". "
    s += f"Визуализация — {cur['label']}: {cur['why']}."
    if alts:
        s += " Альтернативы: " + "; ".join(f"{o['label']} — {o['why']}" for o in alts) + "."
    rej = ins.options[0].get("rejected") or []
    if rej:
        s += " " + " ".join(r[0].upper() + r[1:] + "." for r in rej[:2])
    return s

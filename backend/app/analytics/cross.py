"""Перекрёстные факты между датасетами — только там, где совпадают ключи.

Совпадающее измерение (город в выручке и в анкете) → доли одного и того же ключа в обоих датасетах;
общая ось времени (кварталы в отчёте об открытиях и месяцы выручки) → корреляция по общим периодам.
Числа форматируются теми же fnum/fpct, что и в фактах датасетов, — сверка находит их дословно.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from .analyze import MEAN_NAME, VAL_PREF, Insight, _label, _metric_name, fnum, fpct, profile
from .ingest import Table


def _prep(t: Table):
    df, cols = profile(t.df)
    cats = [c for c in cols if c.kind == "cat" and 2 <= c.unique <= 60]
    nums = [c for c in cols if c.kind == "num"]
    dates = [c for c in cols if c.kind == "date"]
    metric = next((c for c in nums if VAL_PREF.search(c.name) and not MEAN_NAME.search(c.name)), None)
    return df, cats, nums, dates, metric


def _shares(df: pd.DataFrame, key: str, metric) -> tuple[pd.Series, str]:
    if metric is not None:
        g = df.groupby(key)[metric.name].sum()
        return g / g.sum() * 100 if g.sum() else g, f"суммы «{_metric_name(metric.name)}»"
    g = df[key].value_counts()
    return g / g.sum() * 100, "строк"


def cross_facts(items: list[tuple[Insight, Table]], limit: int = 4) -> list[str]:
    facts: list[str] = []
    prepared = [(ins, t, *_prep(t)) for ins, t in items]
    for (ia, ta, dfa, ca_, na, da, ma), (ib, tb, dfb, cb_, nb, db, mb) in combinations(prepared, 2):
        # 1) одно и то же измерение
        for ca in ca_:
            for cb in cb_:
                va, vb = set(dfa[ca.name].dropna()), set(dfb[cb.name].dropna())
                common = va & vb
                if len(common) < 3 or len(common) < 0.5 * min(len(va), len(vb)):
                    continue
                sa, wa = _shares(dfa, ca.name, ma)
                sb, wb = _shares(dfb, cb.name, mb)
                key = max(common, key=lambda k: float(sa.get(k, 0)))
                facts.append(f"{key}: {fpct(float(sa[key]))} {wa} в «{ia.dataset}» и {fpct(float(sb[key]))} {wb} в «{ib.dataset}» "
                             f"(общих значений «{_label(ca.name)}» — {len(common)})")
                # средний показатель второго датасета у лидера первого
                mean_b = next((c for c in nb if MEAN_NAME.search(c.name) or "nps" in c.name.lower()), None)
                if mean_b is not None:
                    g = dfb.groupby(cb.name)[mean_b.name].mean()
                    if key in g.index and len(g) >= 3:
                        rank = int((g > g[key]).sum()) + 1
                        facts.append(f"«{_metric_name(mean_b.name)}» в «{ib.dataset}» для «{key}» — {fnum(float(g[key]))}, "
                                     f"{rank}-е место из {len(g)}")
                break
            else:
                continue
            break
        # 2) общая ось времени — сравнение по кварталам
        if da and db and na and nb:
            def by_q(df, d, cols):
                m = next((c for c in cols if VAL_PREF.search(c.name)), cols[0])
                s = df[[d.name, m.name]].dropna()
                agg = "mean" if MEAN_NAME.search(m.name) else "sum"
                return s.groupby(s[d.name].dt.to_period("Q"))[m.name].agg(agg), m
            qa, ma_ = by_q(dfa, da[0], na)
            qb, mb_ = by_q(dfb, db[0], nb)
            # неполный квартал в агрегате месяцев не сравниваем
            months = dfa[da[0].name].dropna().dt.to_period("M").groupby(dfa[da[0].name].dropna().dt.to_period("Q")).nunique()
            if months.max() > 1:
                qa = qa[[q for q in qa.index if months.get(q, 0) == 3]]
            common = sorted(set(qa.index) & set(qb.index))
            if len(common) >= 4:
                x = np.array([float(qa[q]) for q in common])
                y = np.array([float(qb[q]) for q in common])
                if x.std() and y.std():
                    r = float(np.corrcoef(x, y)[0, 1])
                    facts.append(f"По {len(common)} общим кварталам «{_metric_name(ma_.name)}» («{ia.dataset}») и "
                                 f"«{_metric_name(mb_.name)}» («{ib.dataset}»): корреляция {fnum(r, 2)}")
        if len(facts) >= limit:
            break
    return facts[:limit]

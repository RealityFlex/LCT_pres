"""Профиль датасета, его природа и расчёты — без модели.

Природа определяет визуализацию:
  временной ряд → линия; сравнение категорий → столбцы/полосы с подсветкой лидера; доли → кольцо;
  распределение → гистограмма; справочник (200+ строк) → агрегат по категориям, а не таблица «как есть»;
  данные с пропусками → полнота по колонкам + показатель по имеющимся значениям.
Все числа, которые попадут на слайд, считаются здесь и форматируются один раз — так сверка фактов
находит их в источнике дословно.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .ingest import Table

NBSP = " "
RU_MON = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
RU_MON_FULL = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
               "ноябрь", "декабрь"]
RU_MON_GEN = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре", "октябре",
              "ноябре", "декабре"]
NATURE_RU = {"timeseries": "временной ряд", "comparison": "сравнение категорий", "shares": "доли",
             "distribution": "распределение", "relationship": "взаимосвязь показателей",
             "reference": "справочная таблица", "gaps": "данные с пропусками"}

ID_NAME = re.compile(r"(^id$|_id$|^id_|\bкод\b|артикул|\bsku\b|^номер|^№|uuid|телефон|e-?mail)", re.I)
DATE_NAME = re.compile(r"(дата|date|месяц|month|период|period|день|day|неделя|week|квартал|quarter|год|year)", re.I)
SHARE_NAME = re.compile(r"(дол[яи]|share|процент|percent|%)", re.I)
MEAN_NAME = re.compile(r"(средн|avg|mean|доля|%|процент|курс\s+(?:валют|доллар|евро|юан)|rate|температур|цена|price|рейтинг|rating|оценк|балл|nps|чек)", re.I)
CAT_PREF = re.compile(r"(категор|тип|групп|регион|город|отдел|канал|сегмент|поставщик|бренд|магазин|филиал|category|type|group|region|city)", re.I)
VAL_PREF = re.compile(r"(выручк|продаж|сумм|оборот|доход|revenue|sales|amount|объём|объем|количеств|заказ|цена|price|остат|stock)", re.I)
METRIC_PREF = re.compile(r"(nps|оценк|балл|score|рейтинг|rating|сумм|чек|трат|spend|доход)", re.I)


# ------------------------------------------------------------------ форматирование (одно на весь расчёт)
def _group(n: int) -> str:
    return f"{n:,}".replace(",", NBSP)


def _hu(v: float, d: int) -> float:
    """Округление «половина — вверх», как в PowerPoint и Excel (round() в Python округляет 46,5 до 46)."""
    from decimal import ROUND_HALF_UP, Decimal
    return float(Decimal(repr(float(v))).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def fnum(v: float, digits: Optional[int] = None) -> str:
    """12 500 · 3,4 · 1,25 млн — русская запись; одна и та же строка идёт и в факты, и на слайд."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if v < 0:
        s = fnum(-v, digits)
        return s if s.strip("0,") == "" else "−" + s       # типографский минус; «−0» не пишем
    a = abs(v)
    if a >= 1_000_000:
        d = 1 if a < 100_000_000 else 0
        return (f"{_hu(v / 1_000_000, d):.{d}f}").replace(".", ",") + f"{NBSP}млн"
    if digits is None:
        digits = 0 if a >= 100 or float(v).is_integer() else 1 if a >= 10 else 2
    if digits == 0:
        return _group(int(_hu(v, 0)))
    s = f"{_hu(v, digits):.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    ip, _, fp = s.partition(".")
    ip = _group(int(ip)) if ip not in ("-0", "") and abs(int(ip)) >= 1000 else ip
    return ip + ("," + fp if fp else "")


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def fpct(v: float, digits: int = 1, sign: bool = False) -> str:
    s = f"{_hu(abs(v), digits):.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    s = s.replace(".", ",")
    pre = ("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")
    return f"{pre}{s}%"


def _numfmt(vals: list[float]) -> str:
    """Формат подписей: целые — без «,0», крупные — с разрядами, мелкие дробные — один знак."""
    if all(float(v).is_integer() for v in vals) or max(abs(v) for v in vals) >= 20:
        return "# ##0"
    return "0.0"


# ------------------------------------------------------------------ типы колонок
def to_num(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.replace(r"[\s  ]", "", regex=True).str.replace("−", "-", regex=False)
    t = t.str.replace(r"(₽|руб\.?|р\.|\$|€|%|млн|тыс\.?)$", "", regex=True, case=False)
    t = t.str.replace(",", ".", regex=False)
    return pd.to_numeric(t.where(s.notna()), errors="coerce")


def _ru_dates(s: pd.Series) -> pd.Series:
    def one(x):
        if not isinstance(x, str):
            return None
        m = re.match(r"^\s*([а-яё]+)\.?\s+(\d{4})\s*$", x.lower())
        if not m:
            return None
        w = m.group(1)[:3]
        if w in RU_MON:
            return pd.Timestamp(int(m.group(2)), RU_MON.index(w) + 1, 1)
        return None
    return s.map(one)


def to_date(s: pd.Series, name: str = "") -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    st = s.astype(str).str.strip()
    # годы: 2019, 2020… — дата только если колонка так называется
    if st.str.fullmatch(r"(19|20)\d{2}").mean() > 0.9:
        return pd.to_datetime(st, format="%Y", errors="coerce") if DATE_NAME.search(name) else pd.Series([pd.NaT] * len(s))
    if st.str.fullmatch(r"\d+([.,]\d+)?").mean() > 0.5:
        return pd.Series([pd.NaT] * len(s))
    ru = _ru_dates(st)
    if ru.notna().mean() > 0.8:
        return pd.to_datetime(ru)
    rq = st.str.extract(r"^(I{1,3}|IV|[1-4])\s*(?:кв\.?|квартал|q)\s*(\d{2,4})\s*(?:г\.?|года?)?$", flags=re.I)
    if rq.notna().all(axis=1).mean() > 0.8:
        qn = rq[0].str.upper().map({"I": 1, "II": 2, "III": 3, "IV": 4, "1": 1, "2": 2, "3": 3, "4": 4})
        yr = rq[1].astype(float).map(lambda y: y + 2000 if y < 100 else y)
        return pd.to_datetime(yr.astype("Int64").astype(str) + "-" + ((qn - 1) * 3 + 1).astype("Int64").astype(str) + "-01",
                              errors="coerce")
    q = st.str.extract(r"^(\d{4})[-\s]?Q([1-4])$", flags=re.I)
    if q.notna().all(axis=1).mean() > 0.8:
        return pd.to_datetime(q[0] + "-" + ((q[1].astype(float) - 1) * 3 + 1).astype(int).astype(str) + "-01", errors="coerce")
    with pd.option_context("mode.chained_assignment", None):
        try:
            d = pd.to_datetime(st.where(s.notna()), errors="coerce", dayfirst=not st.str.match(r"^\d{4}-").mean() > 0.5,
                               format="mixed")
        except (TypeError, ValueError):
            d = pd.to_datetime(st.where(s.notna()), errors="coerce")
    return d


@dataclass
class Col:
    name: str
    kind: str              # date | num | cat | id | text
    missing: float         # доля пропусков 0..1
    unique: int
    pct: bool = False      # значения записаны процентами


def profile(df: pd.DataFrame) -> tuple[pd.DataFrame, list[Col]]:
    """Типизированная копия таблицы и описание колонок."""
    out = pd.DataFrame(index=df.index)
    cols = []
    n = max(1, len(df))
    for c in df.columns:
        s = df[c]
        miss = float(s.isna().mean() + (s.astype(str).str.strip() == "").where(s.notna(), False).mean())
        nonnull = s.dropna()
        num = to_num(s)
        num_ratio = num.notna().sum() / max(1, len(nonnull))
        dates = to_date(s, str(c))
        date_ratio = dates.notna().sum() / max(1, len(nonnull))
        uniq = int(nonnull.nunique())
        is_pct = bool(nonnull.astype(str).str.contains("%").mean() > 0.5) or bool(SHARE_NAME.search(str(c)))
        if ID_NAME.search(str(c)) and uniq >= 0.9 * len(nonnull):
            kind = "id"
            out[c] = s
        elif date_ratio >= 0.8 and (num_ratio < 0.8 or DATE_NAME.search(str(c))):
            kind = "date"
            out[c] = dates
        elif num_ratio >= 0.8:
            kind = "num"
            out[c] = num
            if uniq >= 0.95 * len(nonnull) and len(nonnull) > 20 and (num.dropna().diff().dropna() == 1).mean() > 0.95:
                kind = "id"
        elif uniq <= max(15, int(0.3 * n)) or (n <= 80 and float(nonnull.astype(str).str.len().median()) <= 30):
            kind = "cat"                     # короткие подписи в небольшой таблице — тоже измерение (40 городов)
            out[c] = s.astype(str).str.strip().where(s.notna())
        else:
            kind = "text"
            out[c] = s
        cols.append(Col(name=str(c), kind=kind, missing=round(miss, 4), unique=uniq, pct=is_pct))
    return out, cols


# ------------------------------------------------------------------ профиль датасета (требование 1)
FREQ_RU = {"T": "внутри дня", "D": "день", "W": "неделя", "M": "месяц", "Q": "квартал", "Y": "год", "": "нерегулярно"}
ROLE_RU = {"dimension": "измерение", "metric": "метрика", "time": "время", "id": "идентификатор", "text": "текст"}


@dataclass
class ColProfile:
    name: str
    kind: str                     # num | date | cat | text | id
    role: str                     # dimension | metric | time | id | text
    missing: float
    unique: int
    unit: str = ""
    outliers: int = 0             # за пределами 1,5 межквартильного размаха
    outlier_share: float = 0.0
    min: Optional[float] = None
    max: Optional[float] = None
    median: Optional[float] = None
    date_from: str = ""
    date_to: str = ""
    freq: str = ""                # T | D | W | M | Q | Y


@dataclass
class DataProfile:
    rows: int
    cols: int
    columns: list[ColProfile]
    dimensions: list[str]
    metrics: list[str]
    time_axis: str = ""
    hierarchies: list[list[str]] = field(default_factory=list)   # [дочернее, родительское]: город → регион
    missing_share: float = 0.0
    complete_rows: float = 1.0

    def col(self, name: str) -> Optional[ColProfile]:
        return next((c for c in self.columns if c.name == name), None)

    def summary(self) -> str:
        """Профиль одной строкой — в заметки спикера и в приложение «Данные и методика»."""
        parts = [f"{fnum(self.rows, 0)} {plural(self.rows, 'строка', 'строки', 'строк')} × {self.cols} "
                 f"{plural(self.cols, 'колонка', 'колонки', 'колонок')}"]
        if self.time_axis:
            c = self.col(self.time_axis)
            parts.append(f"время — «{_label(self.time_axis)}» ({c.date_from} — {c.date_to}, шаг: {FREQ_RU.get(c.freq, c.freq)})")
        if self.dimensions:
            parts.append("измерения: " + ", ".join(f"«{_label(d)}» ({self.col(d).unique})" for d in self.dimensions[:4]))
        if self.metrics:
            parts.append("метрики: " + ", ".join(f"«{_label(m)}»" for m in self.metrics[:5]))
        if self.hierarchies:
            parts.append("иерархия: " + "; ".join(f"{_label(a)} → {_label(b)}" for a, b in self.hierarchies[:2]))
        parts.append(f"пропуски — {fpct(self.missing_share * 100)} ячеек" if self.missing_share else "без пропусков")
        out = [c for c in self.columns if c.outliers]
        if out:
            parts.append("выбросы: " + ", ".join(f"«{_label(c.name)}» — {fnum(c.outliers, 0)} ({fpct(c.outlier_share * 100)})"
                                                for c in sorted(out, key=lambda c: -c.outliers)[:3]))
        return "; ".join(parts)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["summary"] = self.summary()
        return d


def _freq(d: pd.Series) -> str:
    d = d.dropna().sort_values()
    if len(d) < 3:
        return ""
    if (d.dt.normalize() != d).mean() > 0.3 and d.dt.normalize().nunique() < len(d):
        return "T"
    u = pd.Series(d.unique())
    step = float(u.diff().dropna().dt.days.median()) if len(u) > 2 else 0
    for f, lo, hi in (("D", 0.5, 1.5), ("W", 6, 8), ("M", 27, 32), ("Q", 85, 95), ("Y", 360, 370)):
        if lo <= step <= hi:
            return f
    return ""


def describe(df: pd.DataFrame, cols: list[Col]) -> DataProfile:
    """Профиль: типы и роли колонок, пропуски, выбросы, диапазоны, ось времени, иерархии измерений."""
    n = len(df)
    out: list[ColProfile] = []
    for c in cols:
        s = df[c.name]
        cp = ColProfile(name=c.name, kind=c.kind, role="text", missing=c.missing, unique=c.unique, unit=_unit(c.name))
        if c.kind == "num":
            x = s.dropna().astype(float)
            # годы (2019…2025) — ось или измерение, а не метрика
            year = bool(len(x)) and bool(x.between(1990, 2035).all()) and bool((x % 1 == 0).all()) and x.nunique() <= 40
            cp.role = "dimension" if year else "metric"
            if len(x):
                cp.min, cp.max, cp.median = float(x.min()), float(x.max()), float(x.median())
            if len(x) >= 8 and not year:
                q1, q3 = float(x.quantile(0.25)), float(x.quantile(0.75))
                iqr = q3 - q1
                if iqr > 0:
                    cp.outliers = int(((x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr)).sum())
                    cp.outlier_share = round(cp.outliers / len(x), 4)
        elif c.kind == "date":
            d = s.dropna()
            cp.role = "time"
            if len(d):
                cp.freq = _freq(d)
                fmt = "%m.%Y" if cp.freq in ("M", "Q") else "%Y" if cp.freq == "Y" else "%d.%m.%Y"
                cp.date_from, cp.date_to = d.min().strftime(fmt), d.max().strftime(fmt)
        elif c.kind == "cat":
            cp.role = "dimension"
        elif c.kind == "id":
            cp.role = "id"
        out.append(cp)
    dims = [c.name for c in out if c.role == "dimension"]
    mets = [c.name for c in out if c.role == "metric"]
    times = [c for c in out if c.role == "time"]
    # иерархия: каждому значению A соответствует ровно одно значение B, и у B меньше значений (город → регион)
    hier = []
    cand = [c for c in out if c.kind in ("cat", "text") and c.unique >= 2]
    for a in cand:
        for b in cand:
            if a.name == b.name or not (2 <= b.unique < a.unique) or b.unique > 30:
                continue
            pair = df[[a.name, b.name]].dropna()
            if len(pair) >= 4 and int(pair.groupby(a.name)[b.name].nunique().max()) == 1:
                hier.append([a.name, b.name])
    use = [c.name for c in cols if c.kind != "id"]
    miss = float(df[use].isna().mean().mean()) if use and n else 0.0
    complete = float(df[use].notna().all(axis=1).mean()) if use and n else 1.0
    return DataProfile(rows=n, cols=len(cols), columns=out, dimensions=dims, metrics=mets,
                       time_axis=times[0].name if times else "", hierarchies=hier[:3],
                       missing_share=round(miss, 4), complete_rows=round(complete, 4))


# ------------------------------------------------------------------ результат анализа
@dataclass
class Insight:
    dataset: str
    nature: str
    rows: int
    cols: int
    method: str                                    # что посчитал код (для заметок и сценариста)
    agg: dict = field(default_factory=dict)        # агрегат, из которого строится любая визуализация (build_chart)
    chart: dict = field(default_factory=dict)      # поля ChartSpec выбранной визуализации (+ viz, table)
    kpis: list[dict] = field(default_factory=list)  # {value, head, text} — цифры для боковой панели
    facts: list[str] = field(default_factory=list)  # проверяемые утверждения с числами
    title: str = ""                                # вывод по умолчанию (если модель не ответит)
    context: str = ""
    quality: list[str] = field(default_factory=list)
    file: str = ""                                 # исходный файл — подпись «Источник» и заметки
    profile: dict = field(default_factory=dict)    # DataProfile.as_dict()
    tasks: list[dict] = field(default_factory=list)    # аналитические задачи с баллами: {task, score, why}
    options: list[dict] = field(default_factory=list)  # 2–3 визуализации по убыванию: {type, score, why}
    viz: str = ""                                  # выбранная визуализация (первый вариант или выбор человека)

    @property
    def nature_ru(self) -> str:
        return NATURE_RU.get(self.nature, self.nature)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["nature_ru"] = self.nature_ru
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Insight":
        names = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in names})


def _pick(cols: list[Col], kind: str, pref: Optional[re.Pattern] = None, exclude: tuple = ()) -> Optional[Col]:
    cands = [c for c in cols if c.kind == kind and c.name not in exclude]
    if not cands:
        return None
    if pref is not None:
        best = [c for c in cands if pref.search(c.name)]
        if best:
            return best[0]
    return cands[0]


def _label(name: str) -> str:
    return re.sub(r"[_]+", " ", name).strip()


def _unit(name: str) -> str:
    m = re.search(r"[,(]\s*([^,()]{1,20})\)?\s*$", name)
    u = m.group(1).strip() if m and m.group(1).strip() != name.strip() else ""
    return "" if re.fullmatch(r"[\d\s–\-.]+", u) else u


def _metric_name(name: str) -> str:
    return re.sub(r"\s*[,(].*$", "", _label(name)).strip() or _label(name)


def _with_unit(v: str, unit: str) -> str:
    if not unit:
        return v
    return f"{v}{unit}" if unit in ("%", "‰") else f"{v}{NBSP}{unit}"


# ------------------------------------------------------------------ природы
def _timeseries(t: Table, df: pd.DataFrame, cols: list[Col], dcol: Col) -> Insight:
    vcol = _pick(cols, "num", VAL_PREF)
    d = df[[dcol.name, vcol.name]].dropna().sort_values(dcol.name)
    agg = "mean" if MEAN_NAME.search(vcol.name) else "sum"
    span_days = (d[dcol.name].max() - d[dcol.name].min()).days
    monthly = d[dcol.name].dt.to_period("M").nunique()
    yearly = d[dcol.name].dt.year.nunique()
    if len(d) > monthly * 1.2 and monthly >= 6:            # дни/недели → месяцы
        g = d.groupby(d[dcol.name].dt.to_period("M"))[vcol.name].agg(agg)
        idx = [p.to_timestamp() for p in g.index]
        freq = "M"
    elif monthly == len(d) and span_days > 40:
        g, idx, freq = d.set_index(dcol.name)[vcol.name], list(d[dcol.name]), "M"
    else:
        g, idx, freq = d.set_index(dcol.name)[vcol.name], list(d[dcol.name]), "Y" if yearly == len(d) else "D"
    vals = [float(x) for x in g.values]
    if freq == "M" and len(idx) >= 3 and all(i.month in (1, 4, 7, 10) for i in idx):
        freq = "Q"                                       # квартальные данные (2024-Q1…)
    roman = {1: "I", 4: "II", 7: "III", 10: "IV"}
    labels = [f"{RU_MON[i.month - 1]} {str(i.year)[2:]}" if freq == "M" else f"{roman[i.month]} кв. {str(i.year)[2:]}" if freq == "Q"
              else str(i.year) if freq == "Y" else i.strftime("%d.%m") for i in idx]
    unit = _unit(vcol.name)
    metric = _metric_name(vcol.name)
    first, last = vals[0], vals[-1]
    ch = (last - first) / abs(first) * 100 if first else 0.0
    imax = int(np.argmax(vals))
    imin = int(np.argmin(vals))
    # соседние показатели того же масштаба (открыто/закрыто) — второй и третьей линией
    series = [{"name": metric, "values": vals}]
    extra_facts = []
    if len(d) == len(vals):
        for oc in [c for c in cols if c.kind == "num" and c.name != vcol.name][:3]:
            ov = [float(x) if not pd.isna(x) else 0.0 for x in df.loc[d.index, oc.name].values]
            if max(ov) > 0 and _unit(oc.name) == unit and max(vals) / max(ov) < 8 and len(series) < 3:
                series.append({"name": _metric_name(oc.name), "values": ov})
                extra_facts.append(f"{_metric_name(oc.name)} за период — {_with_unit(fnum(sum(ov)), unit)} "
                                   f"против {_with_unit(fnum(sum(vals)), unit)} ({metric.lower()})")
    facts = [f"{metric}: {_with_unit(fnum(first), unit)} в {labels[0]} → {_with_unit(fnum(last), unit)} в {labels[-1]} ({fpct(ch, sign=True)})",
             f"Максимум — {labels[imax]}: {_with_unit(fnum(vals[imax]), unit)}; минимум — {labels[imin]}: {_with_unit(fnum(vals[imin]), unit)}"]
    facts += extra_facts
    kpis = []
    title = f"{metric}: {fpct(ch, 0, sign=True)} с {labels[0]} по {labels[-1]}"
    if freq == "M" and len(vals) >= 24:
        s = pd.Series(vals, index=pd.DatetimeIndex(idx))
        last12, prev12 = s.iloc[-12:].sum() if agg == "sum" else s.iloc[-12:].mean(), \
            s.iloc[-24:-12].sum() if agg == "sum" else s.iloc[-24:-12].mean()
        yoy = (last12 - prev12) / abs(prev12) * 100 if prev12 else 0.0
        word = "Сумма" if agg == "sum" else "Среднее"
        facts.append(f"{word} за последние 12 месяцев — {_with_unit(fnum(last12), unit)}, к предыдущим 12 месяцам {fpct(yoy, sign=True)}")
        kpis.append({"value": fpct(yoy, sign=True), "head": "год к году", "text": "последние 12 месяцев к предыдущим"})
        # темп по полным календарным годам — по нему видно, ускоряется рост или замедляется
        by_year = s.groupby(s.index.year).agg(["sum" if agg == "sum" else "mean", "count"])
        full = by_year[by_year["count"] == 12].iloc[:, 0]
        if len(full) >= 2:
            rates = [(int(y), (float(full[y]) - float(full[p])) / abs(float(full[p])) * 100) for p, y in zip(full.index[:-1], full.index[1:])]
            facts.append("По годам: " + "; ".join(f"{y} к {y - 1} — {fpct(r, sign=True)}" for y, r in rates))
            if len(rates) >= 2:
                d_ = rates[-1][1] - rates[-2][1]
                facts.append(f"Темп роста {'ускорился' if d_ > 1 else 'замедлился' if d_ < -1 else 'почти не изменился'}: "
                             f"{fpct(rates[-2][1], sign=True)} → {fpct(rates[-1][1], sign=True)}")
        # сезонность без тренда: месяц относительно среднего своего года (иначе рост ряда «делает» декабрь сильнее января)
        # (отношение к центрированной 12-месячной скользящей средней — классическое разложение ряда)
        trend = s.rolling(12, center=True, min_periods=12).mean()
        rel = (s / trend).dropna()
        seas = rel.groupby(rel.index.month).mean() * float(s.mean())
        top_m, low_m = int(seas.idxmax()), int(seas.idxmin())
        amp = (seas.max() - seas.min()) / seas.mean() * 100 if seas.mean() else 0
        facts.append(f"Сезонность: в среднем сильнее всего {RU_MON_FULL[top_m - 1]}, слабее всего {RU_MON_FULL[low_m - 1]}; "
                     f"размах сезонности {fpct(amp, 0)} от среднего месяца")
        kpis.append({"value": RU_MON_FULL[top_m - 1].capitalize(), "head": "пик сезона", "text": f"слабее всего — {RU_MON_FULL[low_m - 1]}"})
        title = f"{metric} растёт на {fpct(yoy, 0)} в год, пик — в {RU_MON_GEN[top_m - 1]}" if yoy > 0 else \
            f"{metric} снизилась на {fpct(abs(yoy), 0)} за год"
    if len(vals) >= 3:
        k = float(np.polyfit(np.arange(len(vals)), vals, 1)[0])
        step = {"M": "месяц", "Q": "квартал", "Y": "год"}.get(freq, "шаг")
        if abs(k) >= 0.005 * max(abs(v) for v in vals):
            facts.append(f"Линейный тренд: {'+' if k >= 0 else '−'}{_with_unit(fnum(abs(k)), unit)} в {step} в среднем")
    if freq != "M" or len(vals) < 24:
        tot = sum(vals)
        facts.append(f"Всего за период — {_with_unit(fnum(tot), unit)}, в среднем {_with_unit(fnum(tot / len(vals)), unit)} "
                     f"за {'квартал' if freq == 'Q' else 'год' if freq == 'Y' else 'период ряда'}")
    kpis.insert(0, {"value": fpct(ch, 0, sign=True), "head": f"{labels[0]} → {labels[-1]}", "text": f"{_with_unit(fnum(first), unit)} → {_with_unit(fnum(last), unit)}"})
    if len(kpis) < 2:
        kpis.append({"value": _with_unit(fnum(vals[imax]), unit), "head": "максимум", "text": labels[imax]})
    return Insight(dataset=t.name, nature="timeseries", rows=len(t.df), cols=t.df.shape[1],
                   method=f"ряд «{_label(vcol.name)}» по «{_label(dcol.name)}», {len(vals)} точек"
                          + (", агрегировано по месяцам" if len(d) > len(vals) else "") + f" ({'сумма' if agg == 'sum' else 'среднее'})"
                          + (f"; рядом — {', '.join(s['name'] for s in series[1:])}" if len(series) > 1 else ""),
                   agg={"kind": "time", "freq": freq, "categories": labels, "series": series, "unit": unit, "agg": agg,
                        "number_format": _numfmt([v for s in series for v in s["values"]]), "highlight": [labels[imax]],
                        "x_title": _label(dcol.name), "y_title": _label(vcol.name) if len(series) == 1 else (unit or ""),
                        "same_unit": len(series) > 1},
                   kpis=kpis[:3], facts=facts, title=title, context=t.context)


def _comparison(t: Table, df: pd.DataFrame, cols: list[Col], ccol: Col, vcol: Col) -> Insight:
    agg = "mean" if MEAN_NAME.search(vcol.name) else "sum"
    full = df.groupby(ccol.name)[vcol.name].agg(agg).dropna().sort_values(ascending=False)
    g = full
    tail_share = float(full.iloc[10:].sum() / full.sum()) if agg == "sum" and len(full) > 12 and full.sum() else 0.0
    if len(g) > 12:
        rest = g.iloc[11:].sum() if agg == "sum" else g.iloc[11:].mean()
        g = pd.concat([g.iloc[:11], pd.Series({"Прочие": rest})])
    unit = _unit(vcol.name)
    metric = _metric_name(vcol.name)
    names = [str(x) for x in g.index]
    vals = [float(x) for x in g.values]
    total = sum(vals)
    lead, lead_v = names[0], vals[0]
    real = [(n_, v_) for n_, v_ in zip(names, vals) if n_ != "Прочие"]
    tail, tail_v = real[-1] if real else (names[-1], vals[-1])
    med = float(np.median(vals))
    facts = [f"Лидер — {lead}: {_with_unit(fnum(lead_v), unit)}" + (f", {fpct(lead_v / total * 100)} от общего итога" if agg == "sum" and total else ""),
             f"Последнее место — {tail}: {_with_unit(fnum(tail_v), unit)}; разрыв с лидером в {fnum(lead_v / tail_v, 1)} раза" if tail_v else
             f"Последнее место — {tail}",
             f"Медиана по {len(vals)} категориям — {_with_unit(fnum(med), unit)}"]
    kpis = []
    if agg == "sum" and total:
        top3 = sum(vals[:3]) / total * 100
        facts.append(f"На три первых по «{_label(ccol.name)}» — {', '.join(names[:3])} — приходится {fpct(top3)} суммы")
        kpis.append({"value": fpct(lead_v / total * 100, 0), "head": lead, "text": "доля лидера в общем итоге"})
        kpis.append({"value": fpct(top3, 0), "head": "топ-3", "text": f"{', '.join(names[:3])}"[:60]})
    else:
        kpis.append({"value": _with_unit(fnum(lead_v), unit), "head": lead, "text": "лучший показатель"})
    if tail_v:
        kpis.append({"value": f"×{fnum(lead_v / tail_v, 1)}", "head": "разрыв", "text": f"{lead} против {tail}"})
    # вторая метрика той же таблицы — кто лидирует по ней
    other = [c for c in cols if c.kind == "num" and c.name != vcol.name][:2]
    for oc in other:
        oa = "mean" if MEAN_NAME.search(oc.name) else "sum"
        og = df.groupby(ccol.name)[oc.name].agg(oa).dropna()
        if len(og) >= 2:
            facts.append(f"По показателю «{_metric_name(oc.name)}» первое место — {og.idxmax()}: {_with_unit(fnum(float(og.max())), _unit(oc.name))}"
                         + (" (не совпадает с лидером по основному показателю)" if og.idxmax() != lead else ""))
    # части итога: колонки той же единицы, которые в каждой строке складываются в основную метрику
    # (выручка = у метро + ТЦ + прочие) — основа накопительных полос
    parts = []
    if agg == "sum" and unit and len(full) <= 12:
        cand = [c for c in cols if c.kind == "num" and c.name != vcol.name and _unit(c.name) == unit
                and not MEAN_NAME.search(c.name)]
        if len(cand) >= 2:
            tot, base = df[[c.name for c in cand]].sum(axis=1), df[vcol.name].astype(float)
            if float(((tot - base).abs() <= 0.02 * base.abs() + 1e-6).mean()) > 0.9:
                for c in cand:
                    pv = df.groupby(ccol.name)[c.name].sum().reindex(g.index).fillna(0)
                    parts.append({"name": _metric_name(c.name), "values": [float(v) for v in pv.values]})
                shares = [(p_["name"], sum(p_["values"]) / total * 100) for p_ in parts] if total else []
                if shares:
                    facts.append("Состав итога: " + "; ".join(f"«{n}» — {fpct(v)}" for n, v in shares))
                    lead_parts = [(p_["name"], p_["values"][0] / lead_v * 100) for p_ in parts if lead_v]
                    top_p = max(lead_parts, key=lambda x: x[1]) if lead_parts else None
                    if top_p:
                        facts.append(f"У лидера ({lead}) больше всего даёт «{top_p[0]}» — {fpct(top_p[1])} его итога")
    # вторая сопоставимая метрика (та же единица и масштаб) — для сгруппированных столбцов
    extra = []
    for oc in ([] if parts else other[:1]):
        if _unit(oc.name) == unit and unit and (MEAN_NAME.search(oc.name) is not None) == (agg == "mean"):
            ov = df.groupby(ccol.name)[oc.name].agg(agg).reindex(g.index[:len(names)]).fillna(0)
            if 0.1 < float(ov.max()) / max(vals) < 10:
                extra.append({"name": _metric_name(oc.name), "values": [float(v) for v in ov.values]})
    if tail_share:
        facts.append(f"Категорий — {len(full)}; за пределами первых 10 — {fpct(tail_share * 100)} итога")
    return Insight(dataset=t.name, nature="comparison", rows=len(t.df), cols=t.df.shape[1],
                   method=f"«{_label(vcol.name)}» по «{_label(ccol.name)}» ({'сумма' if agg == 'sum' else 'среднее'}), сортировка по убыванию"
                          + (", хвост объединён в «Прочие»" if len(full) > 12 else ""),
                   agg={"kind": "cat", "categories": names, "series": [{"name": metric, "values": vals}], "unit": unit,
                        "agg": agg, "whole": agg == "sum", "highlight": [lead], "number_format": _numfmt(vals),
                        "x_title": _label(ccol.name), "y_title": _label(vcol.name), "extra_series": extra, "parts": parts,
                        "full": {"categories": [str(x) for x in full.index[:60]], "values": [float(v) for v in full.values[:60]]}
                        if len(full) > 12 else {}, "tail_share": tail_share},
                   kpis=kpis[:3], facts=facts,
                   title=(f"{lead} — {fpct(lead_v / total * 100, 0)} итога, в {fnum(lead_v / tail_v, 1)} раза больше, чем {tail}"
                          if agg == "sum" and total and tail_v else f"{lead} впереди: {_with_unit(fnum(lead_v), unit)}"),
                   context=t.context)


def _shares(t: Table, df: pd.DataFrame, cols: list[Col], ccol: Col, vcol: Col) -> Insight:
    g = df.groupby(ccol.name)[vcol.name].sum().dropna().sort_values(ascending=False)
    total = float(g.sum())
    pct = g / total * 100 if total else g
    if len(pct) > 6:
        pct = pd.concat([pct.iloc[:5], pd.Series({"Прочие": float(pct.iloc[5:].sum())})])
    names = [str(x) for x in pct.index]
    vals = [round(float(x), 1) for x in pct.values]
    top2 = vals[0] + (vals[1] if len(vals) > 1 else 0)
    facts = [f"Крупнейшая доля — {names[0]}: {fpct(vals[0])}",
             f"Две крупнейшие категории вместе — {fpct(top2)}",
             f"Самая малая доля — {names[-1]}: {fpct(vals[-1])}"]
    hhi = sum((v / 100) ** 2 for v in vals) * 10000
    level = "высокая" if hhi > 2500 else "умеренная" if hhi > 1500 else "низкая"
    facts.append(f"Концентрация {level}: индекс Херфиндаля — {fnum(hhi, 0)}")
    if vcol.pct and abs(total - 100) > 1.5 and total > 1.5:
        facts.append(f"Сумма исходных долей — {fpct(total)}, доли нормированы к 100%")
    kpis = [{"value": fpct(vals[0], 0), "head": names[0], "text": "крупнейшая доля"},
            {"value": fpct(top2, 0), "head": "две крупнейшие", "text": "вместе"},
            {"value": str(len(g)), "head": "категорий", "text": f"концентрация {level}"}]
    return Insight(dataset=t.name, nature="shares", rows=len(t.df), cols=t.df.shape[1],
                   method=f"доли «{_label(ccol.name)}» по «{_label(vcol.name)}»" + (", мелкие объединены в «Прочие»" if len(g) > 6 else ""),
                   agg={"kind": "parts", "categories": names, "series": [{"name": "Доля", "values": vals}], "unit": "%",
                        "whole": True, "agg": "sum", "number_format": '0"%"', "highlight": [names[0]],
                        "x_title": _label(ccol.name), "y_title": "Доля, %"},
                   kpis=kpis, facts=facts, title=f"{names[0]} — {fpct(vals[0], 0)}, две крупнейшие дают {fpct(top2, 0)}",
                   context=t.context)


def _nice(step: float) -> float:
    if step <= 0:
        return 1
    e = 10 ** math.floor(math.log10(step))
    for m in (1, 2, 2.5, 5, 10):
        if step <= m * e:
            return m * e
    return 10 * e


def _distribution(t: Table, df: pd.DataFrame, cols: list[Col], vcol: Col) -> Insight:
    x = df[vcol.name].dropna().astype(float)
    unit = _unit(vcol.name)
    metric = _metric_name(vcol.name)
    q1, med, q3, p90, p99 = (float(x.quantile(q)) for q in (0.25, 0.5, 0.75, 0.9, 0.99))
    mean = float(x.mean())
    lo = float(x.min())
    step = _nice((p99 - lo) / 10)
    start = math.floor(lo / step) * step
    edges = [start + i * step for i in range(0, 12) if start + i * step < p99 + step]
    counts, labels = [], []
    for i, a in enumerate(edges):
        last = i == len(edges) - 1
        b = edges[i + 1] if not last else None
        cnt = int(((x >= a) & (x < b)).sum()) if b is not None else int((x >= a).sum())
        counts.append(cnt)
        labels.append(f"{fnum(a)}–{fnum(b)}" if b is not None else f"≥{fnum(a)}")
    while counts and counts[-1] == 0:
        counts.pop(), labels.pop()
    n = len(x)
    imode = int(np.argmax(counts))
    iqr = q3 - q1
    outl = int((x > q3 + 1.5 * iqr).sum())
    skew = float(x.skew())
    facts = [f"Медиана — {_with_unit(fnum(med), unit)}, среднее — {_with_unit(fnum(mean), unit)} (n = {fnum(n, 0)})",
             f"Половина значений — от {_with_unit(fnum(q1), unit)} до {_with_unit(fnum(q3), unit)}",
             f"Чаще всего встречается диапазон {labels[imode]}: {fpct(counts[imode] / n * 100)} значений",
             f"10% значений выше {_with_unit(fnum(p90), unit)}; выбросов выше {_with_unit(fnum(q3 + 1.5 * iqr), unit)} — {fnum(outl, 0)} ({fpct(outl / n * 100)})"]
    shape = "скошено вправо: длинный хвост крупных значений" if skew > 0.5 else "скошено влево" if skew < -0.5 else "близко к симметричному"
    facts.append(f"Распределение {shape}; среднее {'выше' if mean > med else 'ниже'} медианы на {fpct(abs(mean - med) / med * 100 if med else 0)}")
    kpis = [{"value": _with_unit(fnum(med), unit), "head": "медиана", "text": f"среднее — {_with_unit(fnum(mean), unit)}"},
            {"value": f"{fnum(q1)}–{fnum(q3)}", "head": "половина значений", "text": "межквартильный размах"},
            {"value": _with_unit(fnum(p90), unit), "head": "90-й процентиль", "text": f"выбросов — {fpct(outl / n * 100)}"}]
    return Insight(dataset=t.name, nature="distribution", rows=len(t.df), cols=t.df.shape[1],
                   method=f"гистограмма «{_label(vcol.name)}»: {len(counts)} интервалов по {fnum(step)}, хвост выше 99-го процентиля — в последнем",
                   agg={"kind": "bins", "categories": labels, "series": [{"name": "Количество", "values": [float(c) for c in counts]}],
                        "unit": "", "agg": "sum", "highlight": [labels[imode]], "number_format": "# ##0",
                        "x_title": _label(vcol.name), "y_title": "Количество значений",
                        "stats": {"median": med, "q1": q1, "q3": q3, "p90": p90, "mean": mean, "n": n, "unit": unit}},
                   kpis=kpis, facts=facts,
                   title=f"Типичное значение — {_with_unit(fnum(med), unit)}, " + ("крупные встречаются редко" if skew > 0.5 else "разброс умеренный"),
                   context=t.context)


# факторы — то, что влияет (ось X рассеяния): цена, скидка, погода, реклама, расстояние, длительность
PRICE_NAME = re.compile(r"(цен|price|стоим|тариф|скидк|discount|бюджет|расход|затрат|реклам|время|возраст|площад|температур|"
                        r"погод|осадк|расстоян|дистанц|длительн|temperature|distance)", re.I)


def _relationship(t: Table, df: pd.DataFrame, cols: list[Col], a: Col, b: Col) -> Insight:
    """Связь двух метрик: корреляция, наклон, средние по группам X; проверка внутри категорий (парадокс Симпсона)."""
    d = df[[a.name, b.name]].dropna().astype(float)
    x, y = d[a.name].to_numpy(), d[b.name].to_numpy()
    n = len(d)
    r = float(np.corrcoef(x, y)[0, 1]) if n >= 3 and x.std() and y.std() else 0.0
    rs = float(d[a.name].rank().corr(d[b.name].rank())) if n >= 3 else 0.0
    k, c0 = (float(v) for v in np.polyfit(x, y, 1)) if n >= 3 else (0.0, float(y.mean()) if n else 0.0)
    ua, ub = _unit(a.name), _unit(b.name)
    ma, mb = _metric_name(a.name), _metric_name(b.name)
    ar = abs(r)
    strength = "сильная" if ar >= 0.7 else "заметная" if ar >= 0.4 else "слабая" if ar >= 0.2 else "практически отсутствует"
    direction = "обратная" if r < 0 else "прямая"
    facts = [f"Связь «{ma}» и «{mb}»: {direction}, {strength}; коэффициент корреляции {fnum(r, 2)} (n = {fnum(n, 0)})"
             if ar >= 0.2 else f"Связи «{ma}» и «{mb}» практически нет: коэффициент корреляции {fnum(r, 2)} (n = {fnum(n, 0)})"]
    step = _nice(float(np.std(x)))
    if ar >= 0.2:
        facts.append(f"По линейной оценке +{_with_unit(fnum(step), ua)} к «{ma}» — это {'+' if k > 0 else '−'}"
                     f"{_with_unit(fnum(abs(k * step)), ub)} к «{mb}» в среднем")
    if abs(rs - r) >= 0.15:
        facts.append(f"Ранговая корреляция Спирмена — {fnum(rs, 2)}: связь {'монотонная, но нелинейная' if abs(rs) > ar else 'держится на крайних значениях'}")
    # средние Y по пяти группам X (квантили) — читаемая форма той же связи
    qs = sorted(set(float(v) for v in np.quantile(x, [0, 0.2, 0.4, 0.6, 0.8, 1.0])))
    labels, means = [], []
    for i in range(len(qs) - 1):
        lo, hi = qs[i], qs[i + 1]
        m = (x >= lo) & ((x < hi) if i < len(qs) - 2 else (x <= hi))
        if m.sum():
            labels.append(f"{fnum(lo)}–{fnum(hi)}")
            means.append(float(y[m].mean()))
    if len(means) >= 2 and means[0]:
        facts.append(f"«{mb}» в среднем: {_with_unit(fnum(means[0]), ub)} в группе с наименьшими значениями «{ma}» "
                     f"({_with_unit(labels[0], ua)}) и {_with_unit(fnum(means[-1]), ub)} — с наибольшими ({_with_unit(labels[-1], ua)})")
    # та же связь внутри групп: если внутри категорий её нет — общая корреляция обманчива
    within = None
    cat = next((c for c in cols if c.kind == "cat" and 2 <= c.unique <= 15), None)
    if cat is not None:
        rr = []
        for _, gdf in df[[cat.name, a.name, b.name]].dropna().groupby(cat.name):
            if len(gdf) >= 8 and gdf[a.name].std() and gdf[b.name].std():
                rr.append(float(gdf[a.name].astype(float).corr(gdf[b.name].astype(float))))
        if len(rr) >= 2:
            within = float(np.mean(rr))
            same = (within < 0) == (r < 0) and abs(within) >= 0.2
            facts.append(f"Внутри групп «{_label(cat.name)}» средняя корреляция {fnum(within, 2)} — "
                         + ("связь сохраняется и внутри групп" if same else "внутри групп связи почти нет: общая корреляция — эффект различий между группами"))
    kpis = [{"value": fnum(r, 2), "head": "корреляция", "text": f"{direction} связь, {strength}" if ar >= 0.2 else "связи почти нет"}]
    if ar >= 0.2:
        kpis.append({"value": f"{'+' if k > 0 else '−'}{_with_unit(fnum(abs(k * step)), ub)}", "head": f"на +{_with_unit(fnum(step), ua)}",
                     "text": f"«{mb}» по линейной оценке"})
    if within is not None:
        kpis.append({"value": fnum(within, 2), "head": "внутри групп", "text": f"средняя по «{_label(cat.name).lower()}»"})
    else:
        kpis.append({"value": fnum(n, 0), "head": "наблюдений", "text": "пар значений без пропусков"})
    step_pts = max(1, n // 400)
    pts = {"x": [float(v) for v in x[::step_pts]], "y": [float(v) for v in y[::step_pts]]}
    xs = [float(x.min()), float(x.max())]
    if y.min() >= 0 and k < 0 and c0 + k * xs[1] < 0:        # тренд не уходит ниже нуля, если значения не бывают отрицательными
        xs[1] = -c0 / k
    elif y.min() >= 0 and k > 0 and c0 + k * xs[0] < 0:
        xs[0] = -c0 / k
    word = lambda v: "ниже" if v < 0 else "выше"            # noqa: E731
    if ar >= 0.4:
        title = f"Чем выше {ma.lower()}, тем {word(r)} {mb.lower()}: корреляция {fnum(r, 2)}"
    elif within is not None and abs(within) >= 0.4:
        title = f"Внутри групп «{_label(cat.name).lower()}»: чем выше {ma.lower()}, тем {word(within)} {mb.lower()} (r = {fnum(within, 2)})"
    else:
        title = f"{ma} и {mb.lower()} связаны слабо: корреляция {fnum(r, 2)}"
    return Insight(dataset=t.name, nature="relationship", rows=len(t.df), cols=t.df.shape[1],
                   method=f"корреляция Пирсона и линейная регрессия «{_label(b.name)}» от «{_label(a.name)}», {fnum(n, 0)} пар; "
                          "средние по пяти квантильным группам",
                   agg={"kind": "points", "points": pts, "trend": [[xs[0], c0 + k * xs[0]], [xs[1], c0 + k * xs[1]]],
                        "r": r, "categories": labels, "series": [{"name": f"{mb}, среднее", "values": means}],
                        "unit": ub, "agg": "mean", "number_format": _numfmt(means), "highlight": [],
                        "x_title": _label(a.name), "y_title": _label(b.name),
                        "x_format": _numfmt(pts["x"]), "y_format": _numfmt(pts["y"])},
                   kpis=kpis[:3], facts=facts, title=title, context=t.context,
                   quality=["корреляция не доказывает причинность"])


def _reference(t: Table, df: pd.DataFrame, cols: list[Col]) -> Insight:
    cats = [c for c in cols if c.kind == "cat" and 2 <= c.unique <= 15]
    ccol = next((c for c in cats if CAT_PREF.search(c.name)), cats[0] if cats else None)
    nums = [c for c in cols if c.kind == "num"]
    vcol = next((c for c in nums if VAL_PREF.search(c.name)), nums[0] if nums else None)
    n = len(df)
    facts = [f"Справочник: {fnum(n, 0)} строк и {t.df.shape[1]} колонок"]
    kpis = [{"value": fnum(n, 0), "head": "записей", "text": f"{t.df.shape[1]} полей"}]
    chart: dict = {}
    title = f"{fnum(n, 0)} записей справочника"
    method = "агрегат вместо таблицы"
    if ccol is not None:
        cnt = df[ccol.name].value_counts()
        top, top_n = str(cnt.index[0]), int(cnt.iloc[0])
        facts.append(f"Записи по «{_label(ccol.name)}»: {len(cnt)} групп, больше всего — {top}: {fnum(top_n, 0)} ({fpct(top_n / n * 100)})")
        kpis.append({"value": str(len(cnt)), "head": "групп", "text": f"больше всего — {top}"})
        if vcol is not None:
            agg = "mean" if MEAN_NAME.search(vcol.name) else "sum"
            g = df.groupby(ccol.name)[vcol.name].agg(agg).dropna().sort_values(ascending=False)
            unit = _unit(vcol.name)
            metric = _metric_name(vcol.name)
            word = "средн." if agg == "mean" else "сумма"
            facts.append(f"{metric} ({word}) выше всего у группы {g.index[0]}: {_with_unit(fnum(float(g.iloc[0])), unit)}, "
                         f"ниже всего — {g.index[-1]}: {_with_unit(fnum(float(g.iloc[-1])), unit)}")
            names, vals = [str(i) for i in g.index], [float(v) for v in g.values]
            chart = {"kind": "cat", "categories": names, "series": [{"name": f"{metric}, {word}", "values": vals}], "unit": unit,
                     "agg": agg, "whole": agg == "sum", "highlight": [names[0]], "number_format": _numfmt(vals),
                     "x_title": _label(ccol.name), "y_title": f"{_label(vcol.name)} ({'среднее' if agg == 'mean' else 'сумма'})"}
            ratio = float(g.iloc[0] / g.iloc[-1]) if float(g.iloc[-1]) else 0
            kpis.append({"value": f"×{fnum(ratio, 1)}" if ratio else _with_unit(fnum(float(g.iloc[0])), unit),
                         "head": f"{g.index[0]} / {g.index[-1]}", "text": f"разброс «{metric.lower()}» между группами"})
            title = f"{metric} у группы «{g.index[0]}» в {fnum(ratio, 1)} раза выше, чем у «{g.index[-1]}»" if ratio else title
            method = f"{len(cnt)} групп «{_label(ccol.name)}»: {('среднее' if agg == 'mean' else 'сумма')} «{_label(vcol.name)}» по группе"
        else:
            names, vals = [str(i) for i in cnt.index], [float(v) for v in cnt.values]
            chart = {"kind": "cat", "categories": names, "series": [{"name": "Записей", "values": vals}], "unit": "",
                     "agg": "sum", "whole": True, "highlight": [names[0]], "number_format": "# ##0",
                     "x_title": _label(ccol.name), "y_title": "Записей"}
    for c in nums:
        if re.search(r"(остат|stock|налич)", c.name, re.I):
            zero = int((df[c.name].fillna(0) <= 0).sum())
            if zero:
                facts.append(f"Нулевой «{_metric_name(c.name)}» у {fnum(zero, 0)} позиций ({fpct(zero / n * 100)})")
    if len(nums) >= 2:
        cm = df[[c.name for c in nums]].corr(numeric_only=True)
        best = None
        for i, a in enumerate(nums):
            for b in nums[i + 1:]:
                r = cm.loc[a.name, b.name]
                if not math.isnan(r) and abs(r) >= 0.5 and (best is None or abs(r) > abs(best[2])):
                    best = (a, b, r)
        if best:
            facts.append(f"Связь «{_metric_name(best[0].name)}» и «{_metric_name(best[1].name)}»: корреляция {fnum(best[2], 2)}")
    kpis = kpis[2:] + kpis[:2] if len(kpis) == 3 else kpis
    # топ-позиций для варианта «таблица»: первые строки по основному показателю
    if vcol is not None:
        show = [c.name for c in cols if c.kind in ("text", "cat")][:2] + [vcol.name]
        top = df.sort_values(vcol.name, ascending=False).head(7)[show]
        chart["table"] = {"columns": [_label(c) for c in show],
                          "rows": [[fnum(float(v)) if c == vcol.name else str(v) for c, v in zip(show, r)] for r in top.values]}
    return Insight(dataset=t.name, nature="reference", rows=n, cols=t.df.shape[1], method=method, agg=chart,
                   kpis=kpis[:3], facts=facts, title=title, context=t.context)


def _gaps(t: Table, df: pd.DataFrame, cols: list[Col]) -> Insight:
    n = len(df)
    use = [c for c in cols if c.kind != "id"]
    miss = {c.name: c.missing for c in use}
    complete_rows = float(df[[c.name for c in use]].notna().all(axis=1).mean() * 100)
    order = sorted(use, key=lambda c: -c.missing)
    worst = order[0]
    names = [_label(c.name) for c in order]
    fill = [round((1 - c.missing) * 100, 1) for c in order]
    total_cells = n * len(use)
    missing_cells = int(sum(c.missing for c in use) * n)
    facts = [f"Полностью заполнены {fpct(complete_rows)} строк из {fnum(n, 0)}",
             f"Больше всего пропусков в «{_label(worst.name)}» — {fpct(worst.missing * 100)}",
             f"Пропущено {fnum(missing_cells, 0)} значений из {fnum(total_cells, 0)} ({fpct(missing_cells / total_cells * 100)})",
             "Пропуски не заполнялись: показатели посчитаны только по имеющимся значениям"]
    kpis = [{"value": fpct(complete_rows, 0), "head": "строк без пропусков", "text": f"из {fnum(n, 0)}"},
            {"value": fpct(worst.missing * 100, 0), "head": _label(worst.name), "text": "больше всего пропусков"}]
    metric = next((c for c in use if c.kind == "num" and METRIC_PREF.search(c.name)), next((c for c in use if c.kind == "num"), None))
    if metric is not None:
        x = df[metric.name].dropna()
        unit = _unit(metric.name)
        facts.append(f"«{_metric_name(metric.name)}» по {fnum(len(x), 0)} заполненным значениям: среднее {_with_unit(fnum(float(x.mean())), unit)}, "
                     f"медиана {_with_unit(fnum(float(x.median())), unit)}")
        kpis.append({"value": _with_unit(fnum(float(x.mean())), unit), "head": _metric_name(metric.name),
                     "text": f"среднее по {fnum(len(x), 0)} ответам"})
        cat = next((c for c in use if c.kind == "cat" and 2 <= c.unique <= 12), None)
        if cat is not None:
            g = df.groupby(cat.name)[metric.name].mean().dropna().sort_values(ascending=False)
            if len(g) >= 2:
                facts.append(f"По «{_label(cat.name)}»: выше всего у {g.index[0]} — {fnum(float(g.iloc[0]))}, ниже всего у {g.index[-1]} — {fnum(float(g.iloc[-1]))}")
        # смещение: отличается ли показатель у строк с пропусками в других полях
        other = df[[c.name for c in use if c.name != metric.name]].isna().any(axis=1)
        if other.any() and (~other).any():
            a, b = df.loc[other, metric.name].dropna(), df.loc[~other, metric.name].dropna()
            if len(a) >= 10 and len(b) >= 10 and b.mean():
                diff = (a.mean() - b.mean()) / abs(b.mean()) * 100
                facts.append(f"У строк с пропусками в других полях «{_metric_name(metric.name)}» "
                             f"{'выше' if diff > 0 else 'ниже'} на {fpct(abs(diff))} — "
                             + ("пропуски, скорее всего, случайны" if abs(diff) < 5 else "пропуски не случайны, выводы стоит проверить"))
    return Insight(dataset=t.name, nature="gaps", rows=n, cols=t.df.shape[1],
                   method="доля заполненных значений по колонкам; основной показатель — по имеющимся значениям",
                   agg={"kind": "fill", "categories": names, "series": [{"name": "Заполнено", "values": fill}], "unit": "%",
                        "agg": "mean", "highlight": [names[0]], "number_format": '0"%"',
                        "x_title": "Колонка", "y_title": "Заполнено, % строк"},
                   kpis=kpis[:3], facts=facts,
                   title=f"Только {fpct(complete_rows, 0)} строк заполнены полностью — пропуски в «{_label(worst.name)}»",
                   context=t.context, quality=[f"пропуски: {fpct(worst.missing * 100)} в «{_label(worst.name)}»"])


def nature_of(df: pd.DataFrame, cols: list[Col]) -> tuple[str, dict]:
    n = len(df)
    use = [c for c in cols if c.kind != "id"]
    nums = [c for c in use if c.kind == "num"]
    dates = [c for c in use if c.kind == "date"]
    cats = [c for c in use if c.kind == "cat"]
    max_miss = max((c.missing for c in use), default=0)
    if use and (max_miss >= 0.1 or sum(c.missing for c in use) / len(use) >= 0.05) and n >= 20:
        return "gaps", {}
    if dates and nums and n >= 3:
        d = df[dates[0].name].dropna()
        days, months = d.dt.normalize().nunique(), d.dt.to_period("M").nunique()
        # журнал событий (чеки, заказы с временем): много строк в день и меньше полугода — это распределение
        # значений, а не динамика
        if not (len(d) / max(1, days) > 3 and months < 6):
            return "timeseries", {"dcol": dates[0]}
        vcol = next((c for c in nums if VAL_PREF.search(c.name)), nums[0])
        return "distribution", {"vcol": vcol}
    if n >= 200:
        return "reference", {}
    if cats and nums:
        ccol = next((c for c in cats if CAT_PREF.search(c.name)), cats[0])
        share = next((c for c in nums if SHARE_NAME.search(c.name) or c.pct), None)
        vcol = share or next((c for c in nums if VAL_PREF.search(c.name)), nums[0])
        s = float(df[vcol.name].sum())
        if (share is not None or 99 <= s <= 101 or 0.99 <= s <= 1.01) and df[ccol.name].nunique() <= 12:
            return "shares", {"ccol": ccol, "vcol": vcol}
        if df[ccol.name].nunique() <= 60:
            return "comparison", {"ccol": ccol, "vcol": vcol}
    if nums and n >= 50:
        vcol = next((c for c in nums if VAL_PREF.search(c.name)), nums[0])
        return "distribution", {"vcol": vcol}
    if cats and nums:
        return "comparison", {"ccol": cats[0], "vcol": nums[0]}
    return "reference", {}


def build_task(task: str, t: Table, df: pd.DataFrame, cols: list[Col], arg: dict) -> Insight:
    return {"timeseries": lambda: _timeseries(t, df, cols, arg["dcol"]),
            "comparison": lambda: _comparison(t, df, cols, arg["ccol"], arg["vcol"]),
            "shares": lambda: _shares(t, df, cols, arg["ccol"], arg["vcol"]),
            "distribution": lambda: _distribution(t, df, cols, arg["vcol"]),
            "relationship": lambda: _relationship(t, df, cols, arg["a"], arg["b"]),
            "reference": lambda: _reference(t, df, cols),
            "gaps": lambda: _gaps(t, df, cols)}[task]()


def unreadable_reason(t: Table) -> str:
    """Почему датасет нельзя проанализировать (пусто — можно)."""
    df, cols = profile(t.df)
    if len(df) < 2:
        return f"в таблице {len(df)} строк — для анализа нужно хотя бы две"
    # без чисел считать можно только повторяющиеся категории; столбец уникальных подписей — не данные
    if not any(c.kind == "num" or (c.kind == "cat" and c.unique < 0.9 * len(df)) for c in cols):
        ru = {"text": "свободный текст", "cat": "уникальные подписи", "date": "даты", "id": "идентификаторы"}
        kinds = ", ".join(sorted({ru.get(c.kind, c.kind) for c in cols})) or "нет колонок"
        return f"нет ни чисел, ни повторяющихся категорий — в колонках только {kinds}"
    return ""


def wide_to_long(t: Table) -> Table:
    """«Продукт | I кв. | II кв. | …» — периоды стоят в заголовках: разворачиваем, чтобы периоды стали осью времени."""
    df = t.df
    if df.shape[1] < 4 or df.shape[0] > 15:
        return t
    heads = pd.Series([str(c) for c in df.columns[1:]])
    dates = to_date(heads, "период")
    first = df.iloc[:, 0]
    if dates.notna().mean() < 0.8 or to_num(first).notna().mean() > 0.5:
        return t
    body = df.iloc[:, 1:].copy()
    body.index = [str(x).strip() for x in first]
    long = body.T
    long.insert(0, "Период", list(heads))
    long = long.reset_index(drop=True)
    long.columns = ["Период"] + [str(c) for c in body.index]
    return Table(name=t.name, df=long, source=t.source, context=t.context, notes=t.notes + ["развёрнута: периоды из заголовков"])


def analyze(t: Table, goal: str = "") -> Optional[Insight]:
    """Профиль → аналитическая задача (с учётом цели) → расчёт → 2–3 визуализации → выбранная диаграмма."""
    from .recommend import build_chart, choose_tasks, recommend
    t = wide_to_long(t)
    df, cols = profile(t.df)
    if unreadable_reason(t):
        return None
    prof = describe(df, cols)
    nature, arg = nature_of(df, cols)
    tasks = choose_tasks(df, cols, prof, nature, arg, goal, t.name)
    ins = None
    for tk in tasks:
        try:
            ins = build_task(tk["task"], t, df, cols, tk["arg"])
        except Exception:
            ins = None
        if ins is not None and (ins.agg.get("categories") or ins.agg.get("points")):
            break
    if ins is None:
        return None
    if t.source == "text":
        ins.method = "таблица из текста отчёта; " + ins.method
    ins.file = t.name.split(" · ")[0]
    ins.profile = prof.as_dict()
    ins.tasks = [{"task": x["task"], "score": round(x["score"], 2), "why": x["why"]} for x in tasks]
    ins.options = recommend(ins, goal)
    ins.viz = ins.options[0]["type"] if ins.options else "column"
    ins.chart = build_chart(ins, ins.viz)
    return ins


def facts_text(insights: list[Insight]) -> str:
    """Блок для брифа: посчитанные кодом факты — источник цифр для сценария и сверки."""
    lines = ["РЕЗУЛЬТАТЫ АНАЛИЗА ДАННЫХ (посчитано кодом по приложенным файлам; цифры — только отсюда)"]
    for i, ins in enumerate(insights, 1):
        lines.append(f"[Д{i}] «{ins.dataset}» — {ins.nature_ru}, {fnum(ins.rows, 0)} строк. {ins.method}.")
        for f in ins.facts:
            lines.append(f"  • {f}")
        for k in ins.kpis:
            lines.append(f"  • {k['value']} — {k['head']} ({k['text']})")
    return "\n".join(lines)

"""Аналитика данных: чтение форматов, природа датасета, расчёты и визуализация (без модели)."""
from pathlib import Path

import pytest

from app.analytics.analyze import analyze, fnum, fpct
from app.analytics.ingest import find_text_tables, load

DEMO = Path(__file__).resolve().parents[2] / "examples" / "data_demo"


def _one(name):
    tables, _ = load(name, (DEMO / name).read_bytes())
    assert tables, name
    return analyze(tables[0])


@pytest.mark.parametrize("name,nature,chart", [
    ("sales_monthly.csv", "timeseries", "line"),       # «;» и запятая в числах
    ("regions.xlsx", "comparison", "bar"),
    ("channels.json", "shares", "doughnut"),
    ("checks.csv", "distribution", "column"),          # журнал чеков с временем — не временной ряд
    ("products.xlsx", "reference", "bar"),             # 240 строк — агрегат, а не таблица
    ("survey.csv", "gaps", "bar"),
    ("report_q3.txt", "timeseries", "column"),         # таблица внутри текста, кварталы — столбцами
])
def test_nature_and_chart(name, nature, chart):
    ins = _one(name)
    assert ins.nature == nature and ins.chart["type"] == chart
    assert ins.facts and ins.kpis and ins.title


def test_timeseries_yoy_and_seasonality():
    ins = _one("sales_monthly.csv")
    text = " ".join(ins.facts)
    assert "к предыдущим 12 месяцам" in text and "Сезонность" in text
    assert "декабрь" in text and "июль" in text           # без тренда: провал — июль, а не начало года
    assert not ins.chart["labels"]                         # 36 точек — без подписей значений


def test_comparison_leader_on_top_and_highlighted():
    ins = _one("regions.xlsx")
    cats = ins.chart["categories"]
    assert cats[-1] == "Москва" and ins.chart["highlight"] == [len(cats) - 1]


def test_gaps_counts_and_worst_column():
    ins = _one("survey.csv")
    assert "Траты в месяц" in ins.facts[1] and ins.chart["categories"][-1].startswith("Траты")
    assert ins.kpis[1]["value"] == "30%"


def test_text_table_quarters():
    ins = _one("report_q3.txt")
    assert ins.chart["categories"][0] == "I кв. 24" and [s["name"] for s in ins.chart["series"]] == ["Открыто", "Закрыто"]


def test_find_text_tables_markdown_and_tabs():
    txt = "Итоги\n\n| Город | Продажи |\n|---|---|\n| A | 10 |\n| B | 20 |\n| C | 30 |\n\nКонец\n\nX\tY\n1\t2\n3\t4\n5\t6\n"
    ts = find_text_tables(txt, "t")
    assert [t.df.shape for t in ts] == [(3, 2), (3, 2)]


def test_russian_number_format():
    assert fnum(12500) == "12 500" and fnum(3.456) == "3,46" and fnum(1_250_000) == "1,3 млн" and fpct(46.5, 0) == "47%"
    assert fpct(29.8, 0) == "30%" and fpct(19.4, sign=True) == "+19,4%"

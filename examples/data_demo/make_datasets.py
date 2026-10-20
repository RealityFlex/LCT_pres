"""Демо-датасеты для проверки аналитики данных: вымышленная сеть кофеен «Зерно», 2023–2025.

7 файлов разной природы и формата:
  1. sales_monthly.csv      — временной ряд: выручка и заказы по месяцам (36 строк)
  2. regions.xlsx           — сравнение категорий: выручка по регионам, федеральным округам и форматам (9 строк)
  3. channels.json          — доли: каналы продаж (6 категорий)
  4. checks.csv             — распределение: суммы 2 000 чеков
  5. products.xlsx          — справочная таблица: 240 позиций меню (цена и продажи связаны)
  6. survey.csv             — данные с пропусками: анкета гостей, 420 ответов
  7. report_q3.txt          — текст со встроенной таблицей: открытия кофеен по кварталам
Запуск: python examples/data_demo/make_datasets.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent
rng = np.random.default_rng(2025)

# 1. временной ряд: рост ~18% в год, пик в декабре, провал в июле
months = pd.date_range("2023-01-01", "2025-12-01", freq="MS")
season = {1: 0.93, 2: 0.9, 3: 0.97, 4: 0.99, 5: 1.0, 6: 0.94, 7: 0.86, 8: 0.9, 9: 1.03, 10: 1.07, 11: 1.1, 12: 1.27}
base = 48.0 * (1.18 ** (np.arange(len(months)) / 12))
rev = [round(b * season[m.month] * rng.normal(1, 0.025), 2) for b, m in zip(base, months)]
orders = [int(r * 1e6 / rng.normal(420, 8)) for r in rev]
pd.DataFrame({"Месяц": months.strftime("%Y-%m"), "Выручка, млн ₽": [str(v).replace(".", ",") for v in rev],
              "Заказы": orders}).to_csv(OUT / "sales_monthly.csv", sep=";", index=False, encoding="utf-8-sig")

# 2. сравнение категорий
regions = ["Москва", "Санкт-Петербург", "Казань", "Екатеринбург", "Новосибирск", "Нижний Новгород", "Краснодар",
           "Самара", "Пермь"]
rev_r = [612.4, 288.9, 141.2, 133.8, 102.5, 96.3, 94.1, 71.6, 58.2]
stores = [58, 31, 14, 15, 12, 11, 10, 9, 8]
check = [452, 431, 398, 405, 382, 377, 415, 371, 366]
okrug = ["ЦФО", "СЗФО", "ПФО", "УФО", "СФО", "ПФО", "ЮФО", "ПФО", "ПФО"]
# выручка по форматам — части итога (накопительные полосы): в Москве больше ТЦ, в регионах — «у метро»
metro_share = [0.48, 0.55, 0.62, 0.6, 0.66, 0.64, 0.58, 0.67, 0.7]
mall_share = [0.37, 0.3, 0.24, 0.27, 0.2, 0.22, 0.28, 0.19, 0.17]
metro = [round(r * m, 1) for r, m in zip(rev_r, metro_share)]
mall = [round(r * m, 1) for r, m in zip(rev_r, mall_share)]
other_fmt = [round(r - a - b, 1) for r, a, b in zip(rev_r, metro, mall)]
pd.DataFrame({"Регион": regions, "Федеральный округ": okrug, "Выручка 2025, млн ₽": rev_r, "Кофеен": stores,
              "Средний чек, ₽": check, "Формат «у метро», млн ₽": metro, "Торговые центры, млн ₽": mall,
              "Прочие форматы, млн ₽": other_fmt}) \
    .to_excel(OUT / "regions.xlsx", index=False, sheet_name="Регионы")

# 3. доли
channels = [{"канал": "Касса в кофейне", "доля, %": 46.5}, {"канал": "Предзаказ в приложении", "доля, %": 21.8},
            {"канал": "Доставка агрегаторов", "доля, %": 14.2}, {"канал": "Собственная доставка", "доля, %": 8.9},
            {"канал": "Корпоративные заказы", "доля, %": 6.1}, {"канал": "Кофе с собой из автоматов", "доля, %": 2.5}]
(OUT / "channels.json").write_text(json.dumps(channels, ensure_ascii=False, indent=1), encoding="utf-8")

# 4. распределение: логнормальные чеки
amounts = np.round(rng.lognormal(mean=np.log(380), sigma=0.45, size=2000), 0)
amounts = np.clip(amounts, 120, None)
ts = pd.Timestamp("2025-09-01") + pd.to_timedelta(rng.integers(0, 30 * 24 * 60, size=2000), unit="min")
pd.DataFrame({"id_чека": np.arange(100001, 102001), "Время": ts.strftime("%Y-%m-%d %H:%M"),
              "Сумма чека, ₽": amounts.astype(int)}).to_csv(OUT / "checks.csv", index=False, encoding="utf-8")

# 5. справочник: 240 позиций меню
cats = {"Эспрессо-напитки": (190, 320), "Фильтр-кофе": (160, 260), "Чай": (150, 240), "Холодные напитки": (230, 390),
        "Выпечка": (120, 260), "Десерты": (210, 420), "Сэндвичи": (260, 480), "Зерно и дрип-пакеты": (450, 1650)}
rows = []
sku = 1000
for cat, (lo, hi) in cats.items():
    for i in range(30):
        sku += 1
        price = int(rng.uniform(lo, hi) // 10 * 10)
        margin = round(float(np.clip(rng.normal(68 if "напит" in cat.lower() or cat in ("Фильтр-кофе", "Чай") else 52, 6), 25, 85)), 1)
        rows.append({"Артикул": f"Z-{sku}", "Позиция": f"{cat.split()[0]} №{i + 1}", "Категория": cat, "Цена, ₽": price,
                     "Маржа, %": margin, # эластичность спроса: внутри категории дороже → продаётся меньше
                     "Продажи за месяц, шт": int(rng.gamma(2.2, 420 if cat != "Зерно и дрип-пакеты" else 60)
                                                 * (price / ((lo + hi) / 2)) ** -1.8),
                     "Остаток на складе, шт": int(max(0, rng.normal(120, 70))), "Рейтинг": round(float(np.clip(rng.normal(4.5, 0.25), 3.2, 5)), 1)})
pd.DataFrame(rows).to_excel(OUT / "products.xlsx", index=False, sheet_name="Меню")

# 6. анкета с пропусками
n = 420
cities = rng.choice(["Москва", "Санкт-Петербург", "Казань", "Екатеринбург", "Краснодар"], size=n, p=[0.42, 0.24, 0.12, 0.12, 0.10])
nps = np.clip(np.round(rng.normal(8.1, 1.6, n)), 0, 10)
visits = np.clip(np.round(rng.gamma(2.0, 3.0, n)), 1, 30)
age = np.clip(np.round(rng.normal(31, 9, n)), 16, 70)
spend = np.round(rng.normal(3100, 900, n), -1)
df = pd.DataFrame({"id_анкеты": np.arange(1, n + 1), "Город": cities, "Возраст": age, "Визитов в месяц": visits,
                   "Оценка NPS, 0–10": nps, "Траты в месяц, ₽": spend})
for col, p in (("Возраст", 0.18), ("Траты в месяц, ₽", 0.31), ("Визитов в месяц", 0.07), ("Оценка NPS, 0–10", 0.04)):
    df.loc[rng.random(n) < p, col] = np.nan
df.to_csv(OUT / "survey.csv", index=False, encoding="utf-8")

# 7. текст со встроенной таблицей
(OUT / "report_q3.txt").write_text("""Отчёт отдела развития сети «Зерно» по открытиям

В 2025 году сеть продолжила расширение за пределы Москвы и Санкт-Петербурга. Основной формат новых точек —
кофейни у метро площадью до 40 м²; в торговых центрах открытия заморожены из-за роста аренды.

Открытия и закрытия кофеен по кварталам:

| Квартал | Открыто | Закрыто | Инвестиции, млн ₽ |
|---------|---------|---------|-------------------|
| 2024-Q1 | 4       | 1       | 38                |
| 2024-Q2 | 6       | 0       | 55                |
| 2024-Q3 | 7       | 2       | 61                |
| 2024-Q4 | 9       | 1       | 79                |
| 2025-Q1 | 5       | 2       | 47                |
| 2025-Q2 | 8       | 1       | 72                |
| 2025-Q3 | 11      | 1       | 96                |

Закрытия связаны с окончанием договоров аренды в двух торговых центрах Москвы. На четвёртый квартал 2025 года
запланировано 12 открытий, из них 7 — в регионах.
""", encoding="utf-8")
print("готово:", sorted(p.name for p in OUT.iterdir() if p.suffix != ".py"))

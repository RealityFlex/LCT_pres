"""Демо-датасеты: вымышленная онлайн-школа программирования «Код», 2024–2025.

  signups_weekly.csv    — временной ряд по неделям (104 недели): заявки и оплаты
  courses.json          — сравнение 8 курсов: доходимость, оценка, выручка
  sources.xlsx          — структура заявок по источникам (абсолютные числа, не проценты)
  lessons.csv           — распределение: длительность 3 000 просмотров урока, мин
  catalog.xlsx          — справочник: 320 уроков (курс, длительность, просмотры, оценка)
  feedback.csv          — анкета выпускников с пропусками (280 ответов)
  report_2025.md        — текстовый отчёт со встроенной Markdown-таблицей выручки по продуктам
Запуск: python examples/data_school/make_datasets.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent
rng = np.random.default_rng(7)

# 1. недельный ряд: рост к сентябрю и январю, провал летом
weeks = pd.date_range("2024-01-01", periods=104, freq="W-MON")
season = np.array([1.25 if w.month in (1, 9) else 0.7 if w.month in (6, 7) else 1.0 for w in weeks])
signups = (180 * (1.012 ** np.arange(104)) * season * rng.normal(1, 0.06, 104)).round().astype(int)
paid = (signups * rng.normal(0.22, 0.015, 104)).round().astype(int)
pd.DataFrame({"Неделя": weeks.strftime("%d.%m.%Y"), "Заявки": signups, "Оплаты": paid}) \
    .to_csv(OUT / "signups_weekly.csv", index=False, encoding="utf-8")

# 2. сравнение курсов
courses = ["Python с нуля", "Веб-разработка", "Аналитика данных", "Java-разработчик", "Тестирование",
           "Мобильная разработка", "DevOps", "Дизайн интерфейсов"]
complete = [71.5, 58.2, 64.8, 49.3, 76.1, 44.7, 52.6, 68.9]
rating = [4.7, 4.4, 4.6, 4.2, 4.8, 4.1, 4.3, 4.6]
revenue = [48.2, 61.5, 39.8, 33.1, 18.4, 21.7, 26.3, 15.9]
(OUT / "courses.json").write_text(json.dumps(
    [{"курс": c, "доходимость, %": a, "оценка": b, "выручка 2025, млн ₽": r} for c, a, b, r in zip(courses, complete, rating, revenue)],
    ensure_ascii=False, indent=1), encoding="utf-8")

# 3. источники заявок — абсолютные числа
pd.DataFrame({"Источник": ["Контекстная реклама", "Блогеры", "Сарафанное радио", "Вебинары", "Партнёры", "SEO"],
              "Заявок за 2025": [5820, 3410, 2960, 2150, 1180, 940]}).to_excel(OUT / "sources.xlsx", index=False)

# 4. распределение длительности просмотра урока (минуты)
dur = np.clip(rng.gamma(4.2, 6.5, 3000), 2, 120).round(1)
pd.DataFrame({"id_просмотра": np.arange(1, 3001), "Длительность просмотра, мин": dur}).to_csv(OUT / "lessons.csv", index=False)

# 5. справочник уроков
rows = []
for k in range(320):
    c = courses[k % 8]
    length = int(rng.integers(8, 55))
    views = int(rng.gamma(2.5, 900) * (40 / length) ** 0.6)
    rows.append({"Урок": f"{c.split()[0]} · урок {k // 8 + 1}", "Курс": c, "Длительность, мин": length, "Просмотры": views,
                 "Оценка урока": round(float(np.clip(rng.normal(4.5, 0.3), 3, 5)), 1)})
pd.DataFrame(rows).to_excel(OUT / "catalog.xlsx", index=False, sheet_name="Уроки")

# 6. анкета выпускников с пропусками
n = 280
df = pd.DataFrame({"id": np.arange(1, n + 1), "Курс": rng.choice(courses, n),
                   "Нашли работу": rng.choice(["да", "нет", "в процессе"], n, p=[0.48, 0.22, 0.30]),
                   "Зарплата после, тыс. ₽": np.round(rng.normal(118, 35, n)),
                   "Оценка курса, 1–10": np.clip(np.round(rng.normal(8.4, 1.3, n)), 1, 10)})
for col, p in (("Зарплата после, тыс. ₽", 0.38), ("Оценка курса, 1–10", 0.06), ("Нашли работу", 0.04)):
    df.loc[rng.random(n) < p, col] = np.nan
df.to_csv(OUT / "feedback.csv", index=False)

# 7. текст с Markdown-таблицей
(OUT / "report_2025.md").write_text("""# Итоги 2025 года онлайн-школы «Код»

Школа перешла от разовых курсов к подписке: с весны 2025 года студенты платят помесячно и получают доступ ко всем
трекам. Корпоративное обучение запущено в третьем квартале.

## Выручка по продуктам, млн ₽

| Продукт | I кв. 2025 | II кв. 2025 | III кв. 2025 | IV кв. 2025 |
|---|---|---|---|---|
| Курсы | 38,2 | 33,5 | 29,8 | 27,1 |
| Подписка | 4,1 | 12,7 | 21,9 | 30,4 |
| Корпоративное обучение | 0 | 0 | 6,2 | 11,8 |

Планы на 2026 год: удвоить корпоративное направление и перевести на подписку все курсы, кроме DevOps.
""", encoding="utf-8")
print("готово:", sorted(p.name for p in OUT.iterdir() if p.suffix != ".py"))

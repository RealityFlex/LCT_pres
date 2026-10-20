"""Демо-датасеты: вымышленный городской каршеринг «Поехали», 2025 — сложные случаи.

  rides_daily.csv     — 365 дней: поездки и температура (ряд + взаимосвязь «погода → спрос»)
  districts.xlsx      — 25 районов: поездки и выручка (больше 12 категорий → разбиение на два слайда)
  fleet.json          — доли классов автомобилей в парке, %
  complaints.csv      — жалобы свободным текстом без чисел (нетипизируемый датасет → слайд-сообщение)
Запуск: python examples/data_carsharing/make_datasets.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent
rng = np.random.default_rng(11)

days = pd.date_range("2025-01-01", "2025-12-31", freq="D")
temp = np.round(5 + 13 * np.sin((days.dayofyear - 110) / 365 * 2 * np.pi) + rng.normal(0, 3.5, len(days)), 1)
weekend = np.array([1.25 if d.weekday() >= 5 else 1.0 for d in days])
rides = np.round((9000 + 210 * temp) * weekend * rng.normal(1, 0.07, len(days))).astype(int)
pd.DataFrame({"Дата": days.strftime("%Y-%m-%d"), "Поездки": rides, "Температура, °C": temp}) \
    .to_csv(OUT / "rides_daily.csv", index=False)

names = ["Центральный", "Северный", "Южный", "Западный", "Восточный", "Заречный", "Ленинский", "Октябрьский", "Советский",
         "Кировский", "Пролетарский", "Индустриальный", "Приморский", "Нагорный", "Лесной", "Садовый", "Речной",
         "Солнечный", "Новый", "Старый город", "Академический", "Вокзальный", "Парковый", "Озёрный", "Промзона"]
base = np.sort(rng.gamma(2.2, 1.0, len(names)))[::-1]
r = (base / base.sum() * 3_400_000).round().astype(int)
pd.DataFrame({"Район": names, "Поездок за год": r, "Выручка, млн ₽": np.round(r * rng.normal(410, 25, len(names)) / 1e6, 1)}) \
    .to_excel(OUT / "districts.xlsx", index=False)

(OUT / "fleet.json").write_text(json.dumps(
    [{"класс": "Эконом", "доля, %": 54.0}, {"класс": "Комфорт", "доля, %": 27.5}, {"класс": "Бизнес", "доля, %": 8.5},
     {"класс": "Электромобили", "доля, %": 6.0}, {"класс": "Грузовые", "доля, %": 4.0}], ensure_ascii=False, indent=1),
    encoding="utf-8")

texts = ["машина грязная внутри", "не открылась дверь через приложение", "долго искал парковку в зоне",
         "списали за ожидание", "нет зарядки для телефона", "приложение зависло при завершении", "пахнет сигаретами",
         "поцарапан бампер, не мой", "долго отвечала поддержка", "мало машин у метро вечером"]
pd.DataFrame({"Комментарий клиента": [texts[i % len(texts)] + f" (обращение {i + 1})" for i in range(60)]}) \
    .to_csv(OUT / "complaints.csv", index=False)
print("готово:", sorted(p.name for p in OUT.iterdir() if p.suffix != ".py"))

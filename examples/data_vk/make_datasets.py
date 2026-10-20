"""Небольшие наборы данных под задачи трёх шаблонов VK (вымышленные цифры) — для девяти колод «3 шаблона × 3 варианта».

  vk_tech/        облачная платформа: выручка по месяцам, структура выручки по сервисам, клиенты по отраслям
  vk_workspace/   корпоративный суперапп: активные пользователи по неделям, доли функций, внедрение по подразделениям
  vk_education/   образовательные программы: студенты по семестрам, баллы итогового теста, программы по вузам
Запуск: python examples/data_vk/make_datasets.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent
rng = np.random.default_rng(42)

# --- VK Tech: облако
d = OUT / "vk_tech"
d.mkdir(exist_ok=True)
months = pd.date_range("2024-01-01", periods=24, freq="MS")
rev = np.round(410 * 1.032 ** np.arange(24) * rng.normal(1, 0.025, 24), 1)
pd.DataFrame({"Месяц": months.strftime("%Y-%m"), "Выручка облака, млн ₽": rev}).to_csv(d / "cloud_revenue.csv", index=False)
(d / "services.json").write_text(json.dumps(
    [{"сервис": s, "доля выручки, %": v} for s, v in
     (("Вычисления", 38.0), ("Хранилище S3", 21.5), ("Базы данных", 16.0), ("Kubernetes", 12.5), ("ML-платформа", 7.0),
      ("Прочие", 5.0))], ensure_ascii=False, indent=1), encoding="utf-8")
pd.DataFrame({"Отрасль": ["Ритейл", "Финансы", "Госсектор", "Промышленность", "Медиа", "Логистика", "Образование", "Медицина"],
              "Клиентов": [412, 356, 298, 241, 187, 164, 121, 96]}).to_excel(d / "clients.xlsx", index=False)

# --- VK WorkSpace: корпоративные коммуникации
d = OUT / "vk_workspace"
d.mkdir(exist_ok=True)
weeks = pd.date_range("2025-01-06", periods=30, freq="W-MON")
mau = np.round(18000 * 1.025 ** np.arange(30) * rng.normal(1, 0.02, 30)).astype(int)
pd.DataFrame({"Неделя": weeks.strftime("%d.%m.%Y"), "Активные пользователи": mau}).to_csv(d / "active_users.csv", index=False)
(d / "features.json").write_text(json.dumps(
    [{"функция": f, "доля использования, %": v} for f, v in
     (("Мессенджер", 41.0), ("Видеозвонки", 24.0), ("Почта", 15.0), ("Диск", 11.0), ("Календарь", 9.0))],
    ensure_ascii=False, indent=1), encoding="utf-8")
pd.DataFrame({"Подразделение": ["Продажи", "ИТ", "Маркетинг", "Финансы", "HR", "Логистика", "Юристы"],
              "Внедрение, %": [92, 88, 81, 67, 63, 54, 41]}).to_excel(d / "adoption.xlsx", index=False)

# --- VK Education: образовательные программы
d = OUT / "vk_education"
d.mkdir(exist_ok=True)
sem = ["Осень 2022", "Весна 2023", "Осень 2023", "Весна 2024", "Осень 2024", "Весна 2025", "Осень 2025"]
pd.DataFrame({"Семестр": sem, "Студенты": [3200, 4100, 5600, 6900, 8800, 10400, 12900]}).to_csv(d / "students.csv", index=False)
scores = np.clip(np.round(rng.normal(74, 12, 1500)), 20, 100).astype(int)
pd.DataFrame({"id": np.arange(1, 1501), "Балл итогового теста": scores}).to_csv(d / "scores.csv", index=False)
pd.DataFrame({"Вуз": ["МГТУ им. Баумана", "МФТИ", "ИТМО", "СПбГУ", "НИУ ВШЭ", "УрФУ", "КФУ", "НГУ", "ТПУ"],
              "Выпускников программ": [1240, 1080, 960, 870, 820, 610, 540, 430, 380]}).to_excel(d / "universities.xlsx", index=False)
print("готово")

"""Промежуточные представления: контент-модель колоды и планы вариантов вёрстки."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

MIN_SLIDES, MAX_SLIDES = 10, 15       # целевой объём колоды по ТЗ, если пользователь не задал свой

INTENTS = ("title", "agenda", "section", "bullets", "cards", "process", "timeline", "stats", "chart",
           "table", "comparison", "quote", "image", "code", "closing")


class Brief(BaseModel):
    topic: str
    purpose: str = "проект"          # фича | продукт | проект | инициатива | обучение | другое
    audience: str = ""
    details: str = ""                # дополнительные данные (факты, цифры)
    slide_count: Optional[int] = None
    duration_min: Optional[int] = None  # длительность выступления, мин: объём колоды и заметок спикера
    author: str = ""
    language: str = "ru"
    images: str = "auto"             # auto — где уместно | on — обязательно 2–3 иллюстрации | off — без картинок
    style_id: Optional[str] = None       # встроенный стиль (без шаблона): id из каталога или auto
    style_colors: Optional[dict[str, str]] = None   # свои цвета: background/primary/secondary/auxiliary
    style_fonts: Optional[dict[str, str]] = None
    source_text: str = ""          # приложенные материалы целиком: по ним сверяются цифры
    web_search: bool = False         # найти факты в интернете (Википедия) до планирования
    datasets: list[str] = Field(default_factory=list)   # загруженные файлы с данными (data/uploads): аналитика и диаграммы
    dataset_goals: dict[str, str] = Field(default_factory=dict)   # id датасета → цель («показать связь цены и продаж»)
    brand_id: Optional[str] = None   # загруженный брендбук (data/brands/<id>): цвета, шрифты, логотип
    brand_priority: str = "brand"    # brand — брендбук важнее шаблона | template — от брендбука только логотип
    image_source: str = "auto"       # auto — фото Wikimedia Commons, если подошло, иначе Kandinsky | web | generate
    quality: str = "normal"          # normal — три колоды не дольше 5 минут | extended — без лимита: больше попыток
                                     # дизайнера, полный визуальный аудит и автоисправление замечаний оформления


class Item(BaseModel):
    head: str = ""
    text: str = ""
    value: Optional[str] = None      # число/метрика: «91%», «3,2 млн», «2026»
    icon: Optional[str] = None       # ключевое слово иконки (англ.)


class Series(BaseModel):
    name: str = ""
    values: list[float] = Field(default_factory=list)


class ChartSpec(BaseModel):
    type: Literal["bar", "column", "line", "pie", "doughnut", "scatter", "stacked_column", "stacked_bar"] = "column"
    categories: list[str] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    unit: str = ""
    title: str = ""
    number_format: str = ""            # формат подписей значений: «# ##0», «0.0», «0"%"»
    highlight: list[int] = Field(default_factory=list)   # индексы категорий, выделенных акцентом (лидер, пик)
    labels: bool = True                # подписи значений (на длинных рядах выключаются)
    gap: Optional[int] = None          # зазор между столбцами, % (гистограмма — почти без зазора)
    x_title: str = ""                  # подпись оси категорий / оси X: «Регион», «Цена, ₽»
    y_title: str = ""                  # подпись оси значений: «Выручка, млн ₽»
    points: dict[str, list[float]] = Field(default_factory=dict)   # рассеяние: {"x": [...], "y": [...]}
    trend: list[list[float]] = Field(default_factory=list)          # линия тренда: [[x0, y0], [x1, y1]]
    x_format: str = ""                 # формат чисел оси X рассеяния
    y_format: str = ""
    y_min: Optional[float] = None      # границы оси значений (проценты — до 100, продажи — от 0)
    y_max: Optional[float] = None
    viz: str = ""                      # вариант рекомендателя (histogram, clustered…), из которого собрана диаграмма


class TableSpec(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class CodeSpec(BaseModel):
    lang: str = ""                   # python | java | js | sql | … (подпись и отступы)
    text: str = ""                   # фрагмент дословно, построчно, до ~16 строк
    caption: str = ""                # «Листинг 1. Функция проверки чётности»


class Column(BaseModel):
    title: str = ""
    points: list[str] = Field(default_factory=list)


class ContentSlide(BaseModel):
    id: str
    intent: str = "bullets"
    title: str
    lead: str = ""
    kicker: str = ""
    section: str = ""
    items: list[Item] = Field(default_factory=list)
    chart: Optional[ChartSpec] = None
    table: Optional[TableSpec] = None
    columns: list[Column] = Field(default_factory=list)
    quote: str = ""
    code: Optional[CodeSpec] = None  # слайд с примером кода (intent code)
    image_prompt: str = ""
    image: Optional[str] = None      # путь к сгенерированной картинке
    image_query: str = ""            # запрос фото (англ., 1–3 слова) для Wikimedia Commons
    image_credit: str = ""           # автор и лицензия найденного фото: «Фото: Автор, CC BY-SA 4.0»
    source_note: str = ""            # «Источник: ru.wikipedia.org» — в подвал слайда с найденными цифрами
    data: dict[str, Any] = Field(default_factory=dict)   # слайд данных: датасет, задача, выбранная визуализация, варианты
    why: str = ""                    # «и что?»: почему это важно, что от этого зависит (блок под контентом)
    then: str = ""                   # что из этого следует: решение, действие или вопрос к проверке
    why_head: str = ""               # заголовок-мысль блока «почему важно» («Декабрь кормит год»), 2–4 слова
    then_head: str = ""              # заголовок-мысль блока «что следует» («Ставка на метро»), 2–4 слова
    notes: str = ""
    instruction: str = ""            # пожелание человека к слайду (план, чат); очищается после дописывания


class Source(BaseModel):
    n: int
    title: str = ""
    url: str = ""
    host: str = ""


class DeckContent(BaseModel):
    title: str
    subtitle: str = ""
    author: str = ""
    date: str = ""
    language: str = "ru"
    slides: list[ContentSlide] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)   # факты/цифры из брифа (для проверки «цифры из источника»)
    sources: list[Source] = Field(default_factory=list)   # источники из интернета, на которые опираются слайды
    target_slides: int = 0      # объём, который обязан держать каждый вариант (10–15 по ТЗ или заданный пользователем)


class SlideSpec(BaseModel):
    """Решение варианта: какой рецепт/холст применить к какому контенту."""
    slide: ContentSlide
    recipe: str
    canvas: Optional[str] = None
    tone: Literal["light", "dark", "any"] = "any"
    opts: dict[str, Any] = Field(default_factory=dict)
    alts: list[str] = Field(default_factory=list)     # запасные холсты (если на основном не влезает заголовок)


class VariantPlan(BaseModel):
    id: str
    name: str
    strategy: str
    description: str = ""
    slides: list[SlideSpec] = Field(default_factory=list)

"""Промежуточные представления: контент-модель колоды и планы вариантов вёрстки."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

INTENTS = ("title", "agenda", "section", "bullets", "cards", "process", "timeline", "stats", "chart",
           "table", "comparison", "quote", "image", "closing")


class Brief(BaseModel):
    topic: str
    purpose: str = "проект"          # фича | продукт | проект | инициатива | обучение | другое
    audience: str = ""
    details: str = ""                # дополнительные данные (факты, цифры)
    slide_count: Optional[int] = None
    author: str = ""
    language: str = "ru"


class Item(BaseModel):
    head: str = ""
    text: str = ""
    value: Optional[str] = None      # число/метрика: «91%», «3,2 млн», «2026»
    icon: Optional[str] = None       # ключевое слово иконки (англ.)


class Series(BaseModel):
    name: str = ""
    values: list[float] = Field(default_factory=list)


class ChartSpec(BaseModel):
    type: Literal["bar", "column", "line", "pie", "doughnut"] = "column"
    categories: list[str] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    unit: str = ""
    title: str = ""


class TableSpec(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


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
    image_prompt: str = ""
    image: Optional[str] = None      # путь к сгенерированной картинке
    notes: str = ""


class DeckContent(BaseModel):
    title: str
    subtitle: str = ""
    author: str = ""
    date: str = ""
    language: str = "ru"
    slides: list[ContentSlide] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)   # факты/цифры из брифа (для проверки «цифры из источника»)


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

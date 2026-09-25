"""Результат композиции слайда — список элементов в координатах слайда (EMU)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from ..parsing.model import Box


class Run(BaseModel):
    text: str
    bold: Optional[bool] = None
    color: Optional[str] = None


class P(BaseModel):
    runs: list[Run]
    bullet: bool = False
    bullet_color: Optional[str] = None
    space_after: float = 0.0          # pt
    level: int = 0

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


class El(BaseModel):
    id: str
    kind: str                         # text | card | shape | line | icon | image | chart | table
    box: Box
    role: str = ""                    # heading | body | caption | number | label | lead | quote ...
    parent: Optional[str] = None      # элемент-контейнер (карточка)
    # текст
    paras: list[P] = Field(default_factory=list)
    font: Optional[str] = None
    size: Optional[float] = None
    color: Optional[str] = None
    bold: bool = False
    caps: bool = False
    align: str = "l"
    valign: str = "t"
    line_spacing: float = 1.0
    overflow: bool = False            # текст не удалось вместить (сигнал для сокращения)
    # фигуры
    card: Optional[int] = None        # индекс CardStyle профиля
    fill: Optional[str] = None
    line: Optional[str] = None
    line_w: float = 0.0
    geom: str = "rect"
    radius: Optional[float] = None    # абсолютный радиус скругления, EMU
    arrow: bool = False
    # медиа
    icon: Optional[str] = None
    image: Optional[str] = None
    chart: Optional[dict[str, Any]] = None
    table: Optional[dict[str, Any]] = None


class SlotFill(BaseModel):
    role: str
    sid: str
    text: str
    size: Optional[float] = None
    paras: list[str] = Field(default_factory=list)
    color: Optional[str] = None
    h: Optional[int] = None           # новая высота рамки (если заголовок вырос)
    w: Optional[int] = None           # новая ширина рамки (обход логотипов)
    font: Optional[str] = None        # замена гарнитуры шаблона без кириллицы


class SlideLayout(BaseModel):
    index: int
    content_id: str
    canvas: str
    recipe: str
    slots: list[SlotFill] = Field(default_factory=list)
    remove_sids: list[str] = Field(default_factory=list)
    label_width: Optional[int] = None
    elements: list[El] = Field(default_factory=list)
    notes: str = ""
    warnings: list[str] = Field(default_factory=list)
    clone_full: bool = False          # клонировать исходный слайд целиком (паттерн шаблона)
    pattern_ops: list[dict[str, Any]] = Field(default_factory=list)
    overflows: list[dict[str, Any]] = Field(default_factory=list)   # [{text, max_chars}] — не влезло в слот паттерна

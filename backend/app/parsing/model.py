"""Модель профиля шаблона (результат декомпозиции). Сериализуется в profile.json."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Box(BaseModel):
    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def inset(self, dx: int, dy: Optional[int] = None) -> "Box":
        dy = dx if dy is None else dy
        return Box(x=self.x + dx, y=self.y + dy, w=max(1, self.w - 2 * dx), h=max(1, self.h - 2 * dy))


class TextStyle(BaseModel):
    font: str = "Arial"
    size: float = 14
    color: str = "000000"
    bold: bool = False
    caps: bool = False
    spacing: Optional[int] = None     # spc (сотые пункта)
    line_spacing: float = 1.0


class CardStyle(BaseModel):
    """Образец «карточки» из шаблона. sppr_xml — исходный spPr, копируется в новые фигуры."""
    source_slide: int
    sid: str
    geom: str = "rect"
    fill: Optional[str] = None
    line: Optional[str] = None
    sppr_xml: str
    style_xml: Optional[str] = None
    accent: bool = False
    on_dark: bool = False
    weight: float = 1.0
    radius: Optional[float] = None
    text_color: str = "000000"
    heading_color: Optional[str] = None
    marker_xml: Optional[str] = None   # маленький акцентный элемент внутри карточки (точка/иконка-подложка)
    marker_box: Optional[list[float]] = None  # относительное положение маркера в карточке


class TableStyle(BaseModel):
    header_fill: Optional[str] = None
    header_text: str = "FFFFFF"
    body_fill: Optional[str] = None
    alt_fill: Optional[str] = None
    body_text: str = "000000"
    border: Optional[str] = None
    font_size: float = 12
    header_bold: bool = True


class Palette(BaseModel):
    colors: list[dict[str, Any]] = Field(default_factory=list)   # [{hex, weight, role}]
    bg_light: str = "FFFFFF"
    bg_dark: str = "1E1E1E"
    text_dark: str = "111111"
    text_light: str = "FFFFFF"
    muted_dark: str = "6B7280"
    muted_light: str = "D1D5DB"
    primary: str = "0077FF"
    accents: list[str] = Field(default_factory=list)
    chart: list[str] = Field(default_factory=list)
    surface: Optional[str] = None       # светлая подложка карточек

    def allowed(self) -> list[str]:
        base = [c["hex"] for c in self.colors]
        return list(dict.fromkeys(base + [self.bg_light, self.bg_dark, self.text_dark, self.text_light,
                                          self.muted_dark, self.muted_light, self.primary] + self.accents + self.chart))


class Typography(BaseModel):
    heading_font: str = "Arial"
    body_font: str = "Arial"
    scale: list[float] = Field(default_factory=list)   # допустимые кегли
    title: TextStyle = Field(default_factory=TextStyle)
    subtitle: TextStyle = Field(default_factory=TextStyle)
    kicker: Optional[TextStyle] = None
    heading: TextStyle = Field(default_factory=TextStyle)
    body: TextStyle = Field(default_factory=TextStyle)
    caption: TextStyle = Field(default_factory=TextStyle)
    number: TextStyle = Field(default_factory=TextStyle)
    title_caps: bool = False


class Slot(BaseModel):
    role: str            # title | subtitle | kicker | body | meta | pagenum | number | photo
    sid: str
    box: Box
    style: TextStyle
    max_chars: int = 80
    text: str = ""
    bg: Optional[str] = None      # цвет фона под слотом (по пикселям холста)


class ItemGroup(BaseModel):
    """Повторяющаяся структура (карточки, строки, шаги) на слайде-примере."""
    container_sids: list[str] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)  # [{box, container, members:[{sid, role, box, style, text}]}]
    arrangement: str = "row"     # row | column | grid
    count: int = 0


class Canvas(BaseModel):
    """Слайд-основа: слайд шаблона без контентных фигур."""
    id: str
    source_slide: int            # 1-based индекс слайда в шаблоне
    kind: str                    # title | section | closing | agenda | content
    layout: str
    keep_sids: list[str]         # фигуры верхнего уровня, остающиеся на холсте
    slots: list[Slot] = Field(default_factory=list)
    title_label_sid: Optional[str] = None   # подложка заголовка, ширина подстраивается под текст
    title_max_w: Optional[int] = None       # правее заголовка — логотипы/хром, заходить нельзя
    content_box: Box
    bg: str = "FFFFFF"
    dark: bool = False
    bg_busy: bool = False                   # фон с изображением/градиентом
    clean: bool = True                      # в контентной области нет декора/текста макета
    dirty_reason: Optional[str] = None
    score: float = 0.0
    preview: Optional[str] = None


class SlideInfo(BaseModel):
    index: int
    layout: str
    kind: str
    service: bool = False
    service_reason: Optional[str] = None
    title: str = ""
    text_excerpt: str = ""
    dark: bool = False
    bg: str = "FFFFFF"
    n_shapes: int = 0
    features: dict[str, Any] = Field(default_factory=dict)
    groups: list[ItemGroup] = Field(default_factory=list)
    vlm: Optional[dict[str, Any]] = None
    preview: Optional[str] = None


class Narrative(BaseModel):
    has_agenda: bool = False
    has_sections: bool = False
    closing: str = "thanks"          # thanks | summary | contacts | none
    title_caps: bool = False
    uses_kicker: bool = False
    kicker_example: Optional[str] = None
    numbering: bool = False
    avg_title_words: float = 6
    sequence: list[str] = Field(default_factory=list)
    tone: str = ""
    notes: str = ""


class TemplateProfile(BaseModel):
    id: str
    name: str
    file: str
    slide_w: int
    slide_h: int
    n_slides: int
    fonts_found: dict[str, bool] = Field(default_factory=dict)
    palette: Palette
    typography: Typography
    margins: Box                          # типовая контентная область
    gap: int = 182880
    card_styles: list[CardStyle] = Field(default_factory=list)
    table_style: TableStyle = Field(default_factory=TableStyle)
    canvases: list[Canvas] = Field(default_factory=list)
    slides: list[SlideInfo] = Field(default_factory=list)
    narrative: Narrative = Field(default_factory=Narrative)
    logo_boxes: list[Box] = Field(default_factory=list)
    image_style: str = ""
    style_summary: str = ""
    parse_seconds: float = 0.0
    version: int = 1

    def canvas(self, cid: str) -> Canvas:
        for c in self.canvases:
            if c.id == cid:
                return c
        raise KeyError(cid)

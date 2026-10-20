"""Встроенные стили: описание (токены) стиля, из которого генерируется .pptx-пак."""
from __future__ import annotations

import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Category = Literal["work", "finance", "promo", "academic", "consulting"]


class StylePalette(BaseModel):
    bg: str                    # фон контентных слайдов
    surface: str               # подложка карточек и блоков кода
    primary: str               # структурный цвет: заголовки разделов, номера, тёмные слайды
    secondary: str             # второй цвет схем и диаграмм
    accent: str                # акцент — одна точка внимания на слайде
    text: str
    muted: str
    rule: str                  # тонкие линии и рамки
    dark_bg: str               # фон обложки и разделителей
    dark_text: str

    @field_validator("*", mode="before")
    @classmethod
    def _hex(cls, v):
        # YAML читает цвета из одних цифр (233057, 000000) как числа
        if isinstance(v, int):
            v = f"{v:06d}"
        return str(v).lstrip("#").upper()


class StyleFonts(BaseModel):
    heading: str
    body: str
    mono: str = "IBM Plex Mono"            # без лигатур: в учебном коде «!=» не должно превращаться в «≠»


class StyleChrome(BaseModel):
    kicker_caps: bool = True
    kicker_spacing: float = 2.0      # разрядка кикера, пт
    rule: bool = True                # тонкая линия под заголовком
    footer: bool = True
    pagenum: bool = True
    title_size: float = 28
    cover_title_size: float = 46
    title_bold: bool = True
    dark_sections: bool = True
    motif: Literal["squares", "bars", "circle", "frame", "none"] = "squares"
    cover: Literal["dark", "light", "split"] = "dark"     # обложка и финал: тёмные, светлые или цветной блок на полслайда
    card_fill: bool = True           # карточки с подложкой или только тонкой рамкой


class StyleSpec(BaseModel):
    id: str
    name: str
    category: Category
    mood: str = ""
    description: str = ""
    generator: Literal["editorial", "bold", "minimal", "academic"] = "editorial"
    palette: StylePalette
    fonts: StyleFonts
    chrome: StyleChrome = Field(default_factory=StyleChrome)
    logo: str = ""                         # PNG логотипа для светлого фона (брендбук)
    logo_dark: str = ""                    # PNG логотипа для тёмного фона (светлый знак)
    margin: Optional[float] = None         # поля слайда, px сетки 960×540 (брендбук: spacing.margin)
    radius: Optional[float] = None         # скругление карточек, px
    logo_min_h: Optional[float] = None     # минимальная высота логотипа, px
    logo_clear: Optional[float] = None     # охранное поле — доля высоты логотипа

    def with_overrides(self, colors: Optional[dict[str, str]] = None, fonts: Optional[dict[str, str]] = None,
                       logo: str = "", logo_dark: str = "", grid: Optional[dict] = None) -> "StyleSpec":
        """«Свои цвета» Kimi: фон / основной / вторичный / вспомогательный. Производные цвета пересчитываются."""
        spec = self.model_copy(deep=True)
        if colors:
            c = {k: v.lstrip("#").upper() for k, v in colors.items() if v}
            p = spec.palette
            if "background" in c:
                p.bg = c["background"]
                dark = _lum(p.bg) < 0.4
                p.text = "F2F2F2" if dark else "1F2328"
                p.muted = _mix(p.text, p.bg, 0.45)
                p.rule = _mix(p.text, p.bg, 0.82)
                p.surface = _mix(p.text, p.bg, 0.94)
            if "primary" in c:
                p.primary = c["primary"]
                p.dark_bg = c["primary"] if _lum(c["primary"]) < 0.35 else _mix("000000", c["primary"], 0.55)
                p.dark_text = "FFFFFF" if _lum(p.dark_bg) < 0.5 else "111111"
            if "secondary" in c:
                p.secondary = c["secondary"]
            if "auxiliary" in c:
                p.accent = c["auxiliary"]
            # брендбук задаёт роли точно: тёмный фон обложки, цвет текста и приглушённый
            if "dark" in c:
                p.dark_bg = c["dark"]
                p.dark_text = "FFFFFF" if _lum(p.dark_bg) < 0.5 else "111111"
            if "text" in c and _contrast(c["text"], p.bg) >= 4.5:
                p.text = c["text"]
            if "muted" in c and _contrast(c["muted"], p.bg) >= 3.0:
                p.muted = c["muted"]
        if fonts:
            spec.fonts = spec.fonts.model_copy(update={k: v for k, v in fonts.items() if v})
        if logo:
            spec.logo = logo
        if logo_dark:
            spec.logo_dark = logo_dark
        for k, v in (grid or {}).items():
            if v is not None and k in ("margin", "radius", "logo_min_h", "logo_clear"):
                setattr(spec, k, float(v))
        return spec

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lum(h: str) -> float:
    r, g, b = (x / 255 for x in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a) + 0.05, _lum(b) + 0.05
    return max(la, lb) / min(la, lb)


def _mix(a: str, b: str, t: float) -> str:
    """t=0 → a, t=1 → b."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "%02X%02X%02X" % (round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t))

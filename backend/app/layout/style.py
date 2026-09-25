"""Разрешение стилей под конкретный холст: цвета с учётом фона и контраста, кегли из шкалы, карточки."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..parsing.model import Canvas, CardStyle, TemplateProfile
from ..parsing.ooxml import color_distance, contrast, hex_to_rgb, luminance, rgb_to_hex


def mix(a: str, b: str, k: float) -> str:
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex([ra[i] * (1 - k) + rb[i] * k for i in range(3)])


def readable(preferred: list[Optional[str]], bg: str, min_ratio: float = 4.5, fallback: Optional[list[str]] = None) -> str:
    for c in preferred:
        if c and contrast(c, bg) >= min_ratio:
            return c
    for c in fallback or []:
        if c and contrast(c, bg) >= min_ratio:
            return c
    return "FFFFFF" if luminance(bg) < 0.4 else "000000"


@dataclass
class CardChoice:
    index: Optional[int]      # индекс CardStyle в профиле или None (синтетическая)
    fill: Optional[str]
    line: Optional[str]
    text: str
    heading: str
    accent: str               # цвет цифр/иконок на карточке
    muted: str
    surface: str              # фактический цвет под текстом


class Look:
    """Набор токенов, применимых на данном холсте."""

    def __init__(self, profile: TemplateProfile, canvas: Canvas):
        self.p = profile
        self.c = canvas
        pal = profile.palette
        ty = profile.typography
        self.bg = canvas.bg
        self.dark = canvas.dark
        body_pref = [ty.body.color, pal.text_dark] if not self.dark else [pal.text_light, ty.body.color, "FFFFFF"]
        self.fg = readable(body_pref, self.bg, 4.5, [pal.text_dark, pal.text_light])
        head_pref = [ty.heading.color, ty.title.color, self.fg] if not self.dark else [pal.text_light, "FFFFFF"]
        self.heading = readable(head_pref, self.bg, 4.5, [self.fg])
        muted_pref = [ty.caption.color, pal.muted_dark] if not self.dark else [pal.muted_light]
        self.muted = readable(muted_pref, self.bg, 4.5, [self.fg])
        self.accent = readable([pal.primary] + pal.accents, self.bg, 3.0, [self.heading])
        self.accent2 = readable([a for a in pal.accents if a != self.accent] + [pal.primary], self.bg, 3.0, [self.accent])
        from ..parsing import fonts as _f
        cands = [ty.heading.font, ty.title.font, ty.body.font, ty.number.font]
        usable = [f for f in cands if f and _f.font_available(f)]

        def pick(f):
            # шрифт шаблона без кириллицы рендерер подменит чужим — берём другую гарнитуру шаблона
            return f if (f and _f.font_available(f)) or not usable else usable[0]
        self.heading_font = pick(ty.heading.font or ty.title.font)
        self.body_font = pick(ty.body.font)
        self.number_font = pick(ty.number.font or ty.title.font)
        self.scale = ty.scale or [10, 12, 14, 16, 18, 20, 24, 28, 32, 40]
        W = profile.slide_w
        # относительный масштаб: шаблоны 10" и 13.33" имеют разные абсолютные кегли
        self.k = W / (13.333 * 914400)
        self.body_size = ty.body.size
        self.heading_size = max(ty.heading.size, ty.body.size)
        self.caption_size = min(ty.caption.size, ty.body.size)
        floor = max(7.5 * self.k + 1.5, 7.0)
        self.min_size = self.snap_up(floor) if any(s >= floor for s in self.scale) else self.scale[0]
        self.number_size = ty.number.size
        # «потолок» кеглей для разреженного контента: текст крупнее, пустот меньше
        self.body_max = max(self.body_size, self.snap_down(self.body_size * 1.35))
        self.heading_max = max(self.heading_size, self.snap_down(self.body_size * 1.7))
        self.gap = profile.gap
        self.title_caps = ty.title_caps
        self.chart_colors = [c for c in pal.chart] or [pal.primary] + pal.accents

    # ---------------------------------------------------------------- sizes
    def snap_down(self, size: float) -> float:
        cands = [s for s in self.scale if s <= size + 1e-6]
        return max(cands) if cands else size

    def snap_up(self, size: float) -> float:
        cands = [s for s in self.scale if s >= size - 1e-6]
        return min(cands) if cands else size

    def sizes_between(self, lo: float, hi: float) -> list[float]:
        vals = {s for s in self.scale if lo - 1e-6 <= s <= hi + 1e-6}
        return sorted(vals or {self.snap_down(hi)}, reverse=True)

    def pairs(self) -> list[tuple[float, float]]:
        """Пары (заголовок, текст) от крупных к мелким с сохранением пропорции."""
        out = []
        for bs in self.sizes_between(self.min_size, self.body_max):
            hs = min(self.heading_max, max(bs, self.snap_up(bs * 1.22)))
            out.append((hs, bs))
        return out

    # ---------------------------------------------------------------- cards
    def _card_ok(self, cs: CardStyle) -> bool:
        if cs.fill is None and cs.line is None:
            return False
        if cs.fill and color_distance(cs.fill, self.bg) < 10 and not cs.line:
            # карточка сливается с фоном (часто так бывает с тенью) — допустимо, если есть тень
            return "outerShdw" in cs.sppr_xml
        return True

    def card(self, accent: bool = False) -> CardChoice:
        pal = self.p.palette
        best = None
        for i, cs in enumerate(self.p.card_styles):
            if cs.accent != accent or not self._card_ok(cs):
                continue
            surf = cs.fill or self.bg
            # светлые карточки на тёмном фоне и наоборот допустимы; главное — читаемость текста
            txt = readable([cs.text_color, pal.text_dark, pal.text_light], surf, 4.5)
            if max(contrast(c, surf) for c in (txt, pal.text_light, pal.text_dark, "FFFFFF", "000000") if c) < 4.5 \
                    or (accent and max(contrast(c, surf) for c in (pal.text_light, pal.text_dark) if c) < 4.5):
                continue   # на такой заливке мелкий текст не читается ни светлым, ни тёмным цветом
            score = cs.weight
            if cs.fill and luminance(cs.fill) < 0.3 and not self.dark and not accent:
                score *= 0.3
            if cs.on_dark != self.dark and cs.fill and color_distance(cs.fill, self.bg) < 25:
                score *= 0.5
            if best is None or score > best[0]:
                best = (score, i, cs, surf, txt)
        if best is not None:
            _, i, cs, surf, txt = best
            if cs.accent and contrast(txt, surf) < 4.5:
                txt = readable([pal.text_light, pal.text_dark], surf, 4.5)
            head = readable([cs.heading_color, txt], surf, 4.5)
            acc = readable([pal.primary] + pal.accents + [head], surf, 3.0)
            return CardChoice(i, cs.fill, cs.line, txt, head, acc, readable([pal.muted_dark, txt], surf, 4.5), surf)
        # синтетическая карточка из палитры
        if accent:
            for cand in [pal.primary] + pal.accents:
                if contrast(pal.text_light, cand) >= 4.5 and contrast(cand, self.bg) >= 1.6:
                    return CardChoice(None, cand, None, pal.text_light, pal.text_light, pal.text_light, pal.text_light, cand)
            fill = mix(self.bg, pal.primary, 0.16 if not self.dark else 0.3)
            txt = readable([pal.text_dark, self.fg, pal.text_light], fill, 4.5)
            acc = readable([pal.primary] + pal.accents, fill, 3.0, [txt])
            return CardChoice(None, fill, None, txt, txt, acc, txt, fill)
        if self.dark:
            fill = mix(self.bg, "FFFFFF", 0.1)
        else:
            fill = pal.surface or mix(self.bg, pal.primary, 0.06)
        txt = readable([self.fg, pal.text_dark, pal.text_light], fill, 4.5)
        acc = readable([pal.primary] + pal.accents, fill, 3.0, [txt])
        return CardChoice(None, fill, None, txt, readable([self.heading, txt], fill, 4.5), acc,
                          readable([self.muted, txt], fill, 4.5), fill)

    def case(self, text: str) -> str:
        return text.upper() if self.title_caps else text

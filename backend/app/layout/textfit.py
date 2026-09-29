"""Детерминированная подгонка текста: измерение по реальным метрикам шрифта и выбор кегля из шкалы шаблона."""
from __future__ import annotations

from typing import Iterable, Optional

from ..parsing import fonts

EMU_PT = 12700


def para_height(text: str, width_pt: float, font: str, size: float, bold: bool = False, line_spacing: float = 1.0) -> float:
    if not text:
        return size * fonts.line_height_factor(font) * line_spacing
    return fonts.text_height_pt(text, width_pt, font, size, bold, line_spacing)


def block_height(paras: list[tuple[str, bool]], width_pt: float, font: str, size: float,
                 line_spacing: float = 1.0, space_after: float = 0.0) -> float:
    """paras: [(text, bold)] — высота блока в pt."""
    h = 0.0
    for i, (t, b) in enumerate(paras):
        h += para_height(t, width_pt, font, size, b, line_spacing)
        if i < len(paras) - 1:
            h += space_after
    return h


def n_lines(text: str, width_pt: float, font: str, size: float, bold: bool = False) -> int:
    return len(fonts.wrap_lines(text, width_pt, font, size, bold))


def fits(paras: list[tuple[str, bool]], w_emu: int, h_emu: int, font: str, size: float,
         line_spacing: float = 1.0, space_after_k: float = 0.0, max_lines: Optional[int] = None) -> bool:
    wpt = w_emu / EMU_PT * 0.97   # запас по ширине на расхождение метрик рендеров
    if wpt <= 4:
        return False
    for t, b in paras:
        for w in t.split():
            if fonts.text_width_pt(w, font, size, b) > wpt:
                return False   # слово не помещается целиком — был бы разрыв внутри слова
    if max_lines is not None:
        if sum(n_lines(t, wpt, font, size, b) for t, b in paras) > max_lines:
            return False
    # запас 4% на расхождения рендеров
    return block_height(paras, wpt, font, size, line_spacing, space_after_k * size) <= h_emu / EMU_PT * 0.96


def candidate_sizes(scale: Iterable[float], preferred: float, minimum: float) -> list[float]:
    """Только кегли типографической шкалы шаблона (preferred — всегда из шкалы или стиля шаблона)."""
    scale = sorted(set(scale))
    sizes = sorted({s for s in scale if minimum - 1e-6 <= s <= preferred + 1e-6}, reverse=True)
    if not sizes or sizes[0] < preferred - 1e-6:
        sizes = [preferred] + sizes
    if len(sizes) == 1 or sizes[-1] > minimum + 1e-6:
        lower = [s for s in scale if s < sizes[-1] - 1e-6]
        if lower and not any(minimum - 1e-6 <= s for s in sizes[1:]):
            sizes.append(max(lower))   # ближайший меньший кегль шкалы
    return sizes


def fit_size(paras: list[tuple[str, bool]], w_emu: int, h_emu: int, font: str, scale: Iterable[float],
             preferred: float, minimum: float, line_spacing: float = 1.0, space_after_k: float = 0.0,
             max_lines: Optional[int] = None) -> tuple[float, bool]:
    """Наибольший кегль из шкалы, при котором текст влезает. (size, ok)."""
    for s in candidate_sizes(scale, preferred, minimum):
        if fits(paras, w_emu, h_emu, font, s, line_spacing, space_after_k, max_lines):
            return s, True
    return minimum, False


def needed_height(paras: list[tuple[str, bool]], w_emu: int, font: str, size: float,
                  line_spacing: float = 1.0, space_after_k: float = 0.0) -> int:
    # тот же запас по ширине, что и в fits(): иначе «впритык» строка у LibreOffice/PowerPoint переносится,
    # а следующий блок уже поставлен под одну строку и наезжает на неё
    wpt = w_emu / EMU_PT * 0.97
    return int(block_height(paras, wpt, font, size, line_spacing, space_after_k * size) * EMU_PT * 1.05)


def text_width(text: str, font: str, size: float, bold: bool = False) -> int:
    return int(fonts.text_width_pt(text, font, size, bold) * EMU_PT)

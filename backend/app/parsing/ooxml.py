"""Низкоуровневые помощники для OOXML: пространства имён, цвета темы, заливки."""
from __future__ import annotations

import colorsys
from typing import Optional

from lxml import etree

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
}
EMU_PER_INCH = 914400
EMU_PER_PT = 12700


def qn(tag: str) -> str:
    prefix, local = tag.split(":")
    return f"{{{NS[prefix]}}}{local}"


_XP_CACHE: dict[str, etree.XPath] = {}


def _compiled(path: str) -> etree.XPath:
    x = _XP_CACHE.get(path)
    if x is None:
        x = _XP_CACHE[path] = etree.XPath(path, namespaces=NS)
    return x


def xp(el, path: str):
    """XPath с нашими префиксами; работает и для oxml-элементов python-pptx."""
    return _compiled(path)(el)


def first(el, path: str):
    r = _compiled(path)(el)
    return r[0] if r else None


# ---------------------------------------------------------------- colors

PRESET_COLORS = {
    "black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "008000",
    "blue": "0000FF", "yellow": "FFFF00", "gray": "808080", "grey": "808080",
    "darkGray": "A9A9A9", "lightGray": "D3D3D3", "orange": "FFA500",
}


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb) -> str:
    return "".join(f"{max(0, min(255, int(round(c)))):02X}" for c in rgb[:3])


def _apply_mods(hexv: str, color_el) -> str:
    r, g, b = [c / 255 for c in hex_to_rgb(hexv)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    changed = False
    for m in color_el:
        tag = etree.QName(m).localname
        val = m.get("val")
        if val is None:
            continue
        v = int(val) / 100000
        if tag == "lumMod":
            l = l * v; changed = True
        elif tag == "lumOff":
            l = l + v; changed = True
        elif tag == "tint":
            # приблизительно: смешивание с белым
            r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
            r2, g2, b2 = [c + (1 - c) * (1 - v) for c in (r2, g2, b2)]
            h, l, s = colorsys.rgb_to_hls(r2, g2, b2); changed = True
        elif tag == "shade":
            r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
            r2, g2, b2 = [c * v for c in (r2, g2, b2)]
            h, l, s = colorsys.rgb_to_hls(r2, g2, b2); changed = True
    if not changed:
        return hexv.upper()
    l = max(0.0, min(1.0, l))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return rgb_to_hex((r * 255, g * 255, b * 255))


def color_alpha(color_el) -> float:
    a = first(color_el, "a:alpha")
    return int(a.get("val")) / 100000 if a is not None else 1.0


class Theme:
    """Цвета и шрифты темы + clrMap мастера."""

    def __init__(self, theme_el=None, clr_map: Optional[dict] = None):
        self.colors: dict[str, str] = {}
        self.major_font = "Calibri"
        self.minor_font = "Calibri"
        if theme_el is not None:
            scheme = first(theme_el, ".//a:clrScheme")
            if scheme is not None:
                for child in scheme:
                    name = etree.QName(child).localname
                    c = first(child, "a:srgbClr")
                    if c is not None:
                        self.colors[name] = c.get("val").upper()
                    else:
                        c = first(child, "a:sysClr")
                        if c is not None:
                            self.colors[name] = (c.get("lastClr") or "000000").upper()
            mj = first(theme_el, ".//a:majorFont/a:latin")
            mn = first(theme_el, ".//a:minorFont/a:latin")
            if mj is not None and mj.get("typeface"):
                self.major_font = mj.get("typeface")
            if mn is not None and mn.get("typeface"):
                self.minor_font = mn.get("typeface")
        self.clr_map = clr_map or {
            "bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2",
            "accent1": "accent1", "accent2": "accent2", "accent3": "accent3",
            "accent4": "accent4", "accent5": "accent5", "accent6": "accent6",
            "hlink": "hlink", "folHlink": "folHlink",
        }

    def scheme(self, name: str) -> Optional[str]:
        mapped = self.clr_map.get(name, name)
        return self.colors.get(mapped) or self.colors.get(name)

    def font(self, typeface: Optional[str]) -> Optional[str]:
        if not typeface:
            return None
        if typeface.startswith("+mj"):
            return self.major_font
        if typeface.startswith("+mn"):
            return self.minor_font
        return typeface

    def resolve(self, color_el) -> Optional[str]:
        """color_el — элемент a:srgbClr/a:schemeClr/... ИЛИ его контейнер (solidFill)."""
        if color_el is None:
            return None
        tag = etree.QName(color_el).localname
        if tag in ("solidFill", "fgClr", "bgClr"):
            if len(color_el) == 0:
                return None
            color_el = color_el[0]
            tag = etree.QName(color_el).localname
        base = None
        if tag == "srgbClr":
            base = color_el.get("val")
        elif tag == "schemeClr":
            base = self.scheme(color_el.get("val"))
        elif tag == "sysClr":
            base = color_el.get("lastClr") or ("FFFFFF" if color_el.get("val") == "window" else "000000")
        elif tag == "prstClr":
            base = PRESET_COLORS.get(color_el.get("val"), "000000")
        elif tag == "scrgbClr":
            try:
                base = rgb_to_hex([int(color_el.get(k)) / 100000 * 255 for k in ("r", "g", "b")])
            except Exception:
                base = None
        if not base:
            return None
        return _apply_mods(base, color_el)


def parse_fill(container, theme: Theme) -> Optional[str]:
    """Возвращает hex / 'grad:HEX' / 'picture' / 'none' / None (не задано)."""
    if container is None:
        return None
    for child in container:
        tag = etree.QName(child).localname
        if tag == "noFill":
            return "none"
        if tag == "solidFill":
            c = theme.resolve(child)
            if c and len(child) and color_alpha(child[0]) < 0.15:
                return "none"
            return c
        if tag == "gradFill":
            stops = xp(child, "a:gsLst/a:gs")
            cols = [theme.resolve(s[0]) for s in stops if len(s)]
            cols = [c for c in cols if c]
            if cols:
                return "grad:" + mix_colors(cols)
            return None
        if tag == "blipFill":
            return "picture"
        if tag == "pattFill":
            fg = first(child, "a:fgClr")
            return theme.resolve(fg) if fg is not None else None
    return None


def mix_colors(cols: list[str]) -> str:
    rgbs = [hex_to_rgb(c) for c in cols]
    return rgb_to_hex([sum(c[i] for c in rgbs) / len(rgbs) for i in range(3)])


def luminance(hexv: str) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hex_to_rgb(hexv)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def color_distance(a: str, b: str) -> float:
    """Перцептивное расстояние (приближённо, redmean)."""
    r1, g1, b1 = hex_to_rgb(a)
    r2, g2, b2 = hex_to_rgb(b)
    rm = (r1 + r2) / 2
    dr, dg, db = r1 - r2, g1 - g2, b1 - b2
    return ((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db) ** 0.5


def saturation(hexv: str) -> float:
    r, g, b = [c / 255 for c in hex_to_rgb(hexv)]
    return colorsys.rgb_to_hls(r, g, b)[2]

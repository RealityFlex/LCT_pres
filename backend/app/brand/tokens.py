"""Дизайн-токены JSON: W3C Design Tokens ($value/$type), Tokens Studio (value/type) и плоский словарь
{"colors": {...}, "fonts": {...}}. Ссылки «{colors.primary}» разрешаются."""
from __future__ import annotations

import json
import re
from typing import Any

from .model import BrandColor, BrandFont, BrandKit, assign_roles, norm_hex, pick_fonts

REF = re.compile(r"^\{([^{}]+)\}$")
FONT_KEY = re.compile(r"(font|typeface|family|шрифт)", re.I)
COLOR_KEY = re.compile(r"(color|colour|цвет|palette|fill|bg|background)", re.I)


def _flatten(d: Any, path: tuple = ()) -> dict[str, Any]:
    """Листья токенов: путь → {value, type}."""
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        is_leaf = "$value" in d or ("value" in d and ("type" in d or not isinstance(d["value"], dict)))
        if is_leaf:
            out[".".join(path)] = {"value": d.get("$value", d.get("value")), "type": d.get("$type", d.get("type", ""))}
            return out
        for k, v in d.items():
            if str(k).startswith("$"):
                continue
            out.update(_flatten(v, path + (str(k),)))
    elif isinstance(d, (str, int, float)):
        out[".".join(path)] = {"value": d, "type": ""}
    return out


def _resolve(v: Any, leaves: dict[str, Any], depth: int = 0) -> Any:
    if isinstance(v, str) and depth < 8:
        m = REF.match(v.strip())
        if m and m.group(1) in leaves:
            return _resolve(leaves[m.group(1)]["value"], leaves, depth + 1)
    return v


def _color(v: Any) -> str | None:
    if isinstance(v, dict):        # {"colorSpace": "srgb", "components": [r, g, b]} или {"hex": ...}
        if v.get("hex"):
            return norm_hex(v["hex"])
        comp = v.get("components")
        if isinstance(comp, list) and len(comp) >= 3:
            return "%02X%02X%02X" % tuple(round(float(x) * 255) if float(x) <= 1 else round(float(x)) for x in comp[:3])
        return None
    if not isinstance(v, str):
        return None
    s = v.strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", s)
    if m:
        return norm_hex(m.group(1))
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", s)
    if m:
        return "%02X%02X%02X" % tuple(int(x) for x in m.groups())
    return None


def _num(v) -> float | None:
    """«72px», «1.5rem», 0.5 → число (rem → 16 px)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(px|pt|rem|em)?\s*", v)
        if m:
            k = 16.0 if m.group(2) in ("rem", "em") else 1.0
            return float(m.group(1)) * k
    if isinstance(v, dict) and "value" in v:
        return _num(f"{v.get('value')}{v.get('unit', '')}")
    return None


def brand_from_tokens(data: bytes, name: str) -> BrandKit:
    try:
        tree = json.loads(data.decode("utf-8-sig"))
    except Exception as e:
        raise ValueError(f"JSON токенов не читается: {e}") from e
    leaves = _flatten(tree)
    colors: list[BrandColor] = []
    fonts: list[BrandFont] = []
    for path, leaf in leaves.items():
        v = _resolve(leaf["value"], leaves)
        t = str(leaf.get("type", "")).lower()
        label = path.replace(".", "/")
        if t in ("color", "") and (c := _color(v)):
            # вес по имени: «primary/brand» — главнее, оттенки шкалы (100…900) — слабее
            w = 10.0 if re.search(r"(primary|brand|accent|основн|фирмен)", label, re.I) else 3.0
            if re.search(r"(\b|/)(50|100|200|300|700|800|900)$", label):
                w *= 0.4
            colors.append(BrandColor(hex=c, name=label, weight=w, source="token"))
        elif t in ("fontfamily", "fontfamilies") or (isinstance(v, str) and FONT_KEY.search(path) and not _color(v)):
            fam = v[0] if isinstance(v, list) and v else v
            if isinstance(fam, str) and fam.strip():
                fonts.append(BrandFont(family=fam.split(",")[0].strip().strip("'\""), name=label, weight=5))
        elif t == "typography" and isinstance(v, dict):
            fam = _resolve(v.get("fontFamily"), leaves)
            size = _resolve(v.get("fontSize"), leaves)
            if isinstance(fam, str):
                try:
                    sz = float(re.sub(r"[^\d.]", "", str(size))) if size is not None else None
                except ValueError:
                    sz = None
                fonts.append(BrandFont(family=fam.split(",")[0].strip(), name=label, size=sz, weight=5))
    title = str(tree.get("$name") or tree.get("name") or "") if isinstance(tree, dict) else ""
    desc = str(tree.get("$description") or "") if isinstance(tree, dict) else ""
    q = re.search(r"«([^»]{2,40})»", desc)
    kit = BrandKit(name=title or (q.group(1) if q else re.sub(r"\.json$", "", name)), sources=[f"токены: {name}"])
    kit.colors = colors[:40]
    kit.palette, kit.accents = assign_roles(colors)
    # явные роли из имён («colors.background», «colors.text») — точнее эвристики
    for c in colors:
        last = c.name.split("/")[-1].lower()
        for role, rx in (("primary", r"^(primary|brand|main)$"), ("secondary", r"^secondary$"), ("bg", r"^(background|bg)$"),
                         ("surface", r"^(surface|card|paper)$"), ("bg_dark", r"^(dark|background-dark|bg-dark|inverse)$"),
                         ("text", r"^(text|foreground|fg|ink)$"), ("muted", r"^(muted|subtle|text-secondary)$")):
            if re.match(rx, last):
                kit.palette[role] = c.hex
    # акценты — насыщенные цвета, кроме основного и второго; названные «accent» — первыми
    from .model import chroma
    taken = {kit.palette.get("primary"), kit.palette.get("secondary")}
    acc = [c for c in colors if c.hex not in taken and chroma(c.hex) >= 0.25]
    acc.sort(key=lambda c: (0 if re.search(r"accent|акцент", c.name, re.I) else 1, -c.weight))
    kit.accents = list(dict.fromkeys(c.hex for c in acc))[:4] or [a for a in kit.accents if a not in taken]
    # сетка и правила логотипа: отступы, скругление, минимальная высота и охранное поле
    for path, leaf in leaves.items():
        v = _resolve(leaf["value"], leaves)
        key = path.lower()
        num = _num(v)
        if num is None:
            continue
        if re.search(r"(spacing|space|grid)\.(margin|page|padding)", key):
            kit.spacing["margin"] = num
        elif re.search(r"(spacing|space|grid)\.(gap|gutter)", key):
            kit.spacing["gap"] = num
        elif re.search(r"radius", key):
            kit.spacing.setdefault("radius", num)
        elif re.search(r"logo.*(min|минимал)", key):
            kit.logo_min_h = num
        elif re.search(r"logo.*(clear|охран|safe)", key):
            kit.logo_clear = num
    kit.font_styles = fonts
    kit.fonts = pick_fonts(fonts)
    for f in fonts:
        last = f.name.split("/")[-1].lower()
        if re.search(r"(heading|title|display)", last):
            kit.fonts["heading"] = f.family
        elif re.search(r"(body|text|base|regular)", last):
            kit.fonts["body"] = f.family
    if not colors:
        kit.warnings.append("в JSON не найдено ни одного цвета")
    return kit

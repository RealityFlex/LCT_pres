"""Брендбук в одном виде — откуда бы он ни пришёл (.fig, токены JSON, PDF-гайдлайн, папка с логотипами).

Цвета приходят «как есть» (с именами и весом использования), роли — primary / secondary / accents /
bg / text / muted — назначает assign_roles: по именам («primary», «brand», «accent», «фон»), по частоте
и площади, по насыщенности и светлоте. Шрифты — heading / body / mono.
"""
from __future__ import annotations

import colorsys
import re
from typing import Optional

from pydantic import BaseModel, Field


class BrandColor(BaseModel):
    hex: str                       # RRGGBB, без #
    name: str = ""
    weight: float = 0.0            # сколько этого цвета в макетах (частота × площадь), для ролей
    source: str = ""               # style | variable | fill | token | pdf | image


class BrandFont(BaseModel):
    family: str
    role: str = ""                 # heading | body | mono
    style: str = ""                # Bold, Regular…
    size: Optional[float] = None
    name: str = ""                 # имя стиля в брендбуке («Heading L»)
    weight: float = 0.0


class BrandLogo(BaseModel):
    name: str = ""
    png: str = ""                  # путь к PNG с прозрачностью (для PPTX)
    svg: str = ""                  # путь к SVG (если логотип векторный)
    w: float = 0.0
    h: float = 0.0
    dark_bg: bool = False          # логотип для тёмного фона (светлый знак)


class BrandKit(BaseModel):
    id: str = ""
    name: str = ""
    sources: list[str] = Field(default_factory=list)
    colors: list[BrandColor] = Field(default_factory=list)
    palette: dict[str, str] = Field(default_factory=dict)      # primary, secondary, bg, text, muted, bg_dark
    accents: list[str] = Field(default_factory=list)
    fonts: dict[str, str] = Field(default_factory=dict)        # heading, body, mono → семейство
    font_styles: list[BrandFont] = Field(default_factory=list)
    logos: list[BrandLogo] = Field(default_factory=list)
    slides: list[dict] = Field(default_factory=list)           # примеры слайдов 16:9: {name, page, w, h, bg}
    rules: list[str] = Field(default_factory=list)
    spacing: dict[str, float] = Field(default_factory=dict)    # margin, gap, radius — px сетки 960×540
    logo_min_h: Optional[float] = None                         # минимальная высота логотипа, px сетки 960×540
    logo_clear: Optional[float] = None                         # охранное поле — доля высоты логотипа
    warnings: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        p = self.palette
        parts = [f"цвета: основной #{p['primary']}" if p.get("primary") else "цвета не найдены"]
        if self.accents:
            parts.append("акценты " + ", ".join("#" + a for a in self.accents[:4]))
        if self.fonts:
            parts.append("шрифты: " + ", ".join(f"{k} — {v}" for k, v in self.fonts.items()))
        parts.append(f"логотипов: {len(self.logos)}")
        return "; ".join(parts)


# ------------------------------------------------------------------ роли цветов
PRIMARY_NAME = re.compile(r"(primary|brand|main|основн|фирмен|бренд|accent\b|акцент)", re.I)
SECONDARY_NAME = re.compile(r"(secondary|второст|втор(ой|ая|ое)\b|дополнит)", re.I)
BG_NAME = re.compile(r"(background|\bbg\b|фон|surface|canvas|paper)", re.I)
TEXT_NAME = re.compile(r"(text|ink|текст|foreground|\bfg\b|content)", re.I)
MUTED_NAME = re.compile(r"(muted|secondary text|subtle|grey|gray|сер|caption|placeholder|disabled)", re.I)
STATUS_NAME = re.compile(r"(error|danger|warning|success|negative|positive|ошибк|успех|destructive)", re.I)


def norm_hex(v: str) -> Optional[str]:
    v = (v or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", v):
        v = "".join(c * 2 for c in v)
    if re.fullmatch(r"[0-9a-fA-F]{8}", v):
        v = v[:6]
    return v.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", v) else None


def hls(hexv: str) -> tuple[float, float, float]:
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)


def chroma(hexv: str) -> float:
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return max(r, g, b) - min(r, g, b)


def dist(a: str, b: str) -> float:
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    rm = (ra + rb) / 2      # «красное» среднее: простая перцептивная дистанция
    return ((2 + rm / 256) * (ra - rb) ** 2 + 4 * (ga - gb) ** 2 + (2 + (255 - rm) / 256) * (ba - bb) ** 2) ** 0.5


def merge(colors: list[BrandColor]) -> list[BrandColor]:
    """Один hex — одна запись: веса складываются, имя — от стиля/переменной, если есть."""
    out: dict[str, BrandColor] = {}
    rank = {"style": 0, "variable": 1, "token": 2, "pdf": 3, "fill": 4, "image": 5}
    for c in colors:
        h = norm_hex(c.hex)
        if not h:
            continue
        cur = out.get(h)
        if cur is None:
            out[h] = c.model_copy(update={"hex": h})
        else:
            cur.weight += c.weight
            if rank.get(c.source, 9) < rank.get(cur.source, 9) and c.name:
                cur.name, cur.source = c.name, c.source
    return sorted(out.values(), key=lambda c: -c.weight)


def assign_roles(colors: list[BrandColor], slide_bgs: list[str] | None = None) -> tuple[dict[str, str], list[str]]:
    """Палитра по ролям: (palette, accents)."""
    cs = merge(colors)
    if not cs:
        return {}, []
    # серо-голубые (#889BAF) — нейтральные: фирменный цвет должен быть заметно насыщенным
    neutral = [c for c in cs if chroma(c.hex) < 0.25]
    chromatic = [c for c in cs if chroma(c.hex) >= 0.25 and not STATUS_NAME.search(c.name) and not MUTED_NAME.search(c.name)]
    if not chromatic:
        chromatic = [c for c in cs if chroma(c.hex) >= 0.25]
    pal: dict[str, str] = {}

    def score(c: BrandColor, rx: Optional[re.Pattern] = None) -> float:
        boost = 3.0 if rx is not None and rx.search(c.name) else 1.0
        return c.weight * boost * (0.6 + chroma(c.hex) if c in chromatic else 1.0)

    lights = [c for c in neutral if hls(c.hex)[1] >= 0.85]
    darks = [c for c in neutral if hls(c.hex)[1] <= 0.25]
    mids = [c for c in neutral if 0.3 <= hls(c.hex)[1] <= 0.75]
    if lights:
        pal["bg"] = max(lights, key=lambda c: score(c, BG_NAME)).hex
    if darks:
        pal["text"] = max(darks, key=lambda c: score(c, TEXT_NAME)).hex
    if mids:
        pal["muted"] = max(mids, key=lambda c: score(c, MUTED_NAME)).hex
    # фон слайдов-примеров — самый сильный сигнал: тёмный бренд остаётся тёмным
    for bgc in slide_bgs or []:
        h = norm_hex(bgc)
        if h and hls(h)[1] < 0.3:
            pal["bg_dark"] = h
            break
    if chromatic:
        prim = max(chromatic, key=lambda c: score(c, PRIMARY_NAME))
        pal["primary"] = prim.hex
        rest = [c for c in chromatic if c.hex != prim.hex and dist(c.hex, prim.hex) > 90]
        sec = max(rest, key=lambda c: score(c, SECONDARY_NAME), default=None)
        if sec is not None:
            pal["secondary"] = sec.hex
        accents = []
        for c in sorted(rest, key=lambda c: -score(c)):
            if all(dist(c.hex, a) > 90 for a in accents + [prim.hex]):
                accents.append(c.hex)
            if len(accents) >= 4:
                break
    else:
        accents = []
        # монохромный бренд: «основной» — самый тёмный из частых
        if darks:
            pal["primary"] = darks[0].hex
    pal.setdefault("bg", "FFFFFF")
    pal.setdefault("text", "1A1A1A")
    if "muted" not in pal:
        pal["muted"] = "8A8F98"
    return pal, accents


def pick_fonts(fonts: list[BrandFont]) -> dict[str, str]:
    """heading — у крупных стилей и «Heading/Title/Display»; body — у «Body/Text» и по объёму текста."""
    if not fonts:
        return {}
    out: dict[str, str] = {}
    head_rx = re.compile(r"(head|title|display|h[1-3]\b|заголов|large title)", re.I)
    body_rx = re.compile(r"(body|text|paragraph|regular|основн|подпис|caption|subhead|footnote)", re.I)
    mono = [f for f in fonts if re.search(r"(mono|code|courier|consolas)", f.family, re.I)]
    if mono:
        out["mono"] = mono[0].family
    rest = [f for f in fonts if f not in mono]
    used = [f for f in rest if not f.name]                 # тексты макетов: вес — объём текста
    styles = [f for f in rest if f.name]
    # стили — намерение дизайнера, тексты — реальное употребление: учитываем оба (библиотеки держат стили
    # под все платформы — Roboto, SF Pro, — а в макетах живёт фирменный шрифт)
    head_c = [f for f in styles if head_rx.search(f.name)] + [f for f in used if (f.size or 0) >= 22]
    if not head_c:
        head_c = sorted([f for f in rest if f.size], key=lambda f: -(f.size or 0))[:5]
    # доля семейства в реальном тексте макетов («VK Sans» — 85%, «Roboto» — 6%): стилей платформ много,
    # а фирменный шрифт тот, которым набраны макеты
    root = lambda fam: " ".join(fam.split()[:2]).lower()       # noqa: E731
    usage: dict[str, float] = {}
    for f in used:
        usage[root(f.family)] = usage.get(root(f.family), 0) + (f.weight or 0)
    total = sum(usage.values()) or 1.0
    hb: dict[str, float] = {}
    for f in head_c:
        share = usage.get(root(f.family), 0) / total if usage else 1.0
        hb[f.family] = hb.get(f.family, 0) + (f.weight or 1) * (f.size or 16) * (0.15 + share)
    if hb:
        out["heading"] = max(hb, key=lambda k: hb[k])
    body_c = [f for f in styles if body_rx.search(f.name) and not head_rx.search(f.name)]
    body_c += [f for f in used if (f.size or 14) <= 20]
    bb: dict[str, float] = {}
    for f in body_c or rest:
        bb[f.family] = bb.get(f.family, 0) + (f.weight or 1)
    if bb:
        out["body"] = max(bb, key=lambda k: bb[k])
    out.setdefault("heading", out.get("body", ""))
    return {k: v for k, v in out.items() if v}

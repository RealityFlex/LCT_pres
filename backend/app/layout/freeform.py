"""Послайдовый дизайн (как Kimi): модель компонует содержательную область каждого слайда сама.

Основа — дизайн-система стиля/шаблона: цвета по ролям, шкала кеглей, шрифты, хром (кикер, заголовок, подвал)
и область контента. Модель отвечает примитивами (text, box, line, icon) в px слайда 960×540; код привязывает
их к сетке, держит в области, подбирает кегль по реальным метрикам шрифта и переводит в элементы DeckBuilder.
Потом слайд рендерится, и модель-критик смотрит на скриншот и исправляет (см. critique).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from ..llm.skills import SkillRun
from ..parsing.model import Box, Canvas, TemplateProfile
from ..planning.models import ContentSlide, DeckContent
from . import icons
from . import ff_examples
from . import textfit as tf
from .ir import El, P, Run, SlideLayout
from .style import Look
from ..parsing.ooxml import contrast

log = logging.getLogger("freeform")

GW, GH = 960, 540
# что модель рисует сама; титул, план, разделители, финал, диаграммы и таблицы остаются за рецептами
# слайд с картинкой — рецептом: модель не видит фото и раскладывает текст поверх него
FREE_INTENTS = {"bullets", "cards", "process", "timeline", "stats", "comparison", "quote"}
SHAPES = {"rect", "roundRect", "ellipse", "chevron", "homePlate", "diamond", "hexagon"}

# ротация композиций, чтобы соседние слайды одного типа не выглядели одинаково
HINTS = {
    "process": [("цепочка шевронов в один ряд, последний шаг — акцентом, под каждым шевроном название и пояснение", "chevrons"),
                ("блоки шагов в два ряда со стрелками между ними, последний этап — акцентом", "flow"),
                ("нумерованные строки шагов с тонкими разделителями", "rows")],
    "timeline": [("горизонтальная ось с точками-вехами: период над осью, веха и пояснение под ней", "timeline"),
                 ("этапы колонками с крупными метками периода сверху и тонкими разделителями", "columns")],
    "cards": [("главный пункт — большая плашка primary слева, остальные — стопкой плашек справа", "bento"),
              ("крупные номера 01–0N над колонками текста, тонкая линия под номером", "numbered"),
              ("сетка плашек surface с иконкой, заголовком и пояснением, ровные промежутки", "grid"),
              ("колонки без плашек, разделённые тонкими вертикальными линиями, иконка сверху каждой", "columns"),
              ("нумерованные строки 01–0N с тонкими разделителями: номер, тезис, пояснение", "rows")],
    "bullets": [("вывод на тёмной плашке слева, справа список пунктов с иконками и разделителями", "split"),
                ("колонки с иконками и тонкими разделителями", "columns"),
                ("нумерованные строки с тонкими линиями между ними", "rows")],
    "stats": [("2–4 крупные цифры в ряд с подписями под ними и тонкими разделителями", "bignums")],
    "comparison": [("две колонки с плашками-заголовками и тонкой вертикальной линией между ними", "compare")],
    "quote": [("крупная фраза слева на 3/5 ширины, справа плашка primary с пояснением", "statement")],
    "image": [("тезисы слева, справа место под иллюстрацию (плашка surface) — не рисуй там текст", "")],
}


def _hex_mix(a: str, b: str, t: float) -> str:
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    return "%02X%02X%02X" % (round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t))


class Design:
    """Дизайн-система слайда для модели и обратный перевод её ответа в элементы."""

    def __init__(self, profile: TemplateProfile, canvas: Canvas, content_box: Box):
        self.p = profile
        self.look = Look(profile, canvas)
        self.k = profile.slide_w / GW               # EMU на px
        self.chevron_tight: set[str] = set()         # тексты, не влезшие в безопасную зону шеврона
        self.intent = ""                             # тип слайда (quote получает крупную фразу)
        self.orphans: list[str] = []                 # иконки, оторванные от своего текста (убраны ремонтом)
        self.expect: list[str] = []                  # заголовки пунктов содержания: все должны быть на слайде
        cb = content_box
        self.box = (round(cb.x / self.k), round(cb.y / self.k), round(cb.x2 / self.k), round(cb.y2 / self.k))
        lk, pal = self.look, profile.palette
        rule = next((c["hex"] for c in pal.colors if c.get("role") == "rule"), None) or _hex_mix(lk.fg, lk.bg, 0.82)
        surface = pal.surface or _hex_mix(lk.fg, lk.bg, 0.94)
        self.colors = {"text": lk.fg, "heading": lk.heading, "muted": lk.muted, "primary": pal.primary,
                       "accent": lk.accent, "secondary": lk.accent2, "surface": surface, "rule": rule,
                       "bg": lk.bg, "white": "FFFFFF", "dark": pal.bg_dark}
        b = lk.body_size
        self.sizes = {"caption": max(lk.min_size, lk.caption_size), "label": max(lk.min_size, lk.caption_size),
                      "body": b, "lead": lk.snap_up(b * 1.15), "heading": lk.heading_size,
                      "number": max(lk.heading_size * 1.6, lk.number_size or 0), "big": max(lk.heading_size * 2.4, 36)}

    def prompt_vars(self) -> dict[str, Any]:
        cx, cy, cx2, cy2 = self.box
        names = {"text": "основной текст", "heading": "заголовки блоков", "muted": "второстепенный текст",
                 "primary": "структурный цвет", "accent": "один акцент", "secondary": "второй цвет схем",
                 "surface": "светлая подложка", "rule": "тонкие линии", "bg": "фон", "white": "белый", "dark": "тёмный"}
        colors = "; ".join(f"{k} (#{v}, {names[k]})" for k, v in self.colors.items())
        lk = self.look
        parts = []
        for k, v in self.sizes.items():
            font = lk.heading_font if k in ("heading", "number", "big") else lk.body_font
            cw = tf.text_width("оборудование проверка", font, v) / 21 / self.k     # px на символ
            parts.append(f"{k} {v:g} pt (≈{max(1, round(200 / cw))} знаков в строке шириной 200 px, строка {round(v * 1.4)} px)")
        return {"cx": cx, "cy": cy, "cx2": cx2, "cy2": cy2, "cw": cx2 - cx, "ch": cy2 - cy, "colors": colors,
                "sizes": "; ".join(parts)}

    # ---------------------------------------------------------------- ответ модели → элементы
    def _c(self, role: Any, default: Optional[str]) -> Optional[str]:
        if role in (None, "", "none"):
            return None if default is None else default
        r = str(role).strip().lower().lstrip("#")
        if r in self.colors:
            return self.colors[r]
        allowed = {c.upper() for c in self.p.palette.allowed()} | set(self.colors.values())
        return r.upper() if len(r) == 6 and r.upper() in allowed else default

    def _snap(self, v: Any) -> int:
        try:
            return int(round(float(v) / 8.0) * 8)
        except (TypeError, ValueError):
            return 0

    def _clamp(self, x, y, w, h) -> tuple[int, int, int, int]:
        cx, cy, cx2, cy2 = self.box
        w, h = max(8, w), max(8, h)
        x = min(max(x, cx), cx2 - 8)
        y = min(max(y, cy), cy2 - 8)
        return x, y, min(w, cx2 - x), min(h, cy2 - y)

    def _emu(self, x, y, w, h) -> Box:
        return Box(x=int(x * self.k), y=int(y * self.k), w=int(w * self.k), h=int(h * self.k))

    def elements(self, raw: list[dict], prefix: str) -> list[El]:
        out: list[El] = []
        lk = self.look
        for i, e in enumerate(raw or []):
            if not isinstance(e, dict):
                continue
            t = str(e.get("type", "")).lower()
            eid = f"{prefix}{i}"
            if t == "line":
                x1, y1, x2, y2 = (self._snap(e.get(k)) for k in ("x1", "y1", "x2", "y2"))
                cx, cy, cx2, cy2 = self.box
                x1, x2 = (min(max(v, cx), cx2) for v in (x1, x2))
                y1, y2 = (min(max(v, cy), cy2) for v in (y1, y2))
                if (x1, y1) == (x2, y2):
                    continue
                b = self._emu(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
                out.append(El(id=eid, kind="line", box=b, role="dg-line", line=self._c(e.get("color"), self.colors["rule"]),
                              line_w=float(min(3, max(0.75, float(e.get("width") or 1)))), arrow=bool(e.get("arrow")),
                              dash=bool(e.get("dash")), flip_h=x2 < x1, flip_v=y2 < y1))
                continue
            x, y, w, h = (self._snap(e.get(k)) for k in ("x", "y", "w", "h"))
            if t == "icon":
                s = self._snap(e.get("size") or 32) or 32
                x, y, s2, _ = self._clamp(x, y, s, s)
                name = icons.find_icon(str(e.get("name") or "")) or "circle-check"
                out.append(El(id=eid, kind="icon", box=self._emu(x, y, s2, s2), role="dg-icon", icon=name,
                              color=self._c(e.get("color"), self.colors["primary"])))
                continue
            x, y, w, h = self._clamp(x, y, w, h)
            if t == "box":
                shape = str(e.get("shape") or "rect")
                shape = shape if shape in SHAPES else "rect"
                fill, line = self._c(e.get("fill"), None), self._c(e.get("line"), None)
                if not fill and not line:
                    continue
                r = e.get("radius")
                out.append(El(id=eid, kind="shape", box=self._emu(x, y, w, h), role="dg-box", geom=shape, fill=fill,
                              line=line, line_w=0.75 if line else 0.0,
                              radius=int(float(r) * self.k) if shape == "roundRect" and r else None))
                continue
            if t != "text":
                continue
            raw_text = str(e.get("text") or "").strip()
            if not raw_text:
                continue
            style = str(e.get("style") or "body")
            if style == "caption" and len(raw_text.split()) >= 6:
                style = "body"
            pref = self.sizes.get(style, lk.body_size)
            # жирный — только у заголовков, подписей и цифр: модель любит делать жирным всё подряд
            bold = style in ("heading", "number", "big", "label") or (style == "lead" and bool(e.get("bold")))
            font = lk.heading_font if style in ("heading", "number", "big") else lk.body_font
            lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]
            bullets = bool(e.get("bullets"))
            paras = []
            for ln in lines:
                b = bullets or ln[:2] in ("• ", "- ", "– ")
                paras.append(P(runs=[Run(text=ln.lstrip("•-– ").strip() if b else ln)], bullet=b,
                               bullet_color=self.colors["accent"] if b else None))
            box = self._emu(x, y, w, h)
            items = [(p.text, bold) for p in paras]
            minimum = max(lk.min_size, pref * (0.9 if style in ("body", "lead") else 0.6)) \
                if style not in ("caption", "label") else lk.min_size
            ls = 1.0 if style in ("number", "big") else 1.15
            one_line = style in ("number", "big", "label") and len(paras) == 1
            size, ok = tf.fit_size(items, box.w, box.h, font, lk.scale + [pref], pref, minimum, ls, 0.25,
                                   1 if one_line else None)
            for p in paras:
                p.space_after = round(0.25 * size, 1)
            align = {"l": "l", "ctr": "ctr", "c": "ctr", "center": "ctr", "r": "r"}.get(str(e.get("align") or "l"), "l")
            valign = {"t": "t", "ctr": "ctr", "c": "ctr", "middle": "ctr", "b": "b"}.get(str(e.get("valign") or "t"), "t")
            out.append(El(id=eid, kind="text", box=box, role=f"dg-{style}", paras=paras, font=font, size=size,
                          color=self._c(e.get("color"), self.colors["heading" if style == "heading" else "text"]),
                          bold=bold, align=align, valign=valign, line_spacing=ls, overflow=not ok))
        return out

    def repair(self, els: list[El]) -> int:
        """Страховка кода: минимальный кегль, высота рамки под текст (с плашкой), разведение наложений,
        контраст на тёмных плашках. Возвращает число неустранённых проблем (тогда слайд уходит на рецепт)."""
        lk, k = self.look, self.k
        bottom = int(self.box[3] * k)
        floor = max(lk.min_size, 10.0)
        shapes = [e for e in els if e.kind == "shape"]
        texts = [e for e in els if e.kind == "text"]
        icons_ = [e for e in els if e.kind == "icon"]

        def inside(t: El, sh: El) -> bool:
            cx, cy = t.box.x + t.box.w // 2, t.box.y + min(t.box.h, int(t.size * 12700 * 2)) // 2
            return sh.box.x <= cx <= sh.box.x2 and sh.box.y <= cy <= sh.box.y2

        def container(t: El) -> Optional[El]:
            cands = [sh for sh in shapes if inside(t, sh) and sh.box.w * sh.box.h > t.box.w * t.box.h * 0.8]
            return min(cands, key=lambda sh: sh.box.w * sh.box.h) if cands else None

        problems = 0
        area = (self.box[2] - self.box[0]) * (self.box[3] - self.box[1]) * k * k
        for sh in list(shapes):
            filled = any(_contains(sh.box, e.box) for e in texts + icons_)
            if not filled and sh.fill and sh.box.w * sh.box.h > 0.015 * area and self.intent != "image":
                els.remove(sh)
                shapes.remove(sh)
        solid = texts + icons_ + shapes
        for ln in [e for e in els if e.kind == "line"]:
            near = int(48 * k)
            g = Box(x=ln.box.x - near, y=ln.box.y - near, w=ln.box.w + 2 * near, h=ln.box.h + 2 * near)
            if not any(_hit(g, o.box) for o in solid):
                els.remove(ln)
        if self.intent == "quote" and texts:
            # фраза главной мысли — самый длинный текст вне тёмных плашек, крупным кеглем
            free = [t for t in texts if container(t) is None] or texts
            main = max(free, key=lambda t: sum(len(p.text) for p in t.paras))
            items0 = [(p.text, False) for p in main.paras]
            room = max(main.box.h, int((self.box[3] - self.box[1]) * k * 0.55))
            top_size = lk.snap_up(max(self.sizes["lead"] * 1.8, self.sizes["heading"] * 1.6))
            size, _ = tf.fit_size(items0, main.box.w, room, lk.heading_font, lk.scale + [top_size],
                                  top_size, self.sizes["lead"], 1.15, 0.25)
            if size > (main.size or 0):
                main.size, main.font, main.role, main.bold = size, lk.heading_font, "dg-lead", False
                main.color = self.colors["heading"]
        for t in texts:
            if (t.size or 0) < floor and not t.role.endswith(("caption", "label")):
                t.size = floor
            sh0 = container(t)
            if sh0 is not None and sh0.geom not in ("chevron", "homePlate"):
                pad = int(12 * k)
                x1, x2 = max(t.box.x, sh0.box.x + pad), min(t.box.x2, sh0.box.x2 - pad)
                if (x1, x2) != (t.box.x, t.box.x2) and x2 - x1 > int(40 * k):
                    t.box = Box(x=x1, y=t.box.y, w=x2 - x1, h=t.box.h)
            if sh0 is not None and sh0.geom in ("chevron", "homePlate"):
                # безопасная зона шеврона: без выреза слева и острия справа (глубина — половина высоты)
                notch = sh0.box.h // 2
                x1 = sh0.box.x + (notch if sh0.geom == "chevron" else int(12 * k))
                x2 = sh0.box.x2 - notch
                if t.box.x < x1 or t.box.x2 > x2:
                    t.box = Box(x=max(t.box.x, x1), y=t.box.y, w=max(int(16 * k), min(t.box.x2, x2) - max(t.box.x, x1)), h=t.box.h)
                    items0 = [(p.text, t.bold) for p in t.paras]
                    size, ok = tf.fit_size(items0, t.box.w, t.box.h, t.font or lk.body_font, lk.scale + [t.size],
                                           t.size, lk.min_size, t.line_spacing, 0.25)
                    t.size = size
                    if not ok:
                        t.overflow = True
                        self.chevron_tight.add(t.id)
            items = [(p.text.upper() if t.caps else p.text, t.bold) for p in t.paras]
            need = tf.needed_height(items, t.box.w, t.font or lk.body_font, t.size or lk.body_size, t.line_spacing, 0.25) + 45720
            if t.valign == "t" and t.box.h > need + int(24 * k):
                t.box = Box(x=t.box.x, y=t.box.y, w=t.box.w, h=int(need) + int(8 * k))
            if need > t.box.h:
                t.box = Box(x=t.box.x, y=t.box.y, w=t.box.w, h=min(int(need), bottom - t.box.y))
                t.overflow = (t.overflow and t.id in self.chevron_tight) or need > bottom - t.box.y
            style = t.role.replace("dg-", "")
            if style in ("number", "big", "label") and len(t.paras) == 1:
                # однострочные подписи и цифры проверяем по ширине: высота тут не спасает
                size, ok = tf.fit_size(items, t.box.w, t.box.h, t.font or lk.body_font, lk.scale + [t.size],
                                       t.size, lk.min_size, t.line_spacing, 0.0, 1)
                t.size = size
                t.overflow = t.overflow or not ok
            sh = container(t)
            if sh is not None:
                pad = int(12 * k)
                if t.box.y2 + pad > sh.box.y2:          # плашка растёт вместе с текстом
                    sh.box = Box(x=sh.box.x, y=sh.box.y, w=sh.box.w, h=min(bottom - sh.box.y, t.box.y2 + pad - sh.box.y))
                bg = sh.fill or self.colors["bg"]
            else:
                bg = self.colors["bg"]
            # та же норма, что у аудита: мелкий текст ≥ 4.5:1, крупный (≥18 pt или ≥14 pt жирный) ≥ 3:1
            need = 3.0 if (t.size or 0) >= 18 or (t.bold and (t.size or 0) >= 14) else 4.5
            if t.color and contrast(t.color, bg) < need + 0.1:
                cands = [self.colors[c] for c in ("text", "heading", "white", "dark")]
                ok = [c for c in cands if contrast(c, bg) >= need + 0.1]
                t.color = ok[0] if ok else max(cands, key=lambda c: contrast(c, bg))
            for ic in icons_:                             # текст, наехавший на иконку, сдвигаем вправо от неё
                if _hit(t.box, ic.box) and t.box.x < ic.box.x2 and ic.box.x <= t.box.x + int(8 * k):
                    nx = ic.box.x2 + int(8 * k)
                    t.box = Box(x=nx, y=t.box.y, w=max(int(40 * k), t.box.x2 - nx), h=t.box.h)
        for ic in icons_:                                 # иконка не должна сливаться с подложкой
            under = [sh for sh in shapes if _contains(sh.box, ic.box)]
            bg = min(under, key=lambda sh: sh.box.w * sh.box.h).fill if under else self.colors["bg"]
            bg = bg or self.colors["bg"]
            if ic.color and contrast(ic.color, bg) < 3.0:
                cands = [self.colors[c] for c in ("primary", "accent", "text", "white", "dark")]
                ic.color = max(cands, key=lambda c: contrast(c, bg))
        for a in sorted(texts, key=lambda e: e.box.y):
            if not a.role.endswith(("heading", "label", "number", "big")):
                continue
            below = [b for b in texts if b is not a and b.box.y >= a.box.y2 - int(2 * k)
                     and min(a.box.x2, b.box.x2) - max(a.box.x, b.box.x) > 0.5 * min(a.box.w, b.box.w)]
            if not below:
                continue
            b = min(below, key=lambda e: e.box.y)
            if not b.role.endswith(("body", "lead", "caption")):
                continue
            between = [o for o in els if o is not a and o is not b and o.kind in ("text", "icon")
                       and o.box.y >= a.box.y2 - int(2 * k) and o.box.y2 <= b.box.y + int(2 * k)
                       and min(o.box.x2, b.box.x2) - max(o.box.x, b.box.x) > 0]
            if between or container(a) is not container(b):
                continue
            if b.box.y - a.box.y2 > int(20 * k):
                b.box = Box(x=b.box.x, y=a.box.y2 + int(12 * k), w=b.box.w, h=b.box.h)
        # тексты одного ряда (соседи по горизонтали, разница по высоте ≤ 16 px) — по верхней линии
        tol = int(16 * k)
        for a in texts:
            for b in texts:
                if a is b or abs(a.box.y - b.box.y) > tol or a.box.y == b.box.y:
                    continue
                if (a.box.x2 <= b.box.x or b.box.x2 <= a.box.x) and min(a.box.y2, b.box.y2) > max(a.box.y, b.box.y):
                    y = min(a.box.y, b.box.y)
                    a.box = Box(x=a.box.x, y=y, w=a.box.w, h=a.box.h)
                    b.box = Box(x=b.box.x, y=y, w=b.box.w, h=b.box.h)
        # мелкий текст при свободном месте — крупнее, до кегля вводной фразы
        for t in texts:
            if not t.role.endswith(("body", "caption")):
                continue
            own = container(t)
            lim = own.box.y2 - int(16 * k) if own is not None else bottom
            for o in texts + icons_ + [sh for sh in shapes if sh is not own]:
                if o is t or (own is None and _contains(o.box, t.box)) or o.box.y < t.box.y2 - int(4 * k):
                    continue
                if min(o.box.x2, t.box.x2) - max(o.box.x, t.box.x) > 0 and (own is None or _contains(own.box, o.box)):
                    lim = min(lim, o.box.y - int(12 * k))
            room = lim - t.box.y
            items = [(p.text, t.bold) for p in t.paras]
            cur = tf.needed_height(items, t.box.w, t.font or lk.body_font, t.size, t.line_spacing, 0.25)
            if room > cur * 1.3:
                size, ok = tf.fit_size(items, t.box.w, int(room * 0.85), t.font or lk.body_font, lk.scale,
                                       self.sizes["lead"], t.size, t.line_spacing, 0.25)
                if ok and size > t.size:
                    t.size = size
                    for p_ in t.paras:
                        p_.space_after = round(0.25 * size, 1)
                    need = tf.needed_height(items, t.box.w, t.font or lk.body_font, size, t.line_spacing, 0.25) + 45720
                    t.box = Box(x=t.box.x, y=t.box.y, w=t.box.w, h=min(room, max(t.box.h, int(need))))
        # плашки поджимаем под содержимое (без пустых нижних половин), в одном ряду — одинаковой высоты
        rows: dict[int, list[El]] = {}
        for sh in shapes:
            inner = [t for t in texts + icons_ if _contains(sh.box, t.box) and t is not sh]
            if not inner or sh.geom in ("chevron", "homePlate"):
                continue
            need = max(e.box.y2 for e in inner) + int(16 * k) - sh.box.y
            if need < sh.box.h * 0.8:
                sh.box = Box(x=sh.box.x, y=sh.box.y, w=sh.box.w, h=int(need))
            rows.setdefault(round(sh.box.y / (16 * k)), []).append(sh)
        for row in rows.values():
            if len(row) > 1:
                hmax = max(sh.box.h for sh in row)
                for sh in row:
                    sh.box = Box(x=sh.box.x, y=sh.box.y, w=sh.box.w, h=hmax)
        for ln in [e for e in els if e.kind == "line" and e.box.w <= int(2 * k) and e.box.h > int(24 * k)]:
            if not any(_hit(ln.box, t.box) for t in texts):
                continue
            span = sorted((t.box.x, t.box.x2) for t in texts if min(t.box.y2, ln.box.y2) > max(t.box.y, ln.box.y))
            cols: list[list[int]] = []
            for x1, x2 in span:
                if cols and x1 <= cols[-1][1]:
                    cols[-1][1] = max(cols[-1][1], x2)
                else:
                    cols.append([x1, x2])
            gaps = [(cols[i][1] + cols[i + 1][0]) // 2 for i in range(len(cols) - 1)
                    if cols[i + 1][0] - cols[i][1] >= int(16 * k)]
            if gaps:
                x = min(gaps, key=lambda g: abs(g - ln.box.x))
                ln.box = Box(x=x, y=ln.box.y, w=ln.box.w, h=ln.box.h)
            else:
                els.remove(ln)
        content_low = max([e.box.y2 for e in shapes + texts + icons_] or [0])
        for ln in [e for e in els if e.kind == "line" and e.box.w <= int(2 * k)]:
            if ln.box.y2 > content_low + int(8 * k) and ln.box.y < content_low:
                ln.box = Box(x=ln.box.x, y=ln.box.y, w=ln.box.w, h=max(int(8 * k), content_low - ln.box.y))
        chevs = sorted([sh for sh in shapes if sh.geom in ("chevron", "homePlate")], key=lambda sh: sh.box.x)
        for n, sh in enumerate(chevs):
            inner = [t for t in texts if _contains(sh.box, t.box)]
            under = [t for t in texts if t.box.y >= sh.box.y2 - int(4 * k) and sh.box.x <= t.box.x + t.box.w // 2 <= sh.box.x2]
            for t in inner:
                lab = " ".join(p.text for p in t.paras).strip().lower()
                if any(" ".join(p.text for p in u.paras).strip().lower().startswith(lab) for u in under):
                    t.paras = [P(runs=[Run(text=f"{n + 1:02d}")])]
                    t.role, t.bold, t.align = "dg-label", True, "ctr"
        # текст, краем заехавший на фигуру сверху (подпись под шевроном), опускаем под фигуру
        for t in texts:
            own = container(t)
            for sh in shapes:
                if sh is own or not _hit(t.box, sh.box, 0.03) or (own is not None and _contains(own.box, sh.box)):
                    continue
                if _contains(sh.box, t.box):
                    continue
                if sh.box.y < t.box.y and sh.box.y2 > t.box.y:
                    ny = sh.box.y2 + int(6 * k)
                    if ny + t.box.h <= bottom:
                        t.box = Box(x=t.box.x, y=ny, w=t.box.w, h=t.box.h)
        # фигуры внахлёст (не вложенные) — модель ошиблась в геометрии: такой слайд уходит на рецепт
        for i, a in enumerate(shapes):
            for b in shapes[i + 1:]:
                if _hit(a.box, b.box, 0.03) and not _contains(a.box, b.box) and not _contains(b.box, a.box):
                    problems += 1
        # тексты не должны перекрываться: нижний сдвигаем под верхний, пока есть место
        texts.sort(key=lambda e: (e.box.y, e.box.x))
        for i, a in enumerate(texts):
            for b in texts[i + 1:]:
                if _hit(a.box, b.box, 0.08):
                    ny = a.box.y2 + int(6 * k)
                    if ny + b.box.h <= bottom:
                        b.box = Box(x=b.box.x, y=ny, w=b.box.w, h=b.box.h)
                    else:
                        problems += 1
        # горизонтальный разделитель, перечёркивающий текст (тексты выросли под свой объём), — в просвет между
        # строками ниже или выше; просвета нет — линию убираем
        for ln in [e for e in els if e.kind == "line" and e.box.h <= int(2 * k) and e.box.w > int(24 * k)]:
            if not any(_hit(ln.box, t.box) for t in texts):
                continue
            span = sorted((t.box.y, t.box.y2) for t in texts if min(t.box.x2, ln.box.x2) > max(t.box.x, ln.box.x))
            rows_: list[list[int]] = []
            for y1, y2 in span:
                if rows_ and y1 <= rows_[-1][1]:
                    rows_[-1][1] = max(rows_[-1][1], y2)
                else:
                    rows_.append([y1, y2])
            gaps = [(rows_[i][1] + rows_[i + 1][0]) // 2 for i in range(len(rows_) - 1)
                    if rows_[i + 1][0] - rows_[i][1] >= int(8 * k)]
            if gaps:
                y = min(gaps, key=lambda g: abs(g - ln.box.y))
                ln.box = Box(x=ln.box.x, y=y, w=ln.box.w, h=ln.box.h)
            else:
                els.remove(ln)
        problems += sum(1 for t in texts if t.overflow)
        self.drop_orphans(els)
        self.align_icons(els)
        # невысокая композиция — целиком чуть выше центра области, а не прижатой к верху с пустым низом
        if els:
            top, low = min(e.box.y for e in els), max(e.box.y2 for e in els)
            area_top, area_h = int(self.box[1] * k), int((self.box[3] - self.box[1]) * k)
            used = low - top
            if used < 0.7 * area_h and top - area_top < int(24 * k):
                dy = int((area_h - used) * 0.38)
                for e in els:
                    e.box = Box(x=e.box.x, y=e.box.y + dy, w=e.box.w, h=e.box.h)
        return problems + overlap_count(els)       # финальная проверка — по правилам аудита

    def missing(self, els: list[El]) -> list[str]:
        """Пункты содержания, которых модель не поставила на слайд (сравнение по началу заголовка)."""
        have = " ".join(p.text.lower() for e in els if e.kind == "text" for p in e.paras)
        return [h for h in self.expect if h.strip().lower()[:14] not in have]

    def drop_orphans(self, els: list[El]) -> None:
        k = self.k
        self.orphans = []
        texts = [e for e in els if e.kind == "text"]
        for ic in [e for e in els if e.kind == "icon"]:
            near = int(56 * k)
            g = Box(x=ic.box.x - near, y=ic.box.y - near, w=ic.box.w + 2 * near, h=ic.box.h + 2 * near)
            if not any(_hit(g, t.box) for t in texts):
                self.orphans.append(ic.icon or "icon")
                els.remove(ic)
                for sh in [e for e in els if e.kind == "shape" and _contains(e.box, ic.box, int(2 * k))
                           and e.box.w <= 3 * ic.box.w and e.box.h <= 3 * ic.box.h]:
                    els.remove(sh)

    def align_icons(self, els: list[El]) -> None:
        """Иконка — часть своего блока: по центру над центрированным текстом, по левому краю над текстом
        с левым выравниванием, слева от заголовка — по середине его первой строки, в шевроне — в центре."""
        k = self.k
        texts = [e for e in els if e.kind == "text"]
        shapes = [e for e in els if e.kind == "shape"]
        for ic in [e for e in els if e.kind == "icon"]:
            sz = ic.box.w
            # подложка иконки (кружок, квадратик) — двигается вместе с ней, иконка — в её центре
            tiles = [sh for sh in shapes if sh.geom not in ("chevron", "homePlate") and _contains(sh.box, ic.box, int(2 * k))
                     and sh.box.w <= 3 * sz and sh.box.h <= 3 * sz]
            tile = min(tiles, key=lambda x: x.box.w * x.box.h) if tiles else None
            unit = tile.box if tile else ic.box

            def place(x: int, y: int):
                if tile is not None:
                    tile.box = Box(x=x, y=y, w=tile.box.w, h=tile.box.h)
                    ic.box = Box(x=x + (tile.box.w - sz) // 2, y=y + (tile.box.h - sz) // 2, w=sz, h=sz)
                else:
                    ic.box = Box(x=x, y=y, w=sz, h=sz)

            b = unit
            chev = [sh for sh in shapes if sh.geom in ("chevron", "homePlate") and _contains(sh.box, b)]
            if chev:
                sh = min(chev, key=lambda x: x.box.w * x.box.h)
                notch = sh.box.h // 2
                x1 = sh.box.x + (notch if sh.geom == "chevron" else int(12 * k))
                x2 = sh.box.x2 - notch
                inside = [t for t in texts if _contains(sh.box, t.box)]
                cx = (x1 + x2) // 2
                if inside:      # иконка и подпись в шевроне — рядом, по центру
                    t = inside[0]
                    place(max(x1, t.box.x - b.w - int(8 * k)), sh.box.y + (sh.box.h - b.h) // 2)
                else:
                    place(cx - b.w // 2, sh.box.y + (sh.box.h - b.h) // 2)
                continue
            below = [t for t in texts if t.box.y >= b.y2 - int(4 * k) and t.box.y - b.y2 < int(64 * k)
                     and min(t.box.x2, b.x2) - max(t.box.x, b.x) > 0]
            right = [t for t in texts if 0 <= t.box.x - b.x2 < int(48 * k)
                     and min(t.box.y2, b.y2) - max(t.box.y, b.y) > 0]
            if right and (not below or min(t.box.x - b.x2 for t in right) < min(t.box.y - b.y2 for t in below)):
                t = min(right, key=lambda t: t.box.x - b.x2)
                size = t.size or self.look.body_size
                line_h = int(size * 12700 * 1.2 * t.line_spacing)
                items = [(p_.text, t.bold) for p_ in t.paras]
                need = min(t.box.h, tf.needed_height(items, t.box.w, t.font or self.look.body_font, size, t.line_spacing, 0.25))
                top = t.box.y + {"ctr": (t.box.h - need) // 2, "b": t.box.h - need}.get(t.valign, 0)
                place(b.x, top + (line_h - b.h) // 2)
            elif below:
                t = min(below, key=lambda t: t.box.y - b.y2)
                if t.align == "ctr":
                    x = t.box.x + (t.box.w - b.w) // 2
                elif t.align == "r":
                    x = t.box.x2 - b.w
                else:
                    x = t.box.x
                place(x, b.y)

    def salvage(self, els: list[El]) -> int:
        """Доводка кодом, когда модель почти справилась: плашки (вместе с их содержимым), перекрывшие друг
        друга, раздвигаются — нижняя опускается под верхнюю, соседняя справа сужается. Потом повторный ремонт."""
        k = self.k
        gap = int(16 * k)
        bottom = int(self.box[3] * k)
        shapes = [e for e in els if e.kind == "shape"]
        tops = [sh for sh in shapes if not any(o is not sh and _contains(o.box, sh.box) for o in shapes)]
        groups = []
        for sh in tops:
            members = [e for e in els if e is not sh and _contains(sh.box, e.box)]
            groups.append((sh, members))
        groups.sort(key=lambda g: (g[0].box.y, g[0].box.x))

        def move(g, dx: int, dy: int):
            for e in [g[0]] + g[1]:
                e.box = Box(x=e.box.x + dx, y=e.box.y + dy, w=e.box.w, h=e.box.h)

        def narrow(g, x2: int):
            sh = g[0]
            cut = sh.box.x2 - x2
            if cut <= 0 or sh.box.w - cut < int(80 * k):
                return False
            for e in [sh] + g[1]:
                if e.box.x2 > x2:
                    e.box = Box(x=e.box.x, y=e.box.y, w=max(int(24 * k), e.box.w - cut), h=e.box.h)
            return True

        for i, a in enumerate(groups):
            for b in groups[i + 1:]:
                A, B = a[0].box, b[0].box
                if not _hit(A, B, 0.03):
                    continue
                ov_x = min(A.x2, B.x2) - max(A.x, B.x)
                ov_y = min(A.y2, B.y2) - max(A.y, B.y)
                if ov_y <= ov_x:            # друг под другом — нижнюю опускаем
                    dy = A.y2 + gap - B.y
                    if B.y2 + dy <= bottom:
                        move(b, 0, dy)
                else:                       # рядом — левую сужаем до соседки
                    narrow(a, B.x - gap)
        return self.repair(els)

    def diagnose(self, els: list[El]) -> list[str]:
        """Проблемы словами — модель исправляет их точнее, чем по картинке."""
        k = self.k
        out = []

        def name(e: El) -> str:
            if e.kind == "text" and e.paras:
                return "«" + e.paras[0].text[:28] + "»"
            return "плашка " + e.geom if e.kind == "shape" else e.kind

        for e in els:
            if e.kind == "text" and e.overflow and e.id in self.chevron_tight:
                out.append(f"текст {name(e)} не помещается внутри шеврона — сделай шеврон низким (56–80 px), внутри "
                           "только короткую подпись шага, а название и пояснение — отдельными текстами ПОД шевроном")
            elif e.kind == "text" and e.overflow:
                items = [(p.text, e.bold) for p in e.paras]
                need = tf.needed_height(items, e.box.w, e.font or self.look.body_font, e.size, e.line_spacing, 0.25)
                out.append(f"текст {name(e)} не помещается: рамка {round(e.box.w / k)}×{round(e.box.h / k)} px, "
                           f"нужно ≈{round(need / k) + 8} px высоты при кегле {e.size:g} — дай больше места или раздели блок")
        small = [e for e in els if e.kind == "text" and e.role in ("dg-body", "dg-lead")
                 and (e.size or 0) < self.sizes["body"] * 0.95]
        if small:
            out.append(f"текст {name(small[0])} получился мелким ({small[0].size:g} pt при норме {self.sizes['body']:g}) — "
                       "дай текстовым рамкам и карточкам больше места, сократи число блоков")
        missing = self.missing(els)
        if missing:
            out.append("на слайде нет пунктов: " + "; ".join(f"«{m}»" for m in missing[:4])
                       + " — каждый пункт содержания с его пояснением должен быть на слайде")
        if self.orphans:
            out.append(f"иконки {', '.join(self.orphans)} стояли далеко от своих текстов (сдвинуты на ряд) — каждая иконка "
                       "в том же ряду, что и её заголовок: тот же y, слева от заголовка с отступом 12–16 px")
        boxes = [e for e in els if e.kind in ("text", "shape", "icon")]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                nested = (a.kind == "shape" and _contains(a.box, b.box)) or (b.kind == "shape" and _contains(b.box, a.box))
                if _hit(a.box, b.box, 0.03) and not nested:
                    out.append(f"{name(a)} перекрывает {name(b)}")
        stack = sorted([e for e in els if e.kind in ("text", "shape")], key=lambda e: e.box.y)
        for i, a in enumerate(stack):
            nxt = [b for b in stack[i + 1:] if b.box.y >= a.box.y2 and min(a.box.x2, b.box.x2) - max(a.box.x, b.box.x) > 0.5 * min(a.box.w, b.box.w)]
            if nxt:
                b = min(nxt, key=lambda b: b.box.y)
                gap = (b.box.y - a.box.y2) / k
                if gap > 64:
                    out.append(f"пустой разрыв {round(gap)} px между {name(a)} и {name(b)} — придвинь блоки друг к другу "
                               "(16–24 px), освободившуюся высоту отдай тексту")
                    break
        cx, cy, cx2, cy2 = self.box
        if els:
            used_w = (max(e.box.x2 for e in els) - min(e.box.x for e in els)) / k
            used_h = (max(e.box.y2 for e in els) - min(e.box.y for e in els)) / k
            fill = used_w * used_h / max(1, (cx2 - cx) * (cy2 - cy))
            if fill < 0.55:
                out.append(f"композиция занимает только {round(fill * 100)}% области {cx2 - cx}×{cy2 - cy} px — "
                           "укрупни блоки и используй высоту")
            elif used_w < 0.82 * (cx2 - cx):
                out.append(f"композиция занимает только {round(used_w / (cx2 - cx) * 100)}% ширины области — "
                           f"растяни блоки на всю ширину {cx}…{cx2}")
        return out[:8]

    def describe(self, els: list[El]) -> list[dict]:
        """Элементы обратно в px — для критика."""
        k = self.k
        inv = {v: r for r, v in self.colors.items()}
        res = []
        for e in els:
            b = e.box
            d: dict[str, Any] = {"x": round(b.x / k), "y": round(b.y / k), "w": round(b.w / k), "h": round(b.h / k)}
            if e.kind == "text":
                d.update(type="text", text="\n".join(("• " if p.bullet else "") + p.text for p in e.paras),
                         style=e.role.replace("dg-", "") if e.role.startswith("dg-") else _style_of(e.role),
                         color=inv.get(e.color or "", "text"), align=e.align, valign=e.valign, bold=e.bold,
                         size_pt=round(e.size or 0, 1))
            elif e.kind == "shape":
                d.update(type="box", shape=e.geom, fill=inv.get(e.fill or "", "none"), line=inv.get(e.line or "", "none"))
            elif e.kind == "card":
                d.update(type="box", shape="rect", fill="surface", line="rule")
            elif e.kind == "line":
                x1, x2 = (d["x"] + d["w"], d["x"]) if e.flip_h else (d["x"], d["x"] + d["w"])
                y1, y2 = (d["y"] + d["h"], d["y"]) if e.flip_v else (d["y"], d["y"] + d["h"])
                d = {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": inv.get(e.line or "", "rule"),
                     "arrow": e.arrow, "dash": e.dash}
            elif e.kind == "icon":
                d = {"type": "icon", "x": d["x"], "y": d["y"], "size": d["w"], "name": e.icon, "color": inv.get(e.color or "", "primary")}
            else:
                continue
            res.append(d)
        return res


def _hit(a: Box, b: Box, frac: float = 0.0) -> bool:
    """Пересечение рамок; frac — доля меньшей площади, начиная с которой это наложение."""
    w = min(a.x2, b.x2) - max(a.x, b.x)
    h = min(a.y2, b.y2) - max(a.y, b.y)
    if w <= 0 or h <= 0:
        return False
    return w * h > frac * min(a.w * a.h, b.w * b.h)


def _style_of(role: str) -> str:
    """Роль элемента рецепта → стиль текста дизайн-системы (для опорной раскладки)."""
    return {"heading": "heading", "number": "number", "value": "big", "lead": "lead", "label": "label",
            "caption": "caption", "quote": "lead"}.get(role, "body")


def overlap_count(els: list[El]) -> int:
    """Наложения так же, как их считает детерминированный аудит: пересечение больше 3% меньшей площади,
    кроме вложенности в фигуру-подложку."""
    boxes = [e for e in els if e.kind in ("text", "shape", "icon") and e.box.w > 0 and e.box.h > 0]
    n = 0
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if not _hit(a.box, b.box, 0.03):
                continue
            if (a.kind == "shape" and _contains(a.box, b.box)) or (b.kind == "shape" and _contains(b.box, a.box)):
                continue
            n += 1
    return n


def _contains(outer: Box, inner: Box, tol: int = 12700 * 4) -> bool:
    return (inner.x >= outer.x - tol and inner.y >= outer.y - tol and inner.x2 <= outer.x2 + tol
            and inner.y2 <= outer.y2 + tol)


def _content(s: ContentSlide) -> str:
    out = []      # кикер уже стоит в шапке слайда — модели его не передаём, иначе она повторяет его в контенте
    if s.lead:
        out.append(f"Вводная фраза: {s.lead}")
    for i, it in enumerate(s.items, 1):
        parts = [x for x in (it.value, it.head, it.text) if x]
        out.append(f"{i}. " + " — ".join(parts) + (f" [иконка: {it.icon}]" if it.icon else ""))
    for c in s.columns:
        out.append(f"Колонка «{c.title}»: " + "; ".join(c.points))
    if s.quote:
        out.append(f"Главная мысль: {s.quote}")
    return "\n".join(out) or "(только заголовок — придумай визуальную поддержку без новых фактов)"


def content_box_of(profile: TemplateProfile, lay: SlideLayout) -> Box:
    """Область контента холста с учётом выросшего заголовка."""
    canvas = profile.canvas(lay.canvas)
    cb = canvas.content_box
    title = next((sl for sl in canvas.slots if sl.role == "title"), None)
    fill = next((sf for sf in lay.slots if sf.role == "title"), None)
    if title is not None and fill is not None and fill.h and title.box.y + fill.h > cb.y:
        top = title.box.y + fill.h + int(0.3 * profile.gap)
        cb = Box(x=cb.x, y=top, w=cb.w, h=max(1, cb.y2 - top))
    return cb


async def design_deck(content: DeckContent, layouts: list[SlideLayout], profile: TemplateProfile, run: SkillRun,
                      topic: str, attempts: int = 3, deadline: Optional[float] = None) -> dict[int, Design]:
    """Перерисовывает содержательные слайды варианта; возвращает {номер слайда: дизайн-система} для критика.

    deadline — к этому моменту новые попытки не начинаются, а начатые обрываются: слайд остаётся лучшей чистой
    попыткой или рецептом (обычный режим держит три колоды в пределах 5 минут даже на медленном инференсе)."""
    by_id = {s.id: s for s in content.slides}
    seen: dict[str, int] = {}
    todo = []
    keys: list[str] = []            # композиции по порядку колоды: соседние слайды не повторяют друг друга
    for lay in layouts:
        s = by_id.get(lay.content_id)
        canvas = profile.canvas(lay.canvas)
        if s is None or s.intent not in FREE_INTENTS or canvas.kind not in ("content", "agenda") or lay.clone_full \
                or s.why or s.then:      # слайд с блоком «и что?» верстает рецепт
            continue
        hints = HINTS.get(s.intent, [("свободная композиция по смыслу", "")])
        start = seen.get(s.intent, 0)
        recent = set(keys[-2:])
        hint = next((hints[(start + j) % len(hints)] for j in range(len(hints))
                     if hints[(start + j) % len(hints)][1] not in recent), hints[start % len(hints)])
        seen[s.intent] = start + 1
        keys.append(hint[1])
        d = Design(profile, canvas, content_box_of(profile, lay))
        d.intent = s.intent
        d.expect = [it.head for it in s.items if it.head] + [c.title for c in s.columns if c.title]
        todo.append((lay, s, d, hint))
    # что стоит на соседних слайдах — модель видит и не повторяет приём
    names = {lay.index: hint[0] for lay, _, _, hint in todo}

    def neighbors(i: int) -> str:
        near = [f"слайд {j}: {names[j]}" for j in (i - 2, i - 1, i + 1, i + 2) if j in names]
        return "; ".join(near) if near else "соседей с такой вёрсткой нет"

    designs: dict[int, Design] = {}

    async def one(lay: SlideLayout, s: ContentSlide, d: Design, hint: tuple[str, str]):
        # опорная раскладка — слайд рецепта в px: размеры текста в нём уже проверены по метрикам шрифта
        draft = json.dumps(d.describe([e for e in lay.elements if e.kind != "image"]), ensure_ascii=False)
        text, key = hint
        n_items = len(s.items) or len(s.columns) or 3
        sample = ff_examples.example(key, d.box, n_items)
        example = json.dumps(sample, ensure_ascii=False) if sample else "(образца нет — композиция по смыслу)"
        feedback = ""
        best: Optional[tuple[int, int, list[El]]] = None      # (проблем, попытка, элементы)
        for attempt in range(attempts):
            left = None if deadline is None else deadline - time.time()
            if left is not None and left < 8:
                break                     # время дизайнера вышло — остаётся лучшая попытка или рецепт
            try:
                raw = await asyncio.wait_for(run.call(
                    "slide_designer", **d.prompt_vars(), hint=text, example=example, icons=icons.icon_catalog_hint(),
                    topic=topic, n=lay.index, total=len(layouts), intent=s.intent, title=s.title,
                    content=_content(s), draft=draft[:5000], feedback=feedback, neighbors=neighbors(lay.index)), left)
                els = d.elements((raw or {}).get("elements", []), f"ff{lay.index}_")
            except asyncio.TimeoutError:
                log.info("designer slide %s: время вышло на попытке %s", lay.index, attempt + 1)
                break
            except Exception as e:      # сбой ответа — следующая попытка, а не сразу рецепт
                log.warning("designer slide %s attempt %s failed: %s", lay.index, attempt + 1, e)
                feedback = "ПРОШЛЫЙ ОТВЕТ НЕ РАЗОБРАН: верни корректный JSON {\"idea\": ..., \"elements\": [...]}, без пояснений."
                continue
            if not any(e.kind == "text" for e in els):
                feedback = "ПРОШЛАЯ ПОПЫТКА БЕЗ ТЕКСТА: на слайде должны быть все тезисы содержания."
                continue
            bad = d.repair(els)
            if bad:
                bad = d.salvage(els)          # доводка кодом: раздвинуть плашки и ряды
            problems = d.diagnose(els)
            sparse = any(("занимает только" in x) or ("пустой разрыв" in x) or ("мелким" in x) for x in problems)
            score = bad * 10 + 5 * len(d.orphans) + 5 * len(d.missing(els)) + (1 if sparse else 0)
            if best is None or score < best[0]:
                best = (score, attempt, els)
            if score == 0:
                break
            # следующая попытка — с конкретными замечаниями кода, а не «попробуй ещё»
            feedback = ("ПРОШЛАЯ ПОПЫТКА ОТКЛОНЕНА. Исправь именно это:\n- " + "\n- ".join(problems)
                        + "\nТвой прошлый вариант (после выравнивания по сетке):\n"
                        + json.dumps(d.describe(els), ensure_ascii=False)[:4000])
        if best is None or best[0] >= 10:
            # крайний случай: ни одна попытка не стала чистой — слайд остаётся рецептом
            log.info("designer slide %s: чистого варианта нет за %s попыток — рецепт", lay.index, attempts)
            lay.warnings.append("freeform_fallback")
            return
        els = best[2]
        image = [e for e in lay.elements if e.kind == "image"]
        lay.elements = els + image
        lay.recipe = "freeform"
        lay.warnings = [w for w in lay.warnings if w != "text_overflow"]
        designs[lay.index] = d

    await asyncio.gather(*(one(*t) for t in todo))
    return designs


async def critique(layouts: list[SlideLayout], designs: dict[int, Design], pngs: list[Path], run: SkillRun) -> list[int]:
    """Критик смотрит на отрендеренный слайд и возвращает исправленные элементы. Номера исправленных слайдов."""
    changed: list[int] = []

    async def one(lay: SlideLayout):
        d = designs.get(lay.index)
        if d is None or lay.index - 1 >= len(pngs):
            return
        cx, cy, cx2, cy2 = d.box
        mine = [e for e in lay.elements if e.role.startswith("dg-")]
        try:
            diag = d.diagnose(mine)
            raw = await run.call("slide_critic", images=[pngs[lay.index - 1]], cx=cx, cy=cy, cx2=cx2, cy2=cy2,
                                 elements=json.dumps(d.describe(mine), ensure_ascii=False),
                                 diagnostics="; ".join(diag) if diag else "проблем не найдено")
        except Exception as e:
            log.warning("critic slide %s failed: %s", lay.index, e)
            return
        if not isinstance(raw, dict) or raw.get("ok") or not raw.get("elements"):
            return
        els = d.elements(raw["elements"], f"fc{lay.index}_")
        if d.repair(els) or overlap_count(els) > overlap_count(mine):
            return      # критик не должен делать хуже
        if len([e for e in els if e.kind == "text"]) >= max(1, len([e for e in mine if e.kind == "text"]) // 2):
            lay.elements = els + [e for e in lay.elements if e.kind == "image"]
            changed.append(lay.index)

    await asyncio.gather(*(one(l) for l in layouts))
    return sorted(changed)

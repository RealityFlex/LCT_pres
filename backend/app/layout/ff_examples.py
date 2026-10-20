"""Образцы композиций для послайдового дизайна (как справочники в скилле Kimi).

Каждый генератор строит правильную раскладку композиции под область контента и число пунктов: геометрия
выверена по сетке 8 px, тексты-заглушки короткие. Модель получает образец вместе с подсказкой и наполняет его
смыслом слайда, а не придумывает геометрию с нуля — так меньше наложений и пустот.
"""
from __future__ import annotations

from typing import Callable


def _g(v: float) -> int:
    return int(round(v / 8.0) * 8)


def _t(x, y, w, h, text, style="body", color="text", **kw) -> dict:
    return {"type": "text", "x": _g(x), "y": _g(y), "w": _g(w), "h": _g(h), "text": text, "style": style,
            "color": color, **kw}


def _b(x, y, w, h, fill="surface", line="none", shape="rect", radius=0) -> dict:
    d = {"type": "box", "x": _g(x), "y": _g(y), "w": _g(w), "h": _g(h), "shape": shape, "fill": fill, "line": line}
    if radius:
        d["radius"] = radius
    return d


def _l(x1, y1, x2, y2, color="rule", arrow=False, width=1) -> dict:
    return {"type": "line", "x1": _g(x1), "y1": _g(y1), "x2": _g(x2), "y2": _g(y2), "color": color, "arrow": arrow,
            "width": width}


def chevrons(cx, cy, cw, ch, n):
    n = max(3, min(6, n))
    gap = 8
    w = (cw - gap * (n - 1)) / n
    out = []
    for i in range(n):
        x = cx + i * (w + gap)
        fill = "accent" if i == n - 1 else "primary"
        out.append(_b(x, cy + 16, w, 64, fill=fill, shape="chevron" if i else "homePlate"))
        out.append(_t(x + 24, cy + 32, w - 48, 32, f"Шаг {i + 1}", "label", "white", align="ctr", valign="ctr"))
        out.append(_t(x, cy + 104, w - 8, 32, "Короткое название", "heading"))
        out.append(_t(x, cy + 144, w - 8, min(ch - 160, 120), "Пояснение шага в одно-два предложения.", "body", "muted"))
    return out


def rows(cx, cy, cw, ch, n):
    n = max(2, min(6, n))
    rh = min(96, ch / n)
    out = []
    for i in range(n):
        y = cy + i * rh
        out.append(_t(cx, y + 8, 64, 40, f"0{i + 1}", "number", "accent" if i == 0 else "primary"))
        out.append(_t(cx + 88, y + 8, cw * 0.32, 32, "Тезис строки", "heading"))
        out.append(_t(cx + 88 + cw * 0.34, y + 8, cw - 88 - cw * 0.34, rh - 24, "Пояснение тезиса одной-двумя строками.", "body", "muted"))
        if i < n - 1:
            out.append(_l(cx, y + rh - 4, cx + cw, y + rh - 4))
    return out


def grid(cx, cy, cw, ch, n):
    n = max(3, min(6, n))
    cols = 2 if n <= 4 else 3
    rws = (n + cols - 1) // cols
    gap = 24
    w = (cw - gap * (cols - 1)) / cols
    h = min(200, (ch - gap * (rws - 1)) / rws)
    out = []
    for i in range(n):
        x = cx + (i % cols) * (w + gap)
        y = cy + (i // cols) * (h + gap)
        out.append(_b(x, y, w, h, fill="surface", radius=8, shape="roundRect"))
        out.append({"type": "icon", "x": _g(x + 24), "y": _g(y + 24), "size": 32, "name": "check", "color": "primary"})
        out.append(_t(x + 72, y + 24, w - 96, 32, "Название блока", "heading"))
        out.append(_t(x + 72, y + 64, w - 96, h - 88, "Пояснение блока одной-двумя строками.", "body", "muted"))
    return out


def columns(cx, cy, cw, ch, n):
    n = max(2, min(5, n))
    gap = 32
    w = (cw - gap * (n - 1)) / n
    out = []
    for i in range(n):
        x = cx + i * (w + gap)
        out.append({"type": "icon", "x": _g(x), "y": _g(cy + 8), "size": 40, "name": "star", "color": "accent" if i == 0 else "primary"})
        out.append(_t(x, cy + 72, w, 32, "Название", "heading"))
        out.append(_t(x, cy + 112, w, min(ch - 120, 160), "Пояснение одним-двумя предложениями.", "body", "muted"))
        if i:
            out.append(_l(x - gap / 2, cy + 8, x - gap / 2, cy + min(ch, 280)))
    return out


def timeline(cx, cy, cw, ch, n):
    n = max(3, min(6, n))
    y = cy + ch * 0.38
    step = cw / n
    out = [_l(cx, y, cx + cw, y, "primary", width=2)]
    for i in range(n):
        x = cx + i * step + step / 2
        out.append(_b(x - 8, y - 8, 16, 16, fill="accent" if i == n - 1 else "primary", shape="ellipse"))
        out.append(_t(x - step / 2 + 8, y - 64, step - 16, 40, "Период", "number", "primary", align="ctr"))
        out.append(_t(x - step / 2 + 8, y + 24, step - 16, 32, "Веха", "heading", align="ctr"))
        out.append(_t(x - step / 2 + 8, y + 60, step - 16, min(120, cy + ch - y - 64), "Что произошло.", "body", "muted", align="ctr"))
    return out


def bignums(cx, cy, cw, ch, n):
    n = max(2, min(4, n))
    w = cw / n
    out = []
    for i in range(n):
        x = cx + i * w
        out.append(_t(x + 16, cy + ch * 0.18, w - 32, 72, "42%", "big", "accent" if i == 0 else "primary"))
        out.append(_t(x + 16, cy + ch * 0.18 + 88, w - 32, 32, "Что измеряем", "heading"))
        out.append(_t(x + 16, cy + ch * 0.18 + 128, w - 32, 80, "Пояснение к цифре.", "body", "muted"))
        if i:
            out.append(_l(x, cy + ch * 0.12, x, cy + ch * 0.82))
    return out


def compare(cx, cy, cw, ch, n):
    w = (cw - 48) / 2
    out = []
    for i, (fill, head) in enumerate((("surface", "Было"), ("primary", "Стало"))):
        x = cx + i * (w + 48)
        out.append(_b(x, cy, w, 56, fill=fill))
        out.append(_t(x + 24, cy + 12, w - 48, 32, head, "heading", "white" if fill == "primary" else "heading", valign="ctr"))
        out.append(_t(x + 24, cy + 80, w - 48, ch - 96, "• первый пункт\n• второй пункт\n• третий пункт", "body", bullets=True))
    out.append(_l(cx + w + 24, cy, cx + w + 24, cy + ch - 16))
    return out


def statement(cx, cy, cw, ch, n):
    lw = cw * 0.58
    return [_t(cx, cy + 24, lw, ch * 0.5, "Главная мысль слайда — крупно, в две-три строки", "lead", "heading"),
            _l(cx, cy + ch * 0.5 + 40, cx + 64, cy + ch * 0.5 + 40, "accent", width=3),
            _b(cx + lw + 40, cy, cw - lw - 40, ch - 16, fill="primary"),
            _t(cx + lw + 64, cy + 24, cw - lw - 88, ch - 64, "Опорные факты или пояснение к мысли.", "body", "white")]


def flow(cx, cy, cw, ch, n):
    n = max(3, min(6, n))
    per = (n + 1) // 2
    gap = 48
    w = (cw - gap * (per - 1)) / per
    h = min(120, (ch - 48) / 2)
    out = []
    for i in range(n):
        r, c = divmod(i, per)
        x = cx + c * (w + gap)
        y = cy + r * (h + 48)
        out.append(_b(x, y, w, h, fill="accent" if i == n - 1 else "surface", radius=8, shape="roundRect"))
        out.append(_t(x + 16, y + 16, w - 32, 32, f"{i + 1}. Этап", "heading", "white" if i == n - 1 else "heading"))
        out.append(_t(x + 16, y + 52, w - 32, h - 64, "Что происходит на этапе.", "body", "white" if i == n - 1 else "muted"))
        if c < per - 1 and i < n - 1:
            out.append(_l(x + w + 8, y + h / 2, x + w + gap - 8, y + h / 2, "primary", arrow=True))
    return out


def bento(cx, cy, cw, ch, n):
    """Главный пункт — большая плашка primary слева, остальные — стопкой справа."""
    n = max(2, min(4, n))
    gap = 24
    lw = cw * 0.46
    rw = cw - lw - gap
    out = [_b(cx, cy, lw, ch - 16, fill="primary", radius=12, shape="roundRect"),
           {"type": "icon", "x": _g(cx + 32), "y": _g(cy + 32), "size": 48, "name": "star", "color": "white"},
           _t(cx + 32, cy + 104, lw - 64, 72, "Главный пункт", "lead", "white"),
           _t(cx + 32, cy + 184, lw - 64, ch - 232, "Пояснение главного пункта двумя-тремя строками.", "body", "white")]
    k = n - 1
    h = (ch - 16 - gap * (k - 1)) / k
    for i in range(k):
        y = cy + i * (h + gap)
        out.append(_b(cx + lw + gap, y, rw, h, fill="surface", radius=12, shape="roundRect"))
        out.append({"type": "icon", "x": _g(cx + lw + gap + 24), "y": _g(y + 24), "size": 32, "name": "check", "color": "primary"})
        out.append(_t(cx + lw + gap + 72, y + 24, rw - 96, 32, "Пункт", "heading"))
        out.append(_t(cx + lw + gap + 72, y + 60, rw - 96, h - 76, "Пояснение одной строкой.", "body", "muted"))
    return out


def numbered(cx, cy, cw, ch, n):
    """Крупные номера 01–0N над колонками текста, тонкая линия под номером."""
    n = max(2, min(4, n))
    gap = 40
    w = (cw - gap * (n - 1)) / n
    out = []
    for i in range(n):
        x = cx + i * (w + gap)
        out.append(_t(x, cy + 16, w, 72, f"{i + 1:02d}", "big", "accent" if i == 0 else "primary"))
        out.append(_l(x, cy + 104, x + w, cy + 104, "rule"))
        out.append(_t(x, cy + 128, w, 32, "Название", "heading"))
        out.append(_t(x, cy + 168, w, min(ch - 176, 160), "Пояснение одним-двумя предложениями.", "body", "muted"))
    return out


def split(cx, cy, cw, ch, n):
    """Вводная мысль слева на тёмной плашке, справа — список пунктов с иконками и разделителями."""
    lw = cw * 0.38
    out = [_b(cx, cy, lw, ch - 16, fill="dark", radius=12, shape="roundRect"),
           _t(cx + 32, cy + 32, lw - 64, ch - 96, "Короткий вывод или вопрос, который раскрывают пункты справа", "lead", "white")]
    n = max(2, min(5, n))
    x = cx + lw + 40
    w = cw - lw - 40
    h = (ch - 16) / n
    for i in range(n):
        y = cy + i * h
        out.append({"type": "icon", "x": _g(x), "y": _g(y + 12), "size": 32, "name": "check", "color": "accent" if i == 0 else "primary"})
        out.append(_t(x + 48, y + 12, w - 48, 32, "Пункт", "heading"))
        out.append(_t(x + 48, y + 48, w - 48, h - 64, "Пояснение пункта одной строкой.", "body", "muted"))
        if i < n - 1:
            out.append(_l(x, y + h - 8, x + w, y + h - 8))
    return out


EXAMPLES: dict[str, Callable] = {"chevrons": chevrons, "rows": rows, "grid": grid, "columns": columns,
                                 "timeline": timeline, "bignums": bignums, "compare": compare, "statement": statement,
                                 "flow": flow, "bento": bento, "numbered": numbered, "split": split}


def example(key: str, box: tuple[int, int, int, int], n: int) -> list[dict]:
    cx, cy, cx2, cy2 = box
    fn = EXAMPLES.get(key)
    return fn(cx, cy, cx2 - cx, cy2 - cy, n) if fn else []

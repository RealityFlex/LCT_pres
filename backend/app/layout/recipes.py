"""Композер: раскладывает контент слайда по рецепту внутри контентной области холста.

Все размеры — производные от токенов шаблона (поля, шаг сетки, шкала кеглей),
поэтому один и тот же рецепт выглядит «родным» в любом шаблоне.
"""
from __future__ import annotations

import math
import re
from typing import Optional

from ..parsing.model import Box, Canvas, Slot, TemplateProfile
from ..planning.models import ContentSlide, Item, SlideSpec
from . import textfit as tf
from .ir import El, P, Run, SlideLayout, SlotFill
from ..parsing.ooxml import contrast
from .style import CardChoice, Look, mix, readable

INCH = 914400
GENERIC_CAPTION = re.compile(r"^(итог|итоги|вывод|выводы|главное|главный вывод|резюме|мысль|ключевая мысль|суть|результат|результаты|подпись|цитата)\W*$", re.I)


def min_contrast(size: float, bold: bool) -> float:
    """WCAG 2.1: крупный текст (≥18pt или ≥14pt полужирный) — 3:1, остальной — 4.5:1."""
    return 3.0 if (size >= 18 or (bold and size >= 14)) else 4.5


def _slot_color(sl: Slot, size: float, look: Look) -> Optional[str]:
    """None — оставить цвет шаблона; иначе — читаемая замена при недостаточном контрасте."""
    bg = sl.bg or look.bg
    need = min_contrast(size or sl.style.size, sl.style.bold)
    if contrast(sl.style.color, bg) >= need:
        return None
    pal = look.p.palette
    return readable([pal.text_light, pal.text_dark, look.heading, look.fg], bg, need)


def _usable_slot_fonts(canvas: Canvas, look: Look) -> Canvas:
    """Копия холста, где у слотов со шрифтом без кириллицы гарнитура заменена на рабочую гарнитуру шаблона."""
    from ..parsing import fonts as _f
    bad = [sl for sl in canvas.slots if sl.style.font and not _f.font_available(sl.style.font)]
    if not bad:
        return canvas
    c = canvas.model_copy(deep=True)
    for sl in c.slots:
        if sl.style.font and not _f.font_available(sl.style.font):
            sl.style.font = look.heading_font if sl.role in ("title", "kicker", "number") else look.body_font
    return c


def _split_title(t: str) -> tuple[str, str]:
    for sep in (": ", " — ", " – ", ". ", ", "):
        if sep in t:
            a, b = t.split(sep, 1)
            if len(a) >= 8 and len(b) >= 6:
                return a.strip(), b.strip()
    return t, ""


class Composer:
    def __init__(self, profile: TemplateProfile):
        self.p = profile
        self._n = 0

    # ================================================================= helpers
    def _id(self, prefix: str = "e") -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def _paras(self, texts: list[str], bullet: bool = False, bold_head: bool = False) -> list[P]:
        return [P(runs=[Run(text=t)], bullet=bullet) for t in texts if t is not None]

    def text(self, look: Look, box: Box, paras: list[P], role: str, font: str, pref: float, minimum: float,
             color: str, bold: bool = False, align: str = "l", valign: str = "t", space_k: float = 0.0,
             max_lines: Optional[int] = None, line_spacing: float = 1.0, caps: bool = False,
             parent: Optional[str] = None) -> El:
        if role in ("number", "label"):
            for p in paras:
                for r in p.runs:
                    r.text = r.text.replace(" ", " ")
        items = [(p.text.upper() if caps else p.text, bold if not any(r.bold for r in p.runs) else True) for p in paras]
        size, ok = tf.fit_size(items, box.w, box.h, font, look.scale, pref, minimum, line_spacing, space_k, max_lines)
        for p in paras:
            p.space_after = round(space_k * size, 1)
        return El(id=self._id("t"), kind="text", box=box, role=role, paras=paras, font=font, size=size, color=color,
                  bold=bold, align=align, valign=valign, line_spacing=line_spacing, overflow=not ok, caps=caps,
                  parent=parent)

    def pad(self, look: Look) -> int:
        return int(max(0.1 * INCH * look.k, min(0.26 * INCH * look.k, 0.7 * look.gap)))

    # ================================================================= slots
    def fill_slots(self, spec: SlideSpec, canvas: Canvas, look: Look, lay: SlideLayout, number: int,
                   deck_title: str = "", extras: Optional[dict] = None) -> Box:
        """Заполняет слоты холста. Возвращает (возможно скорректированную) контентную область."""
        orig_fonts = {sl.sid: sl.style.font for sl in canvas.slots}
        canvas = _usable_slot_fonts(canvas, look)
        s = spec.slide
        extras = extras or {}
        cb = canvas.content_box.model_copy()
        title_slot = next((sl for sl in canvas.slots if sl.role == "title"), None)
        used = set()
        structural = canvas.kind in ("title", "section", "closing")
        if title_slot is not None:
            used.add(title_slot.sid)
            st = title_slot.style
            caps = st.caps or look.title_caps
            text = s.title.upper() if look.title_caps and not st.caps else s.title
            box = title_slot.box
            inset = 91440
            w = max(1, box.w - 2 * inset)
            if canvas.title_max_w and canvas.title_max_w < box.w:
                w = max(int(0.3 * box.w), canvas.title_max_w - 2 * inset)
            single = canvas.title_label_sid is not None
            max_h = box.h
            if not structural and not single:
                max_h = max(box.h, cb.y - box.y - int(0.25 * look.gap))
            lines = 1 if single else (3 if structural else 2)
            minimum = max(look.min_size, st.size * (0.55 if structural else 0.72))
            ls = st.line_spacing or 1.0

            def _fit(t):
                return tf.fit_size([(t.upper() if caps else t, st.bold)], w, max_h, st.font, look.scale + [st.size],
                                   st.size, minimum, ls, 0.0, lines)

            size, ok = _fit(text)
            has_sub = any(sl.role == "subtitle" for sl in canvas.slots)
            if not ok and structural and has_sub and not extras.get("subtitle_locked"):
                head, tail = _split_title(text)
                if tail:
                    text = head
                    extras["subtitle"] = tail[:1].upper() + tail[1:]
                    size, ok = _fit(text)
            sf = SlotFill(role="title", sid=title_slot.sid, text=text, size=size if size != st.size else None,
                          color=_slot_color(title_slot, size, look))
            lay.slots.append(sf)
            if not ok:
                lay.warnings.append("title_overflow")
            if w < box.w - 2 * inset:
                sf.w = w + 2 * inset
            if single and canvas.title_label_sid:
                lay.label_width = tf.text_width(text.upper() if caps else text, st.font, size, st.bold)
            # фактическая высота заголовка → если он вырос, сдвигаем контент
            need = tf.needed_height([(text.upper() if caps else text, st.bold)], w, st.font, size, ls) + 2 * 45720
            if not structural and need > box.h:
                sf.h = int(need)
            if not structural and box.y + need + int(0.3 * look.gap) > cb.y:
                shift = box.y + need + int(0.3 * look.gap) - cb.y
                cb = Box(x=cb.x, y=cb.y + shift, w=cb.w, h=max(1, cb.h - shift))
        for sl in canvas.slots:
            if sl.sid in used:
                continue
            if sl.role == "pagenum":
                lay.slots.append(SlotFill(role="pagenum", sid=sl.sid, text=str(number), color=_slot_color(sl, sl.style.size, look)))
            elif sl.role == "kicker":
                k = s.kicker
                if not k and canvas.kind == "section":
                    k = f"Раздел {extras.get('number', '')}".strip()
                elif not k and canvas.kind == "closing":
                    k = "Итоги"
                elif not k:
                    k = s.section or ""
                if k:
                    lay.slots.append(SlotFill(role="kicker", sid=sl.sid, text=k.upper() if sl.style.caps or sl.text.isupper() else k,
                                              color=_slot_color(sl, sl.style.size, look)))
                else:
                    lay.remove_sids.append(sl.sid)
            elif sl.role == "subtitle":
                t = s.lead or extras.get("subtitle", "")
                if t:
                    grow_h = max(sl.box.h, int(sl.style.size * 12700 * 1.25 * 3))
                    size, _ = tf.fit_size([(t, sl.style.bold)], sl.box.w - 182880, grow_h,
                                          sl.style.font, look.scale, sl.style.size, max(look.min_size, sl.style.size * 0.75), max_lines=3)
                    need = tf.needed_height([(t, sl.style.bold)], sl.box.w - 182880, sl.style.font, size) + 91440
                    lay.slots.append(SlotFill(role="subtitle", sid=sl.sid, text=t, size=size if size != sl.style.size else None,
                                              color=_slot_color(sl, size, look), h=int(need) if need > sl.box.h else None))
                else:
                    lay.remove_sids.append(sl.sid)
            elif sl.role == "number":
                t = extras.get("number", "")
                if t:
                    lay.slots.append(SlotFill(role="number", sid=sl.sid, text=t))
                else:
                    lay.remove_sids.append(sl.sid)
            elif sl.role == "body":
                pts = [it.head or it.text for it in s.items][:5] or ([s.lead] if s.lead else [])
                if pts:
                    size, _ = tf.fit_size([(t, False) for t in pts], sl.box.w - 182880, int(sl.box.h * 1.15), sl.style.font,
                                          look.scale, sl.style.size, max(look.min_size, sl.style.size * 0.75), space_after_k=0.5)
                    need = tf.needed_height([(t, False) for t in pts], sl.box.w - 182880, sl.style.font, size,
                                            sl.style.line_spacing, 0.5) + 91440
                    lay.slots.append(SlotFill(role="body", sid=sl.sid, text="\n".join(pts), paras=pts,
                                              size=size if size != sl.style.size else None, color=_slot_color(sl, size, look),
                                              h=int(need) if need > sl.box.h else None))
                else:
                    lay.remove_sids.append(sl.sid)
            elif sl.role == "meta":
                t = extras.get("meta", "")
                if t:
                    lay.slots.append(SlotFill(role="meta", sid=sl.sid, text=t, color=_slot_color(sl, sl.style.size, look)))
                    extras["meta"] = ""   # одна строка метаданных — в первый слот
                else:
                    lay.remove_sids.append(sl.sid)
        for sf in lay.slots:
            new = next((sl.style.font for sl in canvas.slots if sl.sid == sf.sid), None)
            if new and new != orig_fonts.get(sf.sid):
                sf.font = new
        return cb

    # ================================================================= entry
    def compose(self, spec: SlideSpec, canvas: Canvas, index: int, deck_title: str = "",
                extras: Optional[dict] = None) -> SlideLayout:
        if spec.recipe == "pattern" and canvas.kind != "pattern":
            spec = spec.model_copy(update={"recipe": spec.opts.get("fallback", "cards")})
        look = Look(self.p, canvas)
        lay = SlideLayout(index=index, content_id=spec.slide.id, canvas=canvas.id, recipe=spec.recipe, intent=spec.slide.intent,
                          notes=spec.slide.notes)
        cb = self.fill_slots(spec, canvas, look, lay, index, deck_title, extras)
        if canvas.kind == "pattern":
            from .patterns import PatternFiller
            if not hasattr(self, "_pf"):
                self._pf = PatternFiller(self.p, self)
            self._pf.fill(spec, canvas, lay, look)
            return lay
        if canvas.kind in ("title", "section", "closing") and spec.recipe in ("title", "section", "closing", "clone"):
            return lay
        s = spec.slide
        # вводный абзац над контентом
        if s.lead and spec.recipe not in ("quote", "section_synth", "image_text"):
            lead_h = int(min(0.22 * cb.h, look.body_size * 1.35 * 2.3 * 12700))
            size_pref = look.snap_up(look.body_size * 1.15)
            el = self.text(look, Box(x=cb.x, y=cb.y, w=int(cb.w * 0.8), h=lead_h), self._paras([s.lead]), "lead",
                           look.body_font, size_pref, look.body_size, look.fg, max_lines=2)
            need = tf.needed_height([(s.lead, False)], el.box.w, look.body_font, el.size)
            el.box.h = min(lead_h, need)
            lay.elements.append(el)
            off = el.box.h + int(0.9 * look.gap)
            cb = Box(x=cb.x, y=cb.y + off, w=cb.w, h=max(1, cb.h - off))
        fn = getattr(self, f"r_{spec.recipe}", None) or self.r_bullets
        fn(spec, look, cb, lay)
        return lay

    def compose_best(self, spec: SlideSpec, index: int, deck_title: str = "", extras: Optional[dict] = None) -> SlideLayout:
        """Основной холст, при переполнении заголовка/текста — запасные (например, без однострочной плашки)."""
        tried = []
        for cid in [spec.canvas] + list(spec.alts):
            try:
                canvas = self.p.canvas(cid)
            except KeyError:
                continue
            lay = self.compose(spec, canvas, index, deck_title, dict(extras or {}))
            bad = ("title_overflow" in lay.warnings) * 10 + sum(1 for e in lay.elements if e.overflow) + 3 * len(lay.overflows)
            if bad == 0:
                return lay
            tried.append((bad, len(tried), lay))
        tried.sort(key=lambda t: (t[0], t[1]))
        return tried[0][2]

    # ================================================================= recipes
    def _items(self, s: ContentSlide, limit: int = 6) -> list[Item]:
        return [it for it in s.items if (it.head or it.text or it.value)][:limit]

    # ---------------------------------------------------------------- cards
    def _card_parts_height(self, look: Look, it: Item, inner_w: int, hs: float, bs: float, icon_h: int,
                           show_icon: bool, show_num: bool, num_size: float) -> int:
        h = 0
        gap_s = int(0.45 * look.gap)
        if show_icon and it.icon:
            h += icon_h + gap_s
        if show_num:
            h += tf.needed_height([(it.value or "00", True)], inner_w, look.number_font, num_size) + int(0.2 * look.gap)
        if it.head:
            h += tf.needed_height([(it.head, True)], inner_w, look.heading_font, hs) + int(0.25 * look.gap)
        if it.text:
            h += tf.needed_height([(it.text, False)], inner_w, look.body_font, bs, 1.0)
        return h

    def r_cards(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout, accent_first: bool = False):
        s = spec.slide
        items = self._items(s, 6)
        if not items:
            return self.r_quote(spec, look, cb, lay)
        n = len(items)
        cols = n if n <= 4 else math.ceil(n / 2)
        rows = 1 if n <= 4 else 2
        g = look.gap
        cw = (cb.w - (cols - 1) * g) // cols
        max_ch = (cb.h - (rows - 1) * g) // rows
        pad = self.pad(look)
        inner_w = cw - 2 * pad
        show_icon = spec.opts.get("icons", True) and any(it.icon for it in items)
        show_num = spec.opts.get("numbers", False) or all(it.value for it in items)
        icon_h = int(min(0.5 * INCH * look.k, max(0.3 * INCH * look.k, cw * 0.16)))
        hs_pref = max(look.heading_size, look.snap_up(look.body_size * 1.2))
        num_pref = look.snap_down(min(look.number_size, 36 * look.k * 1.3))
        best = None
        for hs, bs in look.pairs(heads=[it.head for it in items], bodies=[it.text for it in items], width=inner_w):
            need = max(self._card_parts_height(look, it, inner_w, hs, bs, icon_h, show_icon, show_num, num_pref)
                       for it in items) + 2 * pad
            if need <= max_ch * 0.92:
                best = (hs, bs, need)
                break
        overflow = best is None
        if best is None:
            best = (look.min_size, look.min_size, max_ch)
        hs, bs, need = best
        fill_k = 0.85 if spec.opts.get("fill") else 0.62
        ch = int(min(max_ch, max(need, fill_k * max_ch if rows == 1 else need)))
        total_h = rows * ch + (rows - 1) * g
        y0 = cb.y + int((cb.h - total_h) * 0.25)
        accent_idx = spec.opts.get("accent_index")
        for i, it in enumerate(items):
            r, c = divmod(i, cols)
            cols_in_row = cols if r < rows - 1 or n % cols == 0 else n % cols
            row_w = cols_in_row * cw + (cols_in_row - 1) * g
            x = cb.x + (cb.w - row_w) // 2 + c * (cw + g) if rows > 1 else cb.x + c * (cw + g)
            y = y0 + r * (ch + g)
            cc = look.card(accent=(accent_idx == i))
            card = El(id=self._id("c"), kind="card", box=Box(x=x, y=y, w=cw, h=ch), card=cc.index, fill=cc.fill,
                      line=cc.line, geom="roundRect", role="card")
            lay.elements.append(card)
            yy = y + pad
            if show_icon and it.icon:
                lay.elements.extend(self._icon_badge(look, cc, Box(x=x + pad, y=yy, w=icon_h, h=icon_h), it.icon, card.id))
                yy += icon_h + int(0.45 * look.gap)
            if show_num:
                nh = tf.needed_height([(it.value or f"{i + 1:02d}", True)], inner_w, look.number_font, num_pref)
                lay.elements.append(self.text(look, Box(x=x + pad, y=yy, w=inner_w, h=nh), self._paras([it.value or f"{i + 1:02d}"]),
                                              "number", look.number_font, num_pref, look.min_size, cc.accent, bold=True, parent=card.id))
                yy += nh + int(0.2 * look.gap)
            if it.head:
                hh = tf.needed_height([(it.head, True)], inner_w, look.heading_font, hs)
                lay.elements.append(self.text(look, Box(x=x + pad, y=yy, w=inner_w, h=hh), self._paras([it.head]), "heading",
                                              look.heading_font, hs, hs, cc.heading, bold=True, parent=card.id))
                yy += hh + int(0.25 * look.gap)
            if it.text:
                bh = max(1, y + ch - pad - yy)
                el = self.text(look, Box(x=x + pad, y=yy, w=inner_w, h=bh), self._paras([it.text]), "body",
                               look.body_font, bs, bs, cc.muted if cc.muted else cc.text, parent=card.id)
                el.overflow = el.overflow or overflow
                lay.elements.append(el)

    def _icon_badge(self, look: Look, cc: Optional[CardChoice], box: Box, icon: str, parent: Optional[str]) -> list[El]:
        surf = cc.surface if cc else look.bg
        acc = cc.accent if cc else look.accent
        circle_fill = mix(surf, acc, 0.14)
        inner = int(box.w * 0.56)
        off = (box.w - inner) // 2
        return [
            El(id=self._id("b"), kind="shape", geom="ellipse", box=box, fill=circle_fill, role="icon_bg", parent=parent),
            El(id=self._id("i"), kind="icon", box=Box(x=box.x + off, y=box.y + off, w=inner, h=inner), icon=icon,
               color=acc, role="icon", parent=parent),
        ]

    # ---------------------------------------------------------------- rows (нумерованный список)
    def r_rows(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        items = self._items(spec.slide, 6)
        if not items:
            return self.r_quote(spec, look, cb, lay)
        n = len(items)
        g = int(look.gap * 0.6)
        row_h = (cb.h - (n - 1) * g) // n
        if not spec.opts.get("fill"):
            row_h = min(row_h, int(1.25 * INCH * look.k))
        total = n * row_h + (n - 1) * g
        y0 = cb.y + int((cb.h - total) * 0.2)
        num_w = int(max(0.55 * INCH * look.k, cb.w * 0.06))
        head_w = int(cb.w * 0.34)
        text_x = cb.x + num_w + head_w + look.gap
        text_w = cb.x2 - text_x
        hs_pref = max(look.heading_size, look.snap_up(look.body_size * 1.2))
        # единый кегль для всех строк
        hs, bs = look.min_size, look.min_size
        for cand_h, cand_b in look.pairs(heads=[it.head or it.text for it in items], bodies=[it.text for it in items if it.head],
                                         width=head_w - look.gap // 2, body_width=text_w):
            if (all(tf.fits([(it.head or it.text, True)], head_w - look.gap // 2, row_h, look.heading_font, cand_h) for it in items)
                    and all(tf.fits([(it.text, False)], text_w, row_h, look.body_font, cand_b) for it in items if it.text and it.head)):
                hs, bs = cand_h, cand_b
                break
        num_size = look.snap_down(min(look.number_size * 0.6, hs * 1.6))
        line_col = mix(look.bg, look.fg, 0.18)
        for i, it in enumerate(items):
            y = y0 + i * (row_h + g)
            short = it.value if it.value and len(it.value) <= 4 else f"{i + 1:02d}"
            if it.value and len(it.value) > 4:
                it = it.model_copy(update={"text": f"{it.value}. {it.text}" if it.text else it.value})
            lay.elements.append(self.text(look, Box(x=cb.x, y=y, w=num_w, h=row_h), self._paras([short]),
                                          "number", look.number_font, num_size, look.min_size, look.accent, bold=True, max_lines=1))
            lay.elements.append(self.text(look, Box(x=cb.x + num_w, y=y, w=head_w - look.gap // 2, h=row_h),
                                          self._paras([it.head or it.text]), "heading", look.heading_font, hs, hs,
                                          look.heading, bold=True))
            if it.text and it.head:
                lay.elements.append(self.text(look, Box(x=text_x, y=y, w=text_w, h=row_h), self._paras([it.text]), "body",
                                              look.body_font, bs, bs, look.muted))
            if i < n - 1:
                ly = y + row_h + g // 2
                lay.elements.append(El(id=self._id("l"), kind="line", box=Box(x=cb.x, y=ly, w=cb.w, h=0),
                                       line=line_col, line_w=0.75, role="divider"))

    r_agenda = r_rows

    # ---------------------------------------------------------------- bullets (иконки + текст)
    def r_bullets(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        items = self._items(spec.slide, 6)
        if not items:
            return self.r_quote(spec, look, cb, lay)
        n = len(items)
        two_col = n >= 5 or (n == 4 and spec.opts.get("two_col"))
        cols = 2 if two_col else 1
        per_col = math.ceil(n / cols)
        g = look.gap
        col_w = (cb.w - (cols - 1) * 2 * g) // cols if cols > 1 else int(cb.w * (0.78 if spec.slide.image is None else 0.52))
        row_h = (cb.h - (per_col - 1) * int(0.7 * g)) // per_col
        row_h = min(row_h, int(1.3 * INCH * look.k))
        icon = int(min(0.5 * INCH * look.k, max(0.34 * INCH * look.k, row_h * 0.5)))
        show_icon = any(it.icon for it in items)
        tx_off = (icon + int(0.8 * g)) if show_icon else 0
        text_w = col_w - tx_off
        hs_pref = max(look.heading_size, look.snap_up(look.body_size * 1.2))
        best = (look.min_size, look.min_size)
        found = False
        for hs, bs in look.pairs(heads=[it.head for it in items], bodies=[it.text for it in items], width=text_w):
            if all(tf.needed_height([(it.head, True)], text_w, look.heading_font, hs) * (1 if it.head else 0)
                   + tf.needed_height([(it.text, False)], text_w, look.body_font, bs) * (1 if it.text else 0)
                   + int(0.15 * g) <= row_h for it in items):
                best, found = (hs, bs), True
                break
        hs, bs = best
        total = per_col * row_h + (per_col - 1) * int(0.7 * g)
        y0 = cb.y + int((cb.h - total) * 0.2)
        for i, it in enumerate(items):
            c, r = divmod(i, per_col)
            x = cb.x + c * (col_w + 2 * g)
            y = y0 + r * (row_h + int(0.7 * g))
            if show_icon:
                lay.elements.extend(self._icon_badge(look, None, Box(x=x, y=y, w=icon, h=icon), it.icon or "circle-check", None))
            yy = y
            if it.head:
                hh = tf.needed_height([(it.head, True)], text_w, look.heading_font, hs)
                lay.elements.append(self.text(look, Box(x=x + tx_off, y=yy, w=text_w, h=hh), self._paras([it.head]), "heading",
                                              look.heading_font, hs, hs, look.heading, bold=True))
                yy += hh + int(0.15 * g)
            if it.text:
                el = self.text(look, Box(x=x + tx_off, y=yy, w=text_w, h=max(1, y + row_h - yy)), self._paras([it.text]),
                               "body", look.body_font, bs, bs, look.muted if it.head else look.fg)
                el.overflow = el.overflow or not found
                lay.elements.append(el)
        if spec.slide.image and cols == 1:
            ix = cb.x + col_w + 2 * g
            lay.elements.append(El(id=self._id("im"), kind="image", box=Box(x=ix, y=cb.y, w=cb.x2 - ix, h=cb.h),
                                   image=spec.slide.image, role="image", radius=int(0.12 * INCH * look.k)))

    # ---------------------------------------------------------------- process
    def r_process(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        items = self._items(spec.slide, 6)
        if not items:
            return self.r_quote(spec, look, cb, lay)
        n = len(items)
        avg = sum(len(it.text) for it in items) / n
        if n <= 4 and avg > 110 and cb.h > cb.w * 0.4:
            return self._process_vertical(spec, look, cb, lay, items)
        arrow = int(max(0.28 * INCH * look.k, look.gap * 1.2))
        cw = (cb.w - (n - 1) * arrow) // n
        pad = self.pad(look)
        inner = cw - 2 * pad
        label_size = look.snap_down(max(look.min_size, look.body_size * 0.85))
        hs_pref = max(look.heading_size, look.snap_up(look.body_size * 1.15))
        best = None
        for hs, bs in look.pairs(heads=[it.head for it in items], bodies=[it.text for it in items], width=inner):
            need = max(tf.needed_height([(it.value or "Шаг 1", True)], inner, look.heading_font, label_size)
                       + (tf.needed_height([(it.head, True)], inner, look.heading_font, hs) if it.head else 0)
                       + (tf.needed_height([(it.text, False)], inner, look.body_font, bs) if it.text else 0)
                       + int(0.5 * look.gap) for it in items) + 2 * pad
            if need <= cb.h * 0.92:
                best = (hs, bs, need)
                break
        ovf = best is None
        hs, bs, need = best or (look.min_size, look.min_size, cb.h)
        ch = int(min(cb.h, max(need, 0.5 * cb.h)))
        y = cb.y + int((cb.h - ch) * 0.3)
        for i, it in enumerate(items):
            x = cb.x + i * (cw + arrow)
            cc = look.card(accent=(i == n - 1 and spec.opts.get("accent_last", True)))
            card = El(id=self._id("c"), kind="card", box=Box(x=x, y=y, w=cw, h=ch), card=cc.index, fill=cc.fill,
                      line=cc.line, geom="roundRect", role="card")
            lay.elements.append(card)
            yy = y + pad
            lh = tf.needed_height([(it.value or "Шаг 1", True)], inner, look.heading_font, label_size)
            lay.elements.append(self.text(look, Box(x=x + pad, y=yy, w=inner, h=lh), self._paras([it.value or f"Шаг {i + 1}"]),
                                          "label", look.heading_font, label_size, label_size, cc.accent, bold=True, parent=card.id))
            yy += lh + int(0.25 * look.gap)
            if it.head:
                hh = tf.needed_height([(it.head, True)], inner, look.heading_font, hs)
                lay.elements.append(self.text(look, Box(x=x + pad, y=yy, w=inner, h=hh), self._paras([it.head]), "heading",
                                              look.heading_font, hs, hs, cc.heading, bold=True, parent=card.id))
                yy += hh + int(0.25 * look.gap)
            if it.text:
                el = self.text(look, Box(x=x + pad, y=yy, w=inner, h=max(1, y + ch - pad - yy)), self._paras([it.text]),
                               "body", look.body_font, bs, bs, cc.muted, parent=card.id)
                el.overflow = el.overflow or ovf
                lay.elements.append(el)
            if i < n - 1:
                ay = y + ch // 2
                lay.elements.append(El(id=self._id("a"), kind="line", box=Box(x=x + cw + arrow // 5, y=ay, w=arrow * 3 // 5, h=0),
                                       line=look.accent, line_w=1.75, arrow=True, role="arrow"))

    def _process_vertical(self, spec, look: Look, cb: Box, lay: SlideLayout, items: list[Item]):
        n = len(items)
        arrow = int(max(0.22 * INCH * look.k, look.gap))
        bh = (cb.h - (n - 1) * arrow) // n
        w = int(cb.w * 0.72)
        pad = self.pad(look)
        for i, it in enumerate(items):
            y = cb.y + i * (bh + arrow)
            cc = look.card(accent=(i == n - 1))
            card = El(id=self._id("c"), kind="card", box=Box(x=cb.x, y=y, w=w, h=bh), card=cc.index, fill=cc.fill,
                      line=cc.line, geom="roundRect", role="card")
            lay.elements.append(card)
            txt = [P(runs=[Run(text=(it.head + " — ") if it.head else "", bold=True), Run(text=it.text)])]
            lay.elements.append(self.text(look, Box(x=cb.x + pad, y=y + pad // 2, w=w - 2 * pad, h=bh - pad), txt, "body",
                                          look.body_font, look.body_size, look.min_size, cc.text, valign="ctr",
                                          parent=card.id))
            if i < n - 1:
                ax = cb.x + w // 2
                lay.elements.append(El(id=self._id("a"), kind="line", box=Box(x=ax, y=y + bh + arrow // 6, w=0, h=arrow * 2 // 3),
                                       line=look.accent, line_w=1.5, arrow=True, role="arrow"))
        # подпись справа — вывод
        if spec.slide.quote:
            x = cb.x + w + look.gap * 2
            lay.elements.append(self.text(look, Box(x=x, y=cb.y, w=cb.x2 - x, h=cb.h), self._paras([spec.slide.quote]), "caption",
                                          look.body_font, look.body_size, look.min_size, look.muted, valign="ctr"))

    # ---------------------------------------------------------------- timeline
    def r_timeline(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        items = self._items(spec.slide, 6)
        if not items:
            return self.r_quote(spec, look, cb, lay)
        n = len(items)
        col = cb.w // n
        line_y = cb.y + int(cb.h * 0.28)
        dot = int(0.16 * INCH * look.k)
        lay.elements.append(El(id=self._id("l"), kind="line", box=Box(x=cb.x, y=line_y, w=cb.w, h=0), line=look.accent,
                               line_w=2.0, role="timeline"))
        inner = col - look.gap
        hs_pref = max(look.heading_size, look.snap_up(look.body_size * 1.15))
        lab_size = look.snap_down(min(look.number_size * 0.55, hs_pref * 1.5))
        below_h = cb.y2 - (line_y + dot + look.gap)
        hs, bs = look.min_size, look.min_size
        for h_c, b_c in look.pairs(heads=[it.head for it in items], bodies=[it.text for it in items], width=inner):
            if all((tf.needed_height([(it.head, True)], inner, look.heading_font, h_c) if it.head else 0)
                   + (tf.needed_height([(it.text, False)], inner, look.body_font, b_c) if it.text else 0)
                   + int(0.2 * look.gap) <= below_h for it in items):
                hs, bs = h_c, b_c
                break
        for i, it in enumerate(items):
            x = cb.x + i * col
            lay.elements.append(El(id=self._id("d"), kind="shape", geom="ellipse",
                                   box=Box(x=x, y=line_y - dot // 2, w=dot, h=dot), fill=look.accent, role="dot"))
            lab_h = line_y - dot - cb.y
            lay.elements.append(self.text(look, Box(x=x, y=cb.y, w=inner, h=lab_h), self._paras([it.value or f"{i + 1:02d}"]),
                                          "number", look.number_font, lab_size, look.min_size, look.accent, bold=True, valign="b"))
            yy = line_y + dot + look.gap
            if it.head:
                hh = tf.needed_height([(it.head, True)], inner, look.heading_font, hs)
                lay.elements.append(self.text(look, Box(x=x, y=yy, w=inner, h=hh), self._paras([it.head]), "heading",
                                              look.heading_font, hs, hs, look.heading, bold=True))
                yy += hh + int(0.2 * look.gap)
            if it.text:
                lay.elements.append(self.text(look, Box(x=x, y=yy, w=inner, h=max(1, cb.y2 - yy)), self._paras([it.text]),
                                              "body", look.body_font, bs, bs, look.muted))

    # ---------------------------------------------------------------- stats
    def r_stats(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        items = [it for it in self._items(spec.slide, 4) if it.value] or self._items(spec.slide, 4)
        if not items:
            return self.r_quote(spec, look, cb, lay)
        n = len(items)
        g = look.gap * 2
        cw = (cb.w - (n - 1) * g) // n
        with_cards = spec.opts.get("cards", False) or spec.opts.get("fill", False)
        pad = self.pad(look) if with_cards else 0
        inner = cw - 2 * pad
        num_pref = look.snap_down(min(max(look.number_size, 40 * look.k * 1.3), 66 * look.k * 1.3))
        vals = [it.value or "—" for it in items]
        num_size, _ = tf.fit_size([(max(vals, key=len), True)], inner, int(cb.h * 0.45), look.number_font,
                                  look.scale + [num_pref], num_pref, look.snap_down(num_pref * 0.5), max_lines=1)
        num_h = tf.needed_height([("0", True)], inner, look.number_font, num_size)
        hs_pref = max(look.heading_size, look.snap_up(look.body_size * 1.15))
        rest_h = int(cb.h * 0.8) - num_h - 2 * pad
        hs, bs = look.min_size, look.min_size
        for h_c, b_c in look.pairs(heads=[it.head for it in items], bodies=[it.text for it in items], width=inner):
            if all((tf.needed_height([(it.head, True)], inner, look.heading_font, h_c) if it.head else 0) + (
                    tf.needed_height([(it.text, False)], inner, look.body_font, b_c) if it.text else 0) <= rest_h
                   for it in items):
                hs, bs = h_c, b_c
                break
        block_h = num_h + max((tf.needed_height([(it.head, True)], inner, look.heading_font, hs) if it.head else 0)
                              + (tf.needed_height([(it.text, False)], inner, look.body_font, bs) if it.text else 0)
                              for it in items) + int(0.5 * look.gap) + 2 * pad
        if spec.opts.get("fill"):
            block_h = max(block_h, int(0.6 * cb.h))
        block_h = min(block_h, cb.h)
        y0 = cb.y + (cb.h - block_h) // 2 - int(0.05 * cb.h)
        y0 = max(cb.y, y0)
        for i, it in enumerate(items):
            x = cb.x + i * (cw + g)
            parent = None
            cc = look.card() if with_cards else None
            if with_cards:
                card = El(id=self._id("c"), kind="card", box=Box(x=x, y=y0, w=cw, h=block_h), card=cc.index, fill=cc.fill,
                          line=cc.line, geom="roundRect", role="card")
                lay.elements.append(card)
                parent = card.id
            acc = cc.accent if cc else look.accent
            yy = y0 + pad
            lay.elements.append(self.text(look, Box(x=x + pad, y=yy, w=inner, h=num_h), self._paras([it.value or "—"]), "number",
                                          look.number_font, num_size, look.min_size, acc, bold=True, max_lines=1, parent=parent))
            yy += num_h + int(0.3 * look.gap)
            if it.head:
                hh = tf.needed_height([(it.head, True)], inner, look.heading_font, hs)
                lay.elements.append(self.text(look, Box(x=x + pad, y=yy, w=inner, h=hh), self._paras([it.head]), "heading",
                                              look.heading_font, hs, hs, cc.heading if cc else look.heading, bold=True,
                                              parent=parent))
                yy += hh + int(0.2 * look.gap)
            if it.text:
                lay.elements.append(self.text(look, Box(x=x + pad, y=yy, w=inner, h=max(1, y0 + block_h - pad - yy)),
                                              self._paras([it.text]), "body", look.body_font, bs, look.min_size,
                                              cc.muted if cc else look.muted, parent=parent))

    # ---------------------------------------------------------------- chart
    def r_chart(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        s = spec.slide
        if not s.chart or not s.chart.series or not s.chart.categories:
            return self.r_stats(spec, look, cb, lay) if any(it.value for it in s.items) else self.r_cards(spec, look, cb, lay)
        side = self._items(s, 3)
        chart_w = int(cb.w * (0.62 if side else 1.0))
        ch = s.chart
        colors = look.chart_colors
        lay.elements.append(El(id=self._id("ch"), kind="chart", box=Box(x=cb.x, y=cb.y, w=chart_w, h=cb.h), role="chart",
                               chart={"type": ch.type, "categories": ch.categories,
                                      "series": [se.model_dump() for se in ch.series][:5], "unit": ch.unit,
                                      "title": ch.title, "colors": colors, "font": look.body_font,
                                      "font_size": look.snap_down(max(look.min_size, look.body_size * 0.9)),
                                      "text_color": look.fg, "grid_color": mix(look.bg, look.fg, 0.15),
                                      "label_color": look.fg}))
        if side:
            x = cb.x + chart_w + look.gap * 2
            sub = Box(x=x, y=cb.y, w=cb.x2 - x, h=cb.h)
            sub_spec = spec.model_copy(update={"opts": {**spec.opts, "icons": False}})
            sub_spec.slide = s.model_copy(update={"items": side, "lead": ""})
            if all(it.value for it in side):
                self._side_stats(sub_spec, look, sub, lay)
            else:
                self.r_rows_compact(sub_spec, look, sub, lay)

    def _side_stats(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        items = spec.slide.items
        n = len(items)
        g = look.gap
        bh = (cb.h - (n - 1) * g) // n
        num_size = look.snap_down(min(look.number_size, 40 * look.k * 1.3))
        for i, it in enumerate(items):
            y = cb.y + i * (bh + g)
            nh = tf.needed_height([("0", True)], cb.w, look.number_font, num_size)
            lay.elements.append(self.text(look, Box(x=cb.x, y=y, w=cb.w, h=nh), self._paras([it.value]), "number",
                                          look.number_font, num_size, look.min_size, look.accent, bold=True, max_lines=1))
            txt = " — ".join(t for t in (it.head, it.text) if t)
            lay.elements.append(self.text(look, Box(x=cb.x, y=y + nh, w=cb.w, h=max(1, bh - nh)), self._paras([txt]), "body",
                                          look.body_font, look.body_size, look.min_size, look.muted))

    def r_rows_compact(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        items = spec.slide.items
        n = len(items)
        g = look.gap
        bh = (cb.h - (n - 1) * g) // n
        for i, it in enumerate(items):
            y = cb.y + i * (bh + g)
            paras = []
            if it.head:
                paras.append(P(runs=[Run(text=it.head, bold=True, color=look.heading)]))
            if it.text:
                paras.append(P(runs=[Run(text=it.text)]))
            lay.elements.append(self.text(look, Box(x=cb.x, y=y, w=cb.w, h=bh), paras, "body", look.body_font,
                                          look.body_size, look.min_size, look.fg, space_k=0.3))
            if i < n - 1:
                lay.elements.append(El(id=self._id("l"), kind="line", box=Box(x=cb.x, y=y + bh + g // 2, w=cb.w, h=0),
                                       line=mix(look.bg, look.fg, 0.18), line_w=0.75, role="divider"))

    # ---------------------------------------------------------------- table
    def r_table(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        s = spec.slide
        t = s.table
        if not t or not t.columns:
            return self.r_rows(spec, look, cb, lay)
        cols = t.columns[:5]
        rows = [r[: len(cols)] + [""] * (len(cols) - len(r[: len(cols)])) for r in t.rows[:7]]
        ts = self.p.table_style
        # ширины колонок пропорциональны длине содержимого
        lens = [max([len(cols[j])] + [len(r[j]) for r in rows]) for j in range(len(cols))]
        tot = sum(max(6, min(60, L)) for L in lens)
        widths = [int(cb.w * max(6, min(60, L)) / tot) for L in lens]
        widths[-1] = cb.w - sum(widths[:-1])
        pref = look.body_max
        cell_pad = int(0.08 * INCH * look.k)
        size = look.min_size
        heights = []
        for cand in look.sizes_between(look.min_size, pref):
            heights = []
            for ri, r in enumerate([cols] + rows):
                hmax = max(tf.needed_height([(r[j], ri == 0)], widths[j] - 2 * cell_pad, look.body_font, cand)
                           for j in range(len(cols))) + 2 * cell_pad
                heights.append(hmax)
            if sum(heights) <= cb.h:
                size = cand
                break
        overflow = sum(heights) > cb.h
        # разреженная таблица растягивается по высоте (до 70% области), чтобы не оставлять пустоту
        target = int(cb.h * 0.7)
        if heights and sum(heights) < target:
            cap = int(0.85 * INCH * look.k)
            extra = (target - sum(heights)) // len(heights)
            heights = [min(cap, h + extra) if h < cap else h for h in heights]
        header_fill = ts.header_fill or look.accent
        header_text = readable([ts.header_text, self.p.palette.text_light, self.p.palette.text_dark], header_fill)
        body_fill = ts.body_fill if ts.body_fill and ts.body_fill != "none" else None
        body_surface = body_fill or look.bg
        body_text = readable([ts.body_text, look.fg], body_surface)
        lay.elements.append(El(id=self._id("tb"), kind="table", box=Box(x=cb.x, y=cb.y, w=cb.w, h=min(cb.h, sum(heights))),
                               role="table", overflow=overflow,
                               table={"columns": cols, "rows": rows, "widths": widths, "heights": heights, "size": size,
                                      "font": look.body_font, "header_fill": header_fill, "header_text": header_text,
                                      "body_fill": body_fill, "alt_fill": ts.alt_fill, "body_text": body_text,
                                      "border": ts.border or mix(look.bg, look.fg, 0.2), "pad": cell_pad,
                                      "first_col_bold": True}))

    # ---------------------------------------------------------------- comparison
    def r_comparison(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        s = spec.slide
        cols = [c for c in s.columns if c.points][:3]
        if len(cols) < 2:
            return self.r_cards(spec, look, cb, lay)
        n = len(cols)
        g = look.gap * 1.5
        cw = int((cb.w - (n - 1) * g) // n)
        pad = self.pad(look)
        inner = cw - 2 * pad
        hs, bs = look.min_size, look.min_size
        for h_c, b_c in look.pairs(heads=[c.title for c in cols], bodies=[pt for c in cols for pt in c.points[:6]], width=inner):
            head_h = tf.needed_height([(max((c.title for c in cols), key=len), True)], inner, look.heading_font, h_c) + 2 * pad
            if all(tf.fits([(pt, False) for pt in c.points[:6]], inner, cb.h - head_h - 2 * pad, look.body_font, b_c,
                           space_after_k=0.45) for c in cols):
                hs, bs = h_c, b_c
                break
        head_h = tf.needed_height([(max((c.title for c in cols), key=len), True)], inner, look.heading_font, hs) + 2 * pad
        need_body = max(tf.needed_height([(pt, False) for pt in c.points[:6]], inner, look.body_font, bs, 1.0, 0.45)
                        for c in cols) + 2 * pad
        body_h = int(min(cb.h - head_h, max(need_body * 1.15, 0.5 * cb.h)))
        for i, c in enumerate(cols):
            x = cb.x + int(i * (cw + g))
            hc = look.card(accent=(i == n - 1))
            head = El(id=self._id("c"), kind="card", box=Box(x=x, y=cb.y, w=cw, h=head_h), card=hc.index, fill=hc.fill,
                      line=hc.line, geom="roundRect", role="card")
            lay.elements.append(head)
            lay.elements.append(self.text(look, Box(x=x + pad, y=cb.y + pad, w=inner, h=head_h - 2 * pad), self._paras([c.title]),
                                          "heading", look.heading_font, hs, look.body_size, hc.heading, bold=True,
                                          valign="ctr", parent=head.id))
            bc = look.card()
            body = El(id=self._id("c"), kind="card", box=Box(x=x, y=cb.y + head_h + int(0.3 * look.gap), w=cw,
                                                               h=body_h - int(0.3 * look.gap)),
                      card=bc.index, fill=bc.fill, line=bc.line, geom="roundRect", role="card")
            lay.elements.append(body)
            paras = [P(runs=[Run(text=pt)], bullet=True, bullet_color=bc.accent) for pt in c.points[:6]]
            lay.elements.append(self.text(look, Box(x=x + pad, y=body.box.y + pad, w=inner, h=body.box.h - 2 * pad), paras,
                                          "body", look.body_font, bs, bs, bc.text, space_k=0.45, parent=body.id))

    # ---------------------------------------------------------------- quote / key message
    def r_quote(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        s = spec.slide
        text = s.quote or s.lead or (s.items[0].text if s.items else "") or s.title
        w = int(cb.w * 0.82)
        pref = look.snap_down(min(look.p.typography.title.size * 1.05, 34 * look.k * 1.3))
        el = self.text(look, Box(x=cb.x, y=cb.y, w=w, h=int(cb.h * 0.7)), self._paras([text]), "quote", look.heading_font,
                       pref, look.body_size, look.heading, bold=False, valign="ctr", line_spacing=1.05)
        lay.elements.append(el)
        cap = next((it.head or it.text for it in s.items if (it.head or it.text) and (it.head or it.text) != text), "")
        # подпись-заглушка («Итог», «Вывод») ничего не сообщает — только имя автора или источник
        if cap and not GENERIC_CAPTION.match(cap.strip()):
            lay.elements.append(self.text(look, Box(x=cb.x, y=cb.y + int(cb.h * 0.74), w=w, h=int(cb.h * 0.24)),
                                          self._paras([cap]), "caption", look.body_font, look.body_size, look.min_size,
                                          readable([look.accent, look.heading], look.bg, 4.5, [look.fg]), bold=True))

    # ---------------------------------------------------------------- image + text
    def r_image_text(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        s = spec.slide
        if not s.image:
            return self.r_bullets(spec, look, cb, lay)
        img_w = int(cb.w * 0.46)
        right = spec.opts.get("image_right", True)
        ix = cb.x2 - img_w if right else cb.x
        lay.elements.append(El(id=self._id("im"), kind="image", box=Box(x=ix, y=cb.y, w=img_w, h=cb.h), image=s.image,
                               role="image", radius=int(0.12 * INCH * look.k)))
        tx = cb.x if right else cb.x + img_w + look.gap * 2
        tw = cb.w - img_w - look.gap * 2
        sub = Box(x=tx, y=cb.y, w=tw, h=cb.h)
        paras = []
        if s.lead:
            paras.append(P(runs=[Run(text=s.lead)], space_after=0))
        for it in self._items(s, 5):
            runs = []
            if it.head:
                runs.append(Run(text=it.head + (". " if it.text else ""), bold=True, color=look.heading))
            if it.text:
                runs.append(Run(text=it.text))
            paras.append(P(runs=runs, bullet=True, bullet_color=look.accent))
        lay.elements.append(self.text(look, sub, paras, "body", look.body_font, look.snap_up(look.body_size * 1.1),
                                      look.min_size, look.fg, space_k=0.6, valign="ctr"))

    # ---------------------------------------------------------------- синтетический раздел
    def r_section_synth(self, spec: SlideSpec, look: Look, cb: Box, lay: SlideLayout):
        s = spec.slide
        num = spec.opts.get("number", "")
        if num:
            size = look.snap_down(min(120 * look.k * 1.3, max(look.number_size * 2, 72 * look.k)))
            h = tf.needed_height([(num, True)], cb.w // 3, look.number_font, size)
            lay.elements.append(self.text(look, Box(x=cb.x, y=cb.y + int(cb.h * 0.05), w=cb.w // 3, h=h), self._paras([num]),
                                          "number", look.number_font, size, look.number_size, look.accent, bold=True, max_lines=1))
        pts = [it.head or it.text for it in s.items][:4]
        if s.lead or pts:
            paras = ([P(runs=[Run(text=s.lead)])] if s.lead else []) + [P(runs=[Run(text=t)], bullet=True, bullet_color=look.accent) for t in pts]
            lay.elements.append(self.text(look, Box(x=cb.x, y=cb.y + int(cb.h * 0.45), w=int(cb.w * 0.6), h=int(cb.h * 0.55)),
                                          paras, "body", look.body_font, look.snap_up(look.body_size * 1.15), look.min_size,
                                          look.fg, space_k=0.5))

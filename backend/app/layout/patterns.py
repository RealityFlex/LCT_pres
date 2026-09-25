"""Заполнение слайдов-паттернов шаблона контентом (без перерисовки — текст пишется в их фигуры)."""
from __future__ import annotations

from typing import Optional

from ..parsing import fonts as _fonts
from ..parsing.model import Box, Canvas, TemplateProfile
from ..planning.models import ContentSlide, Item, SlideSpec
from . import textfit as tf
from .ir import El, SlideLayout, SlotFill
from .style import Look

INCH = 914400

# какие виды паттернов подходят какому намерению слайда
ACCEPT = {
    "bullets": ("cards", "rows"),
    "cards": ("cards", "rows"),
    "process": ("cards", "rows"),
    "timeline": ("cards", "rows"),
    "agenda": ("rows", "cards"),
    "stats": ("stats", "cards"),
    "chart": ("chart",),
    "table": ("table",),
    "comparison": ("cards", "table"),
    "image": ("image", "cards"),
}


def _items(s: ContentSlide) -> list[Item]:
    return [it for it in s.items if it.head or it.text or it.value]


def eligible(pat: Canvas, s: ContentSlide, intent: str) -> Optional[float]:
    """Пригодность паттерна для слайда: None — не подходит, иначе оценка (больше — лучше)."""
    pi = pat.pattern
    if pi is None or pi.kind not in ACCEPT.get(intent, ()):
        return None
    items = _items(s)
    score = pat.score
    if (pi.hollow or pi.image_sids) and not s.image:
        return None   # в образце фото/скриншот его темы — без своей картинки он останется чужим
    if pi.kind in ("cards", "rows", "stats"):
        k = len(items)
        if intent == "comparison":
            k = len(s.columns)
        if k < 2 or k > pi.count:
            return None
        if pi.arrangement == "grid" and k != pi.count:
            return None
        has_text = sum(len(it.text) for it in items) / max(1, k) > 15
        if has_text and "body" not in pi.roles:
            return None
        if any(it.head for it in items) and "heading" not in pi.roles and "body" not in pi.roles:
            return None
        if pi.kind == "stats" and not all(it.value for it in items[:k]):
            return None
        avg_body = sum(len(it.text) for it in items) / max(1, k)
        avg_head = sum(len(it.head) for it in items) / max(1, k)
        if pi.body_chars and avg_body > pi.body_chars * 1.35:
            return None
        if pi.body_chars and avg_body < 0.12 * pi.body_chars:
            score -= 1.2   # слот рассчитан на длинный текст — короткий «потеряется»
        if pi.head_chars and "body" in pi.roles and avg_head > pi.head_chars * 1.6:
            score -= 0.5
        score += 1.0 if k == pi.count else -0.3 * (pi.count - k)
        if intent == "stats" and pi.kind == "stats":
            score += 1.0
    elif pi.kind == "table":
        t = s.table
        if t is None or not t.columns or len(t.columns) > pi.table_cols or len(t.rows) > pi.table_rows + 2:
            return None
        score += 1.0 - 0.2 * abs(len(t.columns) - pi.table_cols)
    elif pi.kind == "chart":
        if s.chart is None:
            return None
        score += 1.0
    elif pi.kind == "image":
        if not s.image:
            return None
        score += 1.5
    return score


class PatternFiller:
    def __init__(self, profile: TemplateProfile, composer):
        self.p = profile
        self.c = composer

    def _font(self, family: str, look: Look) -> Optional[str]:
        return None if (not family or _fonts.font_available(family)) else look.body_font

    def _fit(self, m: dict, text: str, look: Look, lay: SlideLayout, lines: Optional[int] = None,
             bg: Optional[str] = None) -> SlotFill:
        st = m.get("style") or {"size": look.body_size, "font": look.body_font, "bold": False}
        ins = m.get("insets") or [91440, 45720, 91440, 45720]
        b = m["box"]
        w = max(1, b["w"] - ins[0] - ins[2])
        h = max(1, b["h"] - ins[1] - ins[3])
        font_sub = self._font(st.get("font"), look)
        font = font_sub or st.get("font") or look.body_font
        size0 = st.get("size") or look.body_size
        caps = bool(st.get("caps"))
        measure = text.upper() if caps else text
        size, ok = tf.fit_size([(measure, bool(st.get("bold")))], w, int(h * 1.08), font, look.scale + [size0], size0,
                               max(look.min_size, size0 * 0.7), max_lines=lines)
        if not ok:
            per = max(1, w / 12700 / (size * 0.55)) * max(1, h / 12700 / (size * 1.25))
            lay.overflows.append({"text": text, "max_chars": max(10, int(per * 0.85))})
        # цвет текста шаблона бывает ниже нормы WCAG (серый на белом) — затемняем до читаемого
        color = None
        col = st.get("color")
        surf = bg or look.bg
        if col:
            from ..parsing.ooxml import contrast
            from .style import readable
            need = 3.0 if (size >= 18 or (st.get("bold") and size >= 14)) else 4.5
            if contrast(col, surf) < need:
                pal = self.p.palette
                color = readable([pal.muted_dark, pal.text_dark, pal.text_light], surf, need)
        return SlotFill(role="member", sid=m["sid"], text=text, size=size if size != size0 else None, font=font_sub,
                        color=color)

    def fill(self, spec: SlideSpec, pat: Canvas, lay: SlideLayout, look: Look) -> None:
        pi = pat.pattern
        s = spec.slide
        lay.clone_full = True
        lay.recipe = f"pattern:{pi.kind}"
        for sid in pi.remove_sids:
            lay.remove_sids.append(sid)
        # вводный абзац
        if pi.lead_sid:
            lead_text = s.lead or (s.quote if pi.kind == "image" else "")
            if pi.kind == "image" and not lead_text:
                lead_text = "\n".join(f"{it.head}. {it.text}".strip(". ") for it in _items(s)[:4])
            if lead_text:
                m = self._member_box(pat, pi.lead_sid)
                if m:
                    lay.slots.append(self._fit(m, lead_text, look, lay))
                else:
                    lay.remove_sids.append(pi.lead_sid)
            else:
                lay.remove_sids.append(pi.lead_sid)
                lay.remove_sids.extend(pi.lead_containers)
        if pi.kind in ("cards", "rows", "stats", "chart"):
            self._fill_items(spec, pat, lay, look)
        if pi.kind == "table":
            self._fill_table(s, pat, lay)
        if pi.kind == "chart" and pi.chart_sid and s.chart:
            lay.remove_sids.append(pi.chart_sid)
            b = pi.chart_box
            ch = s.chart
            lay.elements.append(El(id="pch", kind="chart", box=Box(x=b.x, y=b.y, w=b.w, h=b.h), role="chart", chart={
                "type": ch.type, "categories": ch.categories, "series": [se.model_dump() for se in ch.series][:5],
                "unit": ch.unit, "title": ch.title, "colors": look.chart_colors, "font": look.body_font,
                "font_size": look.snap_down(max(look.min_size, look.body_size * 0.9)), "text_color": look.fg,
                "grid_color": "D9D9D9" if not look.dark else "4A4A4A", "label_color": look.fg}))
        if s.image and pi.image_sids:
            lay.pattern_ops.append({"op": "image", "sid": pi.image_sids[0], "path": s.image})

    def _member_box(self, pat: Canvas, sid: str) -> Optional[dict]:
        """Геометрия и стиль произвольной фигуры паттерна (для вводного абзаца)."""
        from ..parsing.analyze import TemplateAnalyzer  # ленивый импорт: нужен редко
        cache = getattr(self, "_shape_cache", None)
        if cache is None:
            cache = self._shape_cache = {}
        key = pat.source_slide
        if key not in cache:
            an = TemplateAnalyzer(self.p.file)
            sl = an.prs.slides[pat.source_slide - 1]
            shapes = an.extractor.extract(sl._element, sl.part, sl.slide_layout._element, sl.slide_layout.slide_master._element)
            cache[key] = {x.sid: x for x in shapes if x.depth == 0}
        x = cache[key].get(sid)
        if x is None:
            return None
        return {"sid": sid, "box": {"x": x.x, "y": x.y, "w": x.w, "h": x.h}, "insets": list(x.insets),
                "style": {"font": x.style.font, "size": x.style.size, "bold": x.style.bold, "caps": x.style.caps}}

    def _fill_items(self, spec: SlideSpec, pat: Canvas, lay: SlideLayout, look: Look) -> None:
        pi = pat.pattern
        s = spec.slide
        items = _items(s)
        if spec.slide.intent == "comparison" and s.columns:
            items = [Item(head=c.title, text="\n".join(f"• {pt}" for pt in c.points[:4])) for c in s.columns]
        k = min(len(items), pi.count)
        by_role: dict[str, list[tuple[SlotFill, float]]] = {}

        def put(m: dict, sf: SlotFill) -> None:
            lay.slots.append(sf)
            base = (m.get("style") or {}).get("size") or look.body_size
            by_role.setdefault(m["role"], []).append((sf, base))

        for i, slot in enumerate(pi.items):
            members = slot["members"]
            if i >= k:
                if slot.get("container"):
                    lay.remove_sids.append(slot["container"])
                lay.remove_sids.extend(m["sid"] for m in members)
                continue
            it = items[i]
            roles = {m["role"] for m in members}
            bg = slot.get("fill") or pat.bg
            for m in members:
                r = m["role"]
                if r == "heading":
                    txt = it.head or it.text
                    put(m, self._fit(m, txt, look, lay, bg=bg))
                elif r == "body":
                    txt = it.text if ("heading" in roles and it.head) else " — ".join(x for x in (it.head, it.text) if x)
                    if txt:
                        put(m, self._fit(m, txt, look, lay, bg=bg))
                    else:
                        lay.remove_sids.append(m["sid"])
                elif r == "number":
                    v = it.value if it.value and len(it.value) <= 9 else f"{i + 1:02d}"
                    put(m, self._fit(m, v, look, lay, lines=1, bg=bg))
                elif r == "extra":
                    lay.remove_sids.append(m["sid"])
                elif r == "icon":
                    # иконка образца про его тему — меняем на тематическую, в цвете исходной
                    lay.pattern_ops.append({"op": "icon", "sid": m["sid"], "name": it.icon or it.head, "i": i})
        # одинаковые роли в соседних пунктах — одним кеглем (по самому тесному)
        for fills in by_role.values():
            eff = [sf.size or base for sf, base in fills]
            low = min(eff, default=0)
            for (sf, base), e in zip(fills, eff):
                if e > low:
                    sf.size = low
        # меньше пунктов, чем в образце: оставшиеся равномерно по исходному пролёту
        if 0 < k < pi.count and pi.arrangement in ("row", "column"):
            boxes = [Box(**sl["box"]) for sl in pi.items]
            axis = "x" if pi.arrangement == "row" else "y"
            if axis == "x":
                start, end = min(b.x for b in boxes), max(b.x2 for b in boxes)
                size = boxes[0].w
            else:
                start, end = min(b.y for b in boxes), max(b.y2 for b in boxes)
                size = boxes[0].h
            gaps = [(boxes[j + 1].x - boxes[j].x2) if axis == "x" else (boxes[j + 1].y - boxes[j].y2) for j in range(len(boxes) - 1)]
            gap = max(0, int(sum(gaps) / len(gaps))) if gaps else 0
            total = k * size + (k - 1) * gap
            first = start + ((end - start) - total) // 2 if axis == "x" else start
            for i in range(k):
                old = boxes[i].x if axis == "x" else boxes[i].y
                delta = first + i * (size + gap) - old
                if delta == 0:
                    continue
                sids = ([pi.items[i]["container"]] if pi.items[i].get("container") else []) + [m["sid"] for m in pi.items[i]["members"]]
                for sid in sids:
                    lay.pattern_ops.append({"op": "move", "sid": sid, "dx": delta if axis == "x" else 0, "dy": delta if axis == "y" else 0})

    def _fill_table(self, s: ContentSlide, pat: Canvas, lay: SlideLayout) -> None:
        t = s.table
        if t is None:
            return
        lay.pattern_ops.append({"op": "table", "sid": pat.pattern.table_sid, "columns": t.columns[:pat.pattern.table_cols],
                                "rows": [r[:pat.pattern.table_cols] for r in t.rows[:pat.pattern.table_rows + 2]]})

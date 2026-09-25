"""Токены дизайн-системы: палитра, типографика, сетка, образцы карточек и таблиц."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Optional

from lxml import etree

from ..core.pptx_ops import find_shape
from .analyze import NUMERIC, PLACEHOLDER_WORDS as PLACEHOLDER, SlideAnalysis, TemplateAnalyzer
from .model import Box, CardStyle, Palette, TableStyle, TextStyle, Typography
from .ooxml import color_distance, contrast, first, luminance, saturation


# ------------------------------------------------------------------ palette

def _add(acc: dict, col: Optional[str], w: float, src: str):
    if not col or col in ("none", "picture"):
        return
    if col.startswith("grad:"):
        col, w = col[5:], w * 0.6
    col = col.upper()
    acc[col]["w"] += w
    acc[col]["src"][src] += w


def build_palette(an: TemplateAnalyzer, slides: list[SlideAnalysis], bg_samples: list[str] | None = None) -> Palette:
    W, H = an.W, an.H
    sarea = W * H
    acc: dict = defaultdict(lambda: {"w": 0.0, "src": Counter()})
    for sa in slides:
        for s in sa.shapes:
            if s.kind in ("shape", "text") and s.fill:
                _add(acc, s.fill, min(1.0, s.area / sarea) * (1.0 if s.depth == 0 else 0.7), "fill")
            if s.line and s.kind in ("shape", "line", "text"):
                _add(acc, s.line, 0.01 + 0.02 * (s.line_w or 1), "line")
            for p in s.paras:
                if p.style.color:
                    _add(acc, p.style.color, len(p.text) * ((p.style.size or 12) / 12) ** 1.5 * 0.0006, "text")
            if s.table:
                for row in s.table["fills"]:
                    for f in row:
                        _add(acc, f, 0.01, "fill")
            if s.chart:
                for c in s.chart.get("colors", []):
                    _add(acc, c, 0.05, "chart")
    for c in bg_samples or []:
        _add(acc, c, 0.8, "bg")

    # кластеризация близких оттенков
    items = sorted(acc.items(), key=lambda kv: -kv[1]["w"])
    clusters: list[dict] = []
    for hexv, d in items:
        for cl in clusters:
            if color_distance(cl["hex"], hexv) < 28:
                cl["w"] += d["w"]
                cl["src"].update(d["src"])
                break
        else:
            clusters.append({"hex": hexv, "w": d["w"], "src": Counter(d["src"])})
    clusters.sort(key=lambda c: -c["w"])
    clusters = [c for c in clusters if c["w"] > 0.004][:16]

    def pick(pred, key=lambda c: -c["w"]):
        cs = sorted([c for c in clusters if pred(c)], key=key)
        return cs[0]["hex"] if cs else None

    bg_light = pick(lambda c: luminance(c["hex"]) > 0.78 and (c["src"]["fill"] + c["src"]["bg"]) > 0) or "FFFFFF"
    bg_dark = pick(lambda c: luminance(c["hex"]) < 0.09 and (c["src"]["fill"] + c["src"]["bg"]) > 0.05)
    text_dark = pick(lambda c: luminance(c["hex"]) < 0.2 and c["src"]["text"] > 0) or "111111"
    text_light = pick(lambda c: luminance(c["hex"]) > 0.85 and c["src"]["text"] > 0) or "FFFFFF"
    muted_dark = pick(lambda c: 0.08 < luminance(c["hex"]) < 0.4 and saturation(c["hex"]) < 0.25 and c["src"]["text"] > 0)
    saturated = [c for c in clusters if saturation(c["hex"]) > 0.3 and 0.03 < luminance(c["hex"]) < 0.75]
    # основной акцент — насыщенный цвет, заметный и в заливках, и в тексте
    saturated.sort(key=lambda c: -(c["w"] + 0.5 * c["src"]["text"] + 2 * c["src"]["chart"]))
    primary = saturated[0]["hex"] if saturated else (bg_dark or "0077FF")
    accents: list[str] = []
    for c in saturated[1:]:
        if all(color_distance(c["hex"], a) > 70 for a in [primary] + accents):
            accents.append(c["hex"])
    if bg_dark is None:
        darks = [c for c in clusters if luminance(c["hex"]) < 0.12]
        bg_dark = darks[0]["hex"] if darks else "1F2430"
    surface = pick(lambda c: 0.7 < luminance(c["hex"]) < 0.985 and c["hex"] != bg_light and c["src"]["fill"] > 0.01
                   and color_distance(c["hex"], bg_light) > 6)
    chart_cols: list[str] = []
    for sa in slides:
        for s in sa.shapes:
            if s.chart:
                for c in s.chart.get("colors", []):
                    if all(color_distance(c, x) > 40 for x in chart_cols):
                        chart_cols.append(c)
    if len(chart_cols) < 3:
        for c in [primary] + accents:
            if all(color_distance(c, x) > 40 for x in chart_cols):
                chart_cols.append(c)
    # добиваем серию оттенками основного цвета
    if len(chart_cols) < 4:
        from .ooxml import hex_to_rgb, rgb_to_hex
        r, g, b = hex_to_rgb(primary)
        for k in (0.55, 0.3):
            chart_cols.append(rgb_to_hex((r + (255 - r) * k, g + (255 - g) * k, b + (255 - b) * k)))
    roles = {bg_light: "bg_light", bg_dark: "bg_dark", text_dark: "text", primary: "primary"}
    colors = [{"hex": c["hex"], "weight": round(c["w"], 4), "role": roles.get(c["hex"], "accent" if c["hex"] in accents else "other"),
               "sources": dict(c["src"])} for c in clusters]
    return Palette(colors=colors, bg_light=bg_light, bg_dark=bg_dark, text_dark=text_dark, text_light=text_light,
                   muted_dark=muted_dark or _mix(text_dark, bg_light, 0.45), muted_light=_mix(text_light, bg_dark, 0.3),
                   primary=primary, accents=accents[:5], chart=chart_cols[:6], surface=surface)


def _mix(a: str, b: str, k: float) -> str:
    from .ooxml import hex_to_rgb, rgb_to_hex
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex([ra[i] * (1 - k) + rb[i] * k for i in range(3)])


# ------------------------------------------------------------------ typography

def _mode_style(styles: list[tuple[TextStyle, float]]) -> Optional[TextStyle]:
    if not styles:
        return None
    cnt: Counter = Counter()
    for st, w in styles:
        cnt[(st.font, round(st.size * 2) / 2, st.color, st.bold, st.caps)] += w
    (font, size, color, bold, caps), _ = cnt.most_common(1)[0]
    return TextStyle(font=font, size=size, color=color, bold=bold, caps=caps)


def build_typography(an: TemplateAnalyzer, slides: list[SlideAnalysis], palette: Palette) -> Typography:
    content = [s for s in slides if s.kind in ("content", "agenda")]
    titles, kickers, subtitles, heads, bodies, numbers, captions = [], [], [], [], [], [], []
    sizes: Counter = Counter()
    fonts: Counter = Counter()
    caps_titles = 0
    n_titles = 0
    for sa in slides:
        for s in sa.shapes:
            for p in s.paras:
                if p.style.size:
                    sizes[round(p.style.size * 2) / 2] += 1
                if p.style.font:
                    fonts[p.style.font] += len(p.text)
        for sl in sa.slots:
            if sl.role == "title" and sa.kind in ("content", "agenda"):
                titles.append((sl.style, 1.0))
                if sl.text.strip():
                    n_titles += 1
                    letters = [ch for ch in sl.text if ch.isalpha()]
                    if sl.style.caps or (letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.8):
                        caps_titles += 1
            elif sl.role == "kicker":
                kickers.append((sl.style, 1.0))
            elif sl.role == "subtitle" and sa.kind == "title":
                subtitles.append((sl.style, 1.0))
    title_ids = {sl.sid for sa in slides for sl in sa.slots if sl.role in ("title", "kicker")}
    for sa in content:
        for g in sa.groups[:1]:
            for it in g.items:
                for m in it["members"]:
                    if m["style"] and m["role"] == "heading":
                        heads.append((TextStyle(**m["style"]), 1.0))
        for s in sa.shapes:
            if s.sid in title_ids or not s.paras or s.kind == "table":
                continue
            for p in s.paras:
                st = TextStyle(font=p.style.font or "Arial", size=p.style.size or 12, color=p.style.color or "000000",
                               bold=p.style.bold, caps=p.style.caps)
                if NUMERIC.match(p.text) and (p.style.size or 0) >= 28:
                    numbers.append((st, 1.0))
                elif len(p.text) >= 25 and not p.style.bold:
                    bodies.append((st, len(p.text)))
                elif len(p.text) < 25:
                    captions.append((st, 1.0))
    title = _mode_style(titles) or TextStyle(font=an.main_theme.major_font, size=28, color=palette.text_dark)
    body = _mode_style(bodies) or TextStyle(font=an.main_theme.minor_font, size=14, color=palette.text_dark)
    # размер тела — взвешенная медиана, а не мода
    if bodies:
        body_sizes = sorted((st.size, w) for st, w in bodies)
        tot = sum(w for _, w in body_sizes)
        acc = 0.0
        for sz, w in body_sizes:
            acc += w
            if acc >= tot / 2:
                body.size = sz
                break
    heading = _mode_style(heads) or TextStyle(font=title.font, size=round(body.size * 1.25 * 2) / 2,
                                              color=body.color, bold=True)
    if heading.size < body.size:
        heading.size = body.size
    number = _mode_style(numbers) or TextStyle(font=title.font, size=max(40, title.size * 1.6),
                                               color=palette.primary, bold=title.bold)
    caption_sizes = [st.size for st, _ in captions if st.size < body.size]
    caption = TextStyle(font=body.font, size=(statistics.median(caption_sizes) if caption_sizes else max(9, body.size - 2)),
                        color=palette.muted_dark)
    subtitle = _mode_style(subtitles) or TextStyle(font=body.font, size=max(body.size + 2, 16), color=body.color)
    kicker = _mode_style(kickers)
    scale = sorted(sz for sz, c in sizes.items() if c >= 2 and 7 <= sz <= 140)
    for sa in slides:
        for sl in sa.slots:
            if sl.style.size and round(sl.style.size * 2) / 2 not in scale:
                scale.append(round(sl.style.size * 2) / 2)
    for need in (title.size, body.size, heading.size, caption.size, number.size, subtitle.size):
        if need not in scale:
            scale.append(need)
    scale = sorted(set(scale))
    fam = [f for f, _ in fonts.most_common(4)]
    return Typography(heading_font=title.font, body_font=body.font, scale=scale, title=title, subtitle=subtitle,
                      kicker=kicker, heading=heading, body=body, caption=caption, number=number,
                      title_caps=n_titles > 0 and caps_titles / n_titles > 0.6)


# ------------------------------------------------------------------ grid

def build_grid(an: TemplateAnalyzer, slides: list[SlideAnalysis]) -> tuple[Box, int]:
    W, H = an.W, an.H
    lefts, tops, rights, bottoms, gaps = [], [], [], [], []
    for sa in slides:
        if sa.kind not in ("content", "agenda"):
            continue
        cont = [it.top for it in sa.items if it.sid in sa.content and it.top.area < 0.7 * W * H]
        cont = [s for s in cont if s.w > 0 and s.h > 0 and s.x >= -0.02 * W and s.x2 <= 1.02 * W]
        if not cont:
            continue
        lefts.append(max(0, min(s.x for s in cont)))
        rights.append(min(W, max(s.x2 for s in cont)))
        tops.append(max(0, min(s.y for s in cont)))
        bottoms.append(min(H, max(s.y2 for s in cont)))
        for g in sa.groups[:1]:
            boxes = [Box(**it["box"]) for it in g.items]
            if g.arrangement == "row":
                boxes.sort(key=lambda b: b.x)
                gaps += [b2.x - b1.x2 for b1, b2 in zip(boxes, boxes[1:]) if 0 < b2.x - b1.x2 < 0.08 * W]
            elif g.arrangement == "column":
                boxes.sort(key=lambda b: b.y)
                gaps += [b2.y - b1.y2 for b1, b2 in zip(boxes, boxes[1:]) if 0 < b2.y - b1.y2 < 0.08 * H]
    title_lefts = [sl.box.x + 0 for sa in slides for sl in sa.slots if sl.role == "title" and sa.kind == "content"]
    left = int(statistics.median(lefts)) if lefts else int(0.06 * W)
    if title_lefts:
        tl = int(statistics.median(title_lefts))
        if abs(tl - left) < 0.05 * W:
            left = min(left, tl)
    right = int(statistics.median(rights)) if rights else int(0.94 * W)
    # симметричные поля, если шаблон почти симметричен
    if abs((W - right) - left) < 0.03 * W:
        right = W - left
    top = int(statistics.median(tops)) if tops else int(0.2 * H)
    bottom = int(statistics.median(bottoms)) if bottoms else int(0.9 * H)
    gap = int(statistics.median(gaps)) if gaps else int(0.018 * W)
    gap = max(int(0.012 * W), min(gap, int(0.035 * W)))
    return Box(x=left, y=top, w=max(1, right - left), h=max(1, bottom - top)), gap


# ------------------------------------------------------------------ cards / tables

def build_card_styles(an: TemplateAnalyzer, slides: list[SlideAnalysis], palette: Palette) -> list[CardStyle]:
    W, H = an.W, an.H
    res: list[CardStyle] = []
    seen = set()
    cand = []
    for sa in slides:
        if sa.service or sa.kind not in ("content", "agenda"):
            continue
        prs_slide = an.prs.slides[sa.index - 1]
        for g in sa.groups:
            if g.count > 8:
                continue
            for it in g.items[:1]:
                if it["container"]:
                    cand.append((sa, prs_slide, it["container"], it, 3.0))
        for itm in sa.items:
            s = itm.top
            if (itm.sid in sa.content and s.kind in ("shape", "text") and s.fill not in (None, "none", "picture")
                    and 0.01 * W * H <= s.area <= 0.35 * W * H and s.geom in ("rect", "roundRect", "snipRoundRect", "round2SameRect", None)):
                cand.append((sa, prs_slide, s.sid, None, 1.0 if not itm.has_text else 0.8))
    for sa, prs_slide, sid, item, w in cand:
        el = find_shape(prs_slide, sid)
        if el is None:
            continue
        sppr = first(el, "p:spPr")
        if sppr is None:
            continue
        info = next((s for s in sa.shapes if s.sid == sid), None)
        if info is None:
            continue
        key = (info.fill, info.line, info.geom)
        if key in seen:
            continue
        seen.add(key)
        fill = info.fill if info.fill and not info.fill.startswith("grad:") else (info.fill or "")[5:] or None
        fill_hex = fill if fill and fill not in ("none", "picture") else None
        accent = bool(fill_hex and saturation(fill_hex) > 0.3 and luminance(fill_hex) < 0.6)
        on_dark = bool(fill_hex and luminance(fill_hex) < 0.2)
        text_color = palette.text_light if (fill_hex and luminance(fill_hex) < 0.35) else palette.text_dark
        heading_color = None
        marker_xml = None
        marker_box = None
        if item:
            for m in item["members"]:
                if m["role"] == "heading" and m["style"]:
                    heading_color = m["style"]["color"]
                if m["role"] == "body" and m["style"]:
                    text_color = m["style"]["color"]
                if m["role"] == "marker" and marker_xml is None:
                    mel = find_shape(prs_slide, m["sid"])
                    if mel is not None and etree.QName(mel).localname == "sp":
                        marker_xml = etree.tostring(mel, encoding="unicode")
                        cb = Box(**item["box"])
                        mb = Box(**m["box"])
                        marker_box = [(mb.x - cb.x) / max(1, cb.w), (mb.y - cb.y) / max(1, cb.h),
                                      mb.w / max(1, cb.w), mb.h / max(1, cb.h)]
        weight = w
        if item:
            roles = {m["role"] for m in item["members"]}
            if "heading" in roles or "body" in roles:
                weight += 2.0
            if "marker" in roles or "icon" in roles:
                weight += 0.5
            if any(PLACEHOLDER.search(m.get("text") or "") for m in item["members"]):
                weight *= 0.1
        if fill_hex and saturation(fill_hex) < 0.08 and 0.3 < luminance(fill_hex) < 0.8:
            weight *= 0.15   # серые подложки — обычно заглушки под фото
        if fill_hex and contrast(text_color, fill_hex) < 3:
            text_color = palette.text_light if luminance(fill_hex) < 0.4 else palette.text_dark
        style_el = first(el, "p:style")
        res.append(CardStyle(source_slide=sa.index, sid=sid, geom=info.geom or "rect", fill=fill_hex, line=info.line,
                             sppr_xml=etree.tostring(sppr, encoding="unicode"),
                             style_xml=etree.tostring(style_el, encoding="unicode") if style_el is not None else None,
                             accent=accent, on_dark=on_dark, weight=round(weight, 2), text_color=text_color, heading_color=heading_color,
                             marker_xml=marker_xml, marker_box=marker_box))
        if len(res) >= 10:
            break
    res.sort(key=lambda c: -c.weight)
    return res


def build_table_style(slides: list[SlideAnalysis], palette: Palette, body: TextStyle) -> TableStyle:
    for sa in slides:
        for s in sa.shapes:
            if s.table and s.table["rows"] >= 2:
                t = s.table
                hf = t["fills"][0][0] if t["fills"] and t["fills"][0] else None
                bf = t["fills"][1][0] if len(t["fills"]) > 1 else None
                af = t["fills"][2][0] if len(t["fills"]) > 2 else None
                ht = next((c for c in t["text_colors"][0] if c), None) or (
                    palette.text_light if hf and luminance(hf) < 0.4 else palette.text_dark)
                bt = next((c for row in t["text_colors"][1:] for c in row if c), None) or palette.text_dark
                return TableStyle(header_fill=hf if hf not in ("none",) else None, header_text=ht,
                                  body_fill=bf if bf not in ("none",) else None,
                                  alt_fill=af if af not in ("none", bf) else None,
                                  body_text=bt, border=t.get("border"), font_size=max(9, body.size - 1))
    return TableStyle(header_fill=palette.primary,
                      header_text=palette.text_light if luminance(palette.primary) < 0.45 else palette.text_dark,
                      body_fill=None, alt_fill=palette.surface, body_text=palette.text_dark,
                      border=palette.muted_light if palette.muted_light else "D0D0D0", font_size=max(9, body.size - 1))

"""Извлечение дерева фигур слайда в нормализованное представление (ShapeInfo).

Учитывает:
* абсолютные координаты с трансформациями групп;
* наследование стилей текста (run → lstStyle фигуры → плейсхолдер макета → мастер → defaultTextStyle);
* цвета темы через clrMap мастера.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from lxml import etree
from pptx.presentation import Presentation as PptxPresentation

from .ooxml import EMU_PER_PT, NS, Theme, first, parse_fill, qn, xp


@dataclass
class RunStyle:
    font: Optional[str] = None
    size: Optional[float] = None
    bold: bool = False
    italic: bool = False
    color: Optional[str] = None
    caps: bool = False
    spacing: Optional[int] = None  # spc, сотые пункта


@dataclass
class Para:
    text: str
    level: int = 0
    bullet: bool = False
    align: Optional[str] = None
    style: RunStyle = field(default_factory=RunStyle)
    line_spacing: float = 1.0


@dataclass
class ShapeInfo:
    sid: str
    name: str
    kind: str                     # text | shape | picture | table | chart | group | line | smartart | graphic
    x: int
    y: int
    w: int
    h: int
    top_index: int                # индекс верхнеуровневого элемента в spTree
    depth: int = 0
    rot: float = 0.0
    geom: Optional[str] = None
    ph_type: Optional[str] = None
    ph_idx: Optional[int] = None
    text: str = ""
    paras: list[Para] = field(default_factory=list)
    fill: Optional[str] = None
    line: Optional[str] = None
    line_w: float = 0.0
    style: RunStyle = field(default_factory=RunStyle)   # доминирующий стиль текста
    insets: tuple[int, int, int, int] = (91440, 45720, 91440, 45720)
    anchor: Optional[str] = None
    image_ref: Optional[str] = None   # имя медиа-части
    image_px: Optional[tuple[int, int]] = None
    crop: Optional[tuple[float, float, float, float]] = None
    table: Optional[dict] = None
    chart: Optional[dict] = None
    children: int = 0
    in_layout: bool = False

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ helpers

def _lvl_ppr(container, lvl: int):
    if container is None:
        return None
    return first(container, f"a:lvl{lvl + 1}pPr")


class StyleContext:
    """Цепочка источников стилей для одного слайда."""

    def __init__(self, prs: PptxPresentation, slide_el, layout_el, master_el, theme: Theme):
        self.theme = theme
        self.layout_el = layout_el
        self.master_el = master_el
        self.default_style = first(prs.part._element, "p:defaultTextStyle")
        self.tx_styles = first(master_el, "p:txStyles") if master_el is not None else None

    def _find_ph(self, root, ph_type: Optional[str], ph_idx: Optional[int]):
        if root is None:
            return None
        phs = xp(root, ".//p:cSld/p:spTree/p:sp[p:nvSpPr/p:nvPr/p:ph]")
        best = None
        for sp in phs:
            ph = first(sp, "p:nvSpPr/p:nvPr/p:ph")
            t = ph.get("type", "body")
            idx = ph.get("idx")
            if ph_idx is not None and idx is not None and int(idx) == ph_idx and ph_idx != 0:
                return sp
            if t == (ph_type or "body") or (t in ("title", "ctrTitle") and ph_type in ("title", "ctrTitle")):
                best = best if best is not None else sp
        return best

    def chain(self, shape_el, ph_type: Optional[str], ph_idx: Optional[int], lvl: int) -> list:
        """Список pPr-подобных элементов уровня lvl от ближнего к дальнему."""
        out = []
        lst = first(shape_el, "p:txBody/a:lstStyle")
        out.append(_lvl_ppr(lst, lvl))
        if ph_type is not None or ph_idx is not None:
            lay_ph = self._find_ph(self.layout_el, ph_type, ph_idx)
            if lay_ph is not None:
                out.append(_lvl_ppr(first(lay_ph, "p:txBody/a:lstStyle"), lvl))
            mtype = ph_type if ph_type in ("title", "ctrTitle") else "body"
            mas_ph = self._find_ph(self.master_el, mtype, None)
            if mas_ph is not None:
                out.append(_lvl_ppr(first(mas_ph, "p:txBody/a:lstStyle"), lvl))
            if self.tx_styles is not None:
                key = "p:titleStyle" if ph_type in ("title", "ctrTitle") else "p:bodyStyle"
                if ph_type in ("sldNum", "dt", "ftr"):
                    key = "p:otherStyle"
                out.append(_lvl_ppr(first(self.tx_styles, key), lvl))
        else:
            if self.tx_styles is not None:
                out.append(_lvl_ppr(first(self.tx_styles, "p:otherStyle"), lvl))
            out.append(_lvl_ppr(self.default_style, lvl))
        return [e for e in out if e is not None]

    def run_style(self, rpr, chain: list) -> RunStyle:
        cands = [rpr] + [first(p, "a:defRPr") for p in chain]
        cands = [c for c in cands if c is not None]
        st = RunStyle()

        def attr(name):
            for c in cands:
                v = c.get(name)
                if v is not None:
                    return v
            return None

        sz = attr("sz")
        st.size = int(sz) / 100 if sz else 18.0
        st.bold = attr("b") in ("1", "true")
        st.italic = attr("i") in ("1", "true")
        st.caps = attr("cap") == "all"
        spc = attr("spc")
        st.spacing = int(spc) if spc else None
        for c in cands:
            lat = first(c, "a:latin")
            if lat is not None and lat.get("typeface"):
                st.font = self.theme.font(lat.get("typeface"))
                break
        if st.font is None:
            st.font = self.theme.minor_font
        for c in cands:
            sf = first(c, "a:solidFill")
            if sf is not None:
                st.color = self.theme.resolve(sf)
                break
        if st.color is None:
            st.color = self.theme.scheme("tx1") or "000000"
        return st

    def para_props(self, ppr, chain: list) -> tuple[Optional[str], bool]:
        cands = [ppr] + chain
        cands = [c for c in cands if c is not None]
        algn = None
        for c in cands:
            if c.get("algn"):
                algn = c.get("algn")
                break
        bullet = False
        for c in cands:
            if first(c, "a:buNone") is not None:
                bullet = False
                break
            if first(c, "a:buChar") is not None or first(c, "a:buAutoNum") is not None:
                bullet = True
                break
        return algn, bullet


def _xfrm(el):
    """(off_x, off_y, ext_cx, ext_cy, ch_off_x, ch_off_y, ch_ext_cx, ch_ext_cy, rot)"""
    tag = etree.QName(el).localname
    if tag == "grpSp":
        x = first(el, "p:grpSpPr/a:xfrm")
    elif tag == "graphicFrame":
        x = first(el, "p:xfrm")
    else:
        x = first(el, "p:spPr/a:xfrm")
    if x is None:
        return None
    off = first(x, "a:off")
    ext = first(x, "a:ext")
    if off is None or ext is None:
        return None
    res = [int(off.get("x", 0)), int(off.get("y", 0)), int(ext.get("cx", 0)), int(ext.get("cy", 0))]
    cho = first(x, "a:chOff")
    che = first(x, "a:chExt")
    if cho is not None and che is not None:
        res += [int(cho.get("x", 0)), int(cho.get("y", 0)), int(che.get("cx", 0)), int(che.get("cy", 0))]
    else:
        res += [res[0], res[1], res[2], res[3]]
    res.append(int(x.get("rot", 0)) / 60000)
    return res


class Transform:
    def __init__(self, sx=1.0, sy=1.0, tx=0.0, ty=0.0):
        self.sx, self.sy, self.tx, self.ty = sx, sy, tx, ty

    def apply(self, x, y, w, h):
        return (int(x * self.sx + self.tx), int(y * self.sy + self.ty), int(w * self.sx), int(h * self.sy))

    def child(self, xf) -> "Transform":
        ox, oy, cx, cy, chx, chy, chcx, chcy, _ = xf
        ksx = cx / chcx if chcx else 1.0
        ksy = cy / chcy if chcy else 1.0
        # child_abs = parent(ox + (x - chx) * ksx)
        return Transform(self.sx * ksx, self.sy * ksy,
                         self.tx + self.sx * (ox - chx * ksx),
                         self.ty + self.sy * (oy - chy * ksy))


def _text_of(txbody) -> tuple[str, list]:
    paras = xp(txbody, "a:p")
    texts = []
    for p in paras:
        t = "".join(
            (n.text or "") if etree.QName(n).localname == "t" else "\n"
            for n in xp(p, "a:r/a:t | a:br | a:fld/a:t")
        )
        texts.append(t)
    return "\n".join(texts), paras


class SlideExtractor:
    def __init__(self, prs: PptxPresentation, theme_for_master):
        self.prs = prs
        self.theme_for_master = theme_for_master

    def extract(self, slide_part_el, part, layout_el, master_el, in_layout=False) -> list[ShapeInfo]:
        theme: Theme = self.theme_for_master(master_el)
        ctx = StyleContext(self.prs, slide_part_el, layout_el, master_el, theme)
        tree = first(slide_part_el, "p:cSld/p:spTree")
        out: list[ShapeInfo] = []
        if tree is None:
            return out
        top = [c for c in tree if etree.QName(c).localname in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp", "contentPart")]
        for i, el in enumerate(top):
            self._walk(el, Transform(), i, 0, ctx, theme, part, out, in_layout)
        return out

    def _walk(self, el, tr: Transform, top_index, depth, ctx, theme, part, out, in_layout):
        tag = etree.QName(el).localname
        xf = _xfrm(el)
        nv = first(el, "*[1]/p:cNvPr")
        sid = nv.get("id") if nv is not None else "?"
        name = nv.get("name", "") if nv is not None else ""
        if xf is None:
            x = y = w = h = 0
            rot = 0.0
        else:
            x, y, w, h = tr.apply(xf[0], xf[1], xf[2], xf[3])
            rot = xf[8]
        info = ShapeInfo(sid=sid, name=name, kind="shape", x=x, y=y, w=w, h=h,
                         top_index=top_index, depth=depth, rot=rot, in_layout=in_layout)
        if tag == "grpSp":
            info.kind = "group"
            kids = [c for c in el if etree.QName(c).localname in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp")]
            info.children = len(kids)
            out.append(info)
            ctr = tr.child(xf) if xf else tr
            for k in kids:
                self._walk(k, ctr, top_index, depth + 1, ctx, theme, part, out, in_layout)
            return
        ph = first(el, "*[1]/p:nvPr/p:ph")
        if ph is not None:
            info.ph_type = ph.get("type", "body")
            info.ph_idx = int(ph.get("idx")) if ph.get("idx") is not None else 0
            if xf is None and ctx.layout_el is not None and not in_layout:
                lay = ctx._find_ph(ctx.layout_el, info.ph_type, info.ph_idx)
                if lay is not None:
                    lxf = _xfrm(lay)
                    if lxf:
                        info.x, info.y, info.w, info.h = lxf[0], lxf[1], lxf[2], lxf[3]
        if tag == "pic":
            info.kind = "picture"
            blip = first(el, ".//a:blip")
            if blip is not None:
                rid = blip.get(qn("r:embed"))
                if rid and part is not None and rid in part.rels:
                    try:
                        tgt = part.rels[rid].target_part
                        info.image_ref = str(tgt.partname)
                        img = getattr(tgt, "image", None)
                        if img is not None:
                            info.image_px = img.size
                    except Exception:
                        pass
            src = first(el, ".//a:srcRect")
            if src is not None:
                info.crop = tuple(int(src.get(k, 0)) / 100000 for k in ("l", "t", "r", "b"))
        elif tag == "graphicFrame":
            gd = first(el, "a:graphic/a:graphicData")
            uri = gd.get("uri", "") if gd is not None else ""
            if uri.endswith("/table"):
                info.kind = "table"
                info.table = self._table(gd, theme)
                info.text = " ".join(" ".join(r) for r in info.table["cells"])
            elif uri.endswith("/chart"):
                info.kind = "chart"
                info.chart = self._chart(gd, part, theme)
            elif "diagram" in uri:
                info.kind = "smartart"
            else:
                info.kind = "graphic"
        elif tag == "cxnSp":
            info.kind = "line"
        if tag in ("sp", "cxnSp"):
            geom = first(el, "p:spPr/a:prstGeom")
            info.geom = geom.get("prst") if geom is not None else ("custom" if first(el, "p:spPr/a:custGeom") is not None else None)
            sppr = first(el, "p:spPr")
            info.fill = parse_fill(sppr, theme)
            if info.fill is None:
                # style reference (p:style/a:fillRef)
                fr = first(el, "p:style/a:fillRef")
                if fr is not None and fr.get("idx") not in (None, "0") and len(fr):
                    info.fill = theme.resolve(fr[0])
            ln = first(el, "p:spPr/a:ln")
            if ln is not None:
                lf = parse_fill(ln, theme)
                info.line = None if lf in ("none", None) else lf
                info.line_w = int(ln.get("w", 12700)) / EMU_PER_PT
            else:
                lr = first(el, "p:style/a:lnRef")
                if lr is not None and lr.get("idx") not in (None, "0") and len(lr):
                    info.line = theme.resolve(lr[0])
                    info.line_w = 0.75
            if info.geom in ("line", "straightConnector1") or (info.h < 2 * EMU_PER_PT or info.w < 2 * EMU_PER_PT):
                if first(el, "p:txBody/a:p/a:r") is None:
                    info.kind = "line" if info.kind != "picture" else info.kind
            txb = first(el, "p:txBody")
            if txb is not None:
                text, paras = _text_of(txb)
                info.text = text
                bp = first(txb, "a:bodyPr")
                if bp is not None:
                    info.insets = tuple(int(bp.get(k, d)) for k, d in
                                        (("lIns", 91440), ("tIns", 45720), ("rIns", 91440), ("bIns", 45720)))
                    info.anchor = bp.get("anchor")
                if text.strip():
                    if info.kind == "shape" and (info.fill in (None, "none") and not info.line):
                        info.kind = "text"
                    elif info.kind == "shape":
                        info.kind = "text"  # текст в фигуре с заливкой
                    info.paras = self._paras(el, paras, ctx, info)
                    if info.paras:
                        # доминирующий стиль = стиль самого «весомого» абзаца
                        best = max(info.paras, key=lambda p: len(p.text) * (p.style.size or 12))
                        info.style = best.style
                else:
                    # пустая рамка/плейсхолдер: стиль «будущего» текста
                    p0 = first(txb, "a:p")
                    rpr = first(p0, "a:endParaRPr") if p0 is not None else None
                    if rpr is None and p0 is not None:
                        rpr = first(p0, "a:r/a:rPr")
                    info.style = ctx.run_style(rpr, ctx.chain(el, info.ph_type, info.ph_idx, 0))
        out.append(info)

    def _paras(self, el, paras, ctx: StyleContext, info: ShapeInfo) -> list[Para]:
        res = []
        for p in paras:
            ppr = first(p, "a:pPr")
            lvl = int(ppr.get("lvl", 0)) if ppr is not None else 0
            chain = ctx.chain(el, info.ph_type, info.ph_idx, lvl)
            runs = xp(p, "a:r")
            text = "".join((t.text or "") for t in xp(p, "a:r/a:t | a:fld/a:t"))
            if not text.strip():
                continue
            rpr = None
            # берём rPr самого длинного прогона
            if runs:
                longest = max(runs, key=lambda r: len("".join(r.itertext())))
                rpr = first(longest, "a:rPr")
            if rpr is None:
                rpr = first(p, "a:endParaRPr")
            st = ctx.run_style(rpr, chain)
            algn, bullet = ctx.para_props(ppr, chain)
            ls = 1.0
            for c in [ppr] + chain:
                if c is None:
                    continue
                sp = first(c, "a:lnSpc/a:spcPct")
                if sp is not None:
                    try:
                        ls = int(sp.get("val", "100000").rstrip("%")) / 100000
                    except ValueError:
                        ls = 1.0
                    break
            res.append(Para(text=text, level=lvl, bullet=bullet, align=algn, style=st, line_spacing=ls))
        return res

    def _table(self, gd, theme: Theme) -> dict:
        tbl = first(gd, "a:tbl")
        rows = xp(tbl, "a:tr")
        cells, fills, text_colors = [], [], []
        for r in rows:
            row, frow, crow = [], [], []
            for tc in xp(r, "a:tc"):
                t, _ = _text_of(first(tc, "a:txBody")) if first(tc, "a:txBody") is not None else ("", [])
                row.append(t.strip())
                frow.append(parse_fill(first(tc, "a:tcPr"), theme))
                c = first(tc, ".//a:rPr/a:solidFill")
                crow.append(theme.resolve(c) if c is not None else None)
            cells.append(row)
            fills.append(frow)
            text_colors.append(crow)
        border = None
        b = first(tbl, ".//a:tcPr/a:lnB/a:solidFill")
        if b is not None:
            border = theme.resolve(b)
        return {"cells": cells, "fills": fills, "text_colors": text_colors, "border": border,
                "rows": len(rows), "cols": max((len(r) for r in cells), default=0)}

    def _chart(self, gd, part, theme: Theme) -> dict:
        c = first(gd, "c:chart")
        res = {"type": None, "colors": []}
        if c is None or part is None:
            return res
        rid = c.get(qn("r:id"))
        try:
            cpart = part.rels[rid].target_part
            root = etree.fromstring(cpart.blob) if not hasattr(cpart, "_element") else cpart._element
        except Exception:
            return res
        plot = first(root, ".//c:plotArea")
        if plot is not None:
            for ch in plot:
                ln = etree.QName(ch).localname
                if ln.endswith("Chart"):
                    res["type"] = ln
                    break
        for sp in xp(root, ".//c:ser/c:spPr/a:solidFill | .//c:dPt/c:spPr/a:solidFill"):
            col = theme.resolve(sp)
            if col:
                res["colors"].append(col)
        return res

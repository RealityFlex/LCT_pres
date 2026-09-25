"""Паттерны шаблона: слайды-образцы, которые клонируются целиком и заполняются контентом.

Так новая колода повторяет не только палитру и шрифты, но и композиционные приёмы
конкретного шаблона: его карточки, 3D-иллюстрации, нумерацию, таблицы, диаграммы.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from .analyze import NUMERIC, SlideAnalysis, TemplateAnalyzer
from .canvases import _pixel_title_limit, _title_max_w
from .model import Box, Canvas, PatternInfo
from .ooxml import luminance, rgb_to_hex

INCH = 914400


def _cap(box: dict, style: Optional[dict], insets) -> int:
    size = (style or {}).get("size") or 12
    w = max(1.0, (box["w"] - (insets[0] + insets[2] if insets else 182880)) / 12700)
    h = max(1.0, (box["h"] - (insets[1] + insets[3] if insets else 91440)) / 12700)
    return int(w / (size * 0.55) * max(1, int(h / (size * 1.25))))


def _bg_of(png: Optional[str], W: int, H: int, box: Optional[Box]) -> tuple[str, bool]:
    if not png or not Path(png).exists():
        return "FFFFFF", False
    im = np.asarray(Image.open(png).convert("RGB")).astype(np.float32)
    ih, iw = im.shape[:2]
    if box is not None:
        x0, y0 = max(0, int(box.x / W * iw)), max(0, int(box.y / H * ih))
        x1, y1 = min(iw, int(box.x2 / W * iw)), min(ih, int(box.y2 / H * ih))
        region = im[y0:y1, x0:x1] if x1 > x0 and y1 > y0 else im
    else:
        region = im
    c = rgb_to_hex(np.median(region.reshape(-1, 3), axis=0))
    return c, luminance(c) < 0.25


def _tight_containers(sa: SlideAnalysis, sid: str) -> set[str]:
    """Подложка, в которой лежит текст (удаляется вместе с ним, чтобы не оставлять пустую плашку)."""
    t = next((it.top for it in sa.items if it.sid == sid), None)
    out: set[str] = set()
    if t is None:
        return out
    cx, cy = t.x + t.w / 2, t.y + t.h / 2
    for it in sa.items:
        s = it.top
        if it.sid == sid or it.has_text or it.sid not in sa.content or s.kind not in ("shape",):
            continue
        if s.x <= cx <= s.x2 and s.y <= cy <= s.y2 and s.area <= 5 * max(1, t.area):
            out.add(it.sid)
    return out


def _decorative(an: TemplateAnalyzer, sa: SlideAnalysis, sid: str) -> bool:
    """PNG с заметной прозрачностью — вырезанный 3D-объект/декор, а не фото или скриншот."""
    import io
    from ..core.pptx_ops import find_shape
    from .ooxml import first, qn
    try:
        slide = an.prs.slides[sa.index - 1]
        el = find_shape(slide, sid)
        blip = first(el, ".//a:blip") if el is not None else None
        rid = blip.get(qn("r:embed")) if blip is not None else None
        if not rid:
            return True
        im = Image.open(io.BytesIO(slide.part.rels[rid].target_part.blob))
        if im.mode in ("RGBA", "LA") or "transparency" in im.info:
            a = np.asarray(im.convert("RGBA"))[..., 3]
            return float((a < 250).mean()) > 0.08
        return False
    except Exception:
        return True


def build_patterns(an: TemplateAnalyzer, slides: list[SlideAnalysis], pngs: list[str], gap: int) -> list[Canvas]:
    W, H = an.W, an.H
    out: list[Canvas] = []
    lay_cache: dict = {}
    for sa in slides:
        if sa.service or sa.kind not in ("content", "agenda") or sa.title is None:
            continue
        info: Optional[PatternInfo] = None
        cont = [it for it in sa.items if it.sid in sa.content]
        group = next((g for g in sa.groups if 2 <= g.count <= 6), None)
        used: set[str] = set()
        # ---- таблица
        tbl = next((it for it in cont if it.top.kind == "table" and it.top.table), None)
        chart = next((it for it in cont if it.top.kind == "chart"), None)
        if tbl is not None and tbl.top.table["rows"] >= 3:
            t = tbl.top.table
            info = PatternInfo(kind="table", table_sid=tbl.sid, table_rows=t["rows"], table_cols=t["cols"])
            used.add(tbl.sid)
        elif chart is not None:
            info = PatternInfo(kind="chart", chart_sid=chart.sid,
                               chart_box=Box(x=chart.top.x, y=chart.top.y, w=chart.top.w, h=chart.top.h))
            used.add(chart.sid)
        if group is not None and (info is None or info.kind == "chart"):
            roles = sorted({m["role"] for it in group.items for m in it["members"] if m["role"] in ("heading", "body", "number")})
            if not roles:
                group = None
            else:
                big_num = any(m["role"] == "number" and ((m.get("style") or {}).get("size") or 0) >= 26
                              for it in group.items for m in it["members"])
                kind = info.kind if info else ("stats" if big_num and group.count <= 4 else
                                               "rows" if group.arrangement == "column" else "cards")
                info = info or PatternInfo(kind=kind)
                info.arrangement = group.arrangement
                info.count = group.count
                fills = {it.sid: it.top.fill for it in sa.items}
                for it in group.items:
                    f = fills.get(it.get("container") or "")
                    it["fill"] = f if f and f not in ("none", "picture") and not str(f).startswith("grad:") else None
                info.items = group.items
                info.roles = roles
                heads = [m for it in group.items for m in it["members"] if m["role"] == "heading"]
                bodies = [m for it in group.items for m in it["members"] if m["role"] == "body"]
                info.head_chars = min((_cap(m["box"], m.get("style"), m.get("insets")) for m in heads), default=0)
                info.body_chars = min((_cap(m["box"], m.get("style"), m.get("insets")) for m in bodies), default=0)
                for it in group.items:
                    if it["container"]:
                        used.add(it["container"])
                    for m in it["members"]:
                        used.add(m["sid"])
        # ---- картинки-иллюстрации (скриншоты, фото) вне групп; декоративные объекты с прозрачностью не трогаем
        pics = [it for it in cont if it.top.kind == "picture" and it.sid not in used
                and 0.08 * W * H <= it.top.area <= 0.55 * W * H and not _decorative(an, sa, it.sid)]
        if info is None and pics:
            info = PatternInfo(kind="image")
        if info is None:
            continue
        # заменяем одну картинку; прочие фото/скриншоты образца остались бы чужим контентом — такой образец не годится
        pic_ids = {p.sid for p in pics[:1]}
        foreign = [it for it in cont if it.top.kind == "picture" and it.sid not in used and it.sid not in pic_ids
                   and it.top.area >= 0.012 * W * H and not _decorative(an, sa, it.sid)]
        if foreign:
            continue
        info.image_sids = [p.sid for p in pics][:1] if info.kind in ("image", "cards", "rows") else []
        used |= set(info.image_sids)
        # ---- прочие тексты образца: вводный абзац или удалить (с подложкой)
        extras = [it for it in cont if it.has_text and it.sid not in used]
        top_y = min((it["box"]["y"] for it in info.items), default=None)
        lead = None
        for it in sorted(extras, key=lambda x: x.top.y):
            if top_y is not None and it.top.y2 <= top_y + 0.02 * H and it.top.w > 0.35 * W and not NUMERIC.match(it.text):
                lead = it
                break
        if info.kind == "image":
            # для картинки с текстом крупнейший текстовый блок — тело
            biggest = max(extras, key=lambda x: x.top.area, default=None)
            if biggest is not None:
                lead = biggest
        info.lead_sid = lead.sid if lead else None
        # картинку, на которую в образце наложен текст, заменять нельзя: фото «съест» надпись
        texts_all = [it.top for it in sa.items if it.has_text]
        def _under_text(pid: str) -> bool:
            pt = next((it.top for it in sa.items if it.sid == pid), None)
            if pt is None:
                return True
            for t in texts_all:
                ix = max(0, min(pt.x2, t.x2) - max(pt.x, t.x))
                iy = max(0, min(pt.y2, t.y2) - max(pt.y, t.y))
                if ix * iy > 0.25 * max(1, t.area):
                    return True
            return False
        info.image_sids = [sid for sid in info.image_sids if not _under_text(sid)]
        if info.kind == "image" and not info.image_sids:
            continue
        if lead is not None:
            info.lead_containers = sorted(_tight_containers(sa, lead.sid))
            used |= set(info.lead_containers)
        for it in extras:
            if lead is not None and it.sid == lead.sid:
                continue
            info.remove_sids.append(it.sid)
            info.remove_sids.extend(sorted(_tight_containers(sa, it.sid)))
        # ---- «пустые» подложки-заглушки фото с подписью «Вставить фото» уже в removable
        info.remove_sids.extend(sorted(sa.removable))
        # «осиротевшие» карточки того же размера, не попавшие в группу, и всё, что внутри них
        if info.items and any(it.get("container") for it in info.items):
            cw = info.items[0]["box"]["w"]
            ch = info.items[0]["box"]["h"]
            orphans = [it for it in cont if it.sid not in used and not it.has_text and it.top.kind == "shape"
                       and abs(it.top.w - cw) <= 0.12 * cw and abs(it.top.h - ch) <= 0.12 * ch]
            for o in orphans:
                info.remove_sids.append(o.sid)
                for it in cont:
                    t = it.top
                    cx, cy = t.x + t.w / 2, t.y + t.h / 2
                    if it.sid not in used and it.sid != o.sid and o.top.x <= cx <= o.top.x2 and o.top.y <= cy <= o.top.y2                             and t.area < o.top.area and t.kind != "picture":
                        info.remove_sids.append(it.sid)
        info.remove_sids = sorted(set(info.remove_sids) - used)
        # удаляемый текст не должен «выкусывать» заметную часть слайда
        removed_area = sum(it.top.area for it in cont if it.sid in set(info.remove_sids) and it.has_text)
        if removed_area > 0.12 * W * H:
            continue
        # пустые рамки (макеты устройств под скриншоты): тексты занимают малую долю контейнера
        fills = []
        for it in info.items:
            if it.get("container"):
                cb_ = it["box"]
                ma = sum(m["box"]["w"] * m["box"]["h"] for m in it["members"] if m["role"] in ("heading", "body", "number"))
                fills.append(ma / max(1, cb_["w"] * cb_["h"]))
        info.hollow = bool(fills) and sum(fills) / len(fills) < 0.12
        # места под фото внутри пунктов или рядом — паттерн годится только со своей картинкой
        from .analyze import is_photo_placeholder
        if any(is_photo_placeholder(it.top, W * H) for it in cont):
            info.hollow = True
        # картинка с текстом годится, только если у неё есть свой текстовый блок и немного лишнего
        if info.kind == "image" and (info.lead_sid is None or len(info.remove_sids) > 12):
            continue
        if info.kind in ("cards", "rows", "stats") and len(info.remove_sids) > 14:
            continue
        boxes = [it["box"] for it in info.items]
        if lead is not None:
            # вводный абзац под заголовком — часть контента: заголовок не должен на него разрастаться
            boxes.append({"x": lead.top.x, "y": lead.top.y, "w": lead.top.w, "h": lead.top.h})
        if info.chart_box:
            boxes.append(info.chart_box.model_dump())
        if boxes:
            cb = Box(x=min(b["x"] for b in boxes), y=min(b["y"] for b in boxes),
                     w=max(b["x"] + b["w"] for b in boxes) - min(b["x"] for b in boxes),
                     h=max(b["y"] + b["h"] for b in boxes) - min(b["y"] for b in boxes))
        else:
            cb = Box(x=int(0.06 * W), y=int(0.25 * H), w=int(0.88 * W), h=int(0.6 * H))
        png = pngs[sa.index - 1] if sa.index - 1 < len(pngs) else None
        bg, dark = _bg_of(png, W, H, None)
        score = 1.0
        if info.kind in ("cards", "rows", "stats"):
            score += 0.5 * ("heading" in info.roles) + 0.5 * ("body" in info.roles)
            score -= 0.25 * abs(info.count - 4)
        c = Canvas(id=f"p{sa.index}", source_slide=sa.index, kind="pattern", layout=sa.layout,
                   keep_sids=[it.sid for it in sa.items], slots=[sl.model_copy() for sl in sa.slots if sl.role in ("title", "kicker", "pagenum")],
                   title_label_sid=sa.label.sid if sa.label else None, content_box=cb, bg=bg, dark=dark,
                   score=round(score, 2), preview=png, pattern=info,
                   title_max_w=_title_max_w(an, sa, lay_cache, gap))
        if png and Path(png).exists():
            arr = np.asarray(Image.open(png).convert("RGB")).astype(np.float32)
            ih, iw = arr.shape[:2]
            sx, sy = iw / W, ih / H
            for sl in c.slots:
                x0, y0 = max(0, int(sl.box.x * sx)), max(0, int(sl.box.y * sy))
                x1, y1 = min(iw, int(sl.box.x2 * sx)), min(ih, int(sl.box.y2 * sy))
                if x1 > x0 and y1 > y0:
                    sl.bg = rgb_to_hex(np.median(arr[y0:y1, x0:x1].reshape(-1, 3), axis=0))
                if sl.role == "title":
                    _pixel_title_limit(c, sl, arr, sx, sy, W, gap)
        out.append(c)
    return out

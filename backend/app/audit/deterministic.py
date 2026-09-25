"""Детерминированные проверки (Приложение 1): на одном и том же файле всегда один и тот же результат.

Источники данных — только то, что есть в файле и рендере: координаты, размеры, цвета, шрифты,
ссылки на макеты, пиксели PNG-рендера (для контраста и заполненности).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np
from lxml import etree
from PIL import Image

from ..layout.ir import SlideLayout
from ..layout.style import mix
from ..parsing import fonts
from ..parsing.analyze import TemplateAnalyzer
from ..parsing.extract import ShapeInfo
from ..parsing.model import Box, TemplateProfile
from ..parsing.ooxml import contrast, first, hex_to_rgb, qn, rgb_to_hex, xp
from .model import Issue

PLACEHOLDER_RE = re.compile(
    r"(lorem|ipsum|\bXXX+\b|\bTODO\b|вставьте|вставить|\bобразец текста\b|\bимя фамилия\b|\bдолжность\b|"
    r"заголовок в (одну|две)|добавьте текст|\[.*?(текст|text).*?\]|placeholder|click to add)", re.I)
EMU_PT = 12700
GENERIC_LABEL_RE = re.compile(r"^(вывод|пункт|тезис|пример|заголовок|текст|блок|элемент|item|point)\s*№?\s*\d{0,2}\.?$", re.I)


def _min_contrast(size: float, bold: bool) -> float:
    return 3.0 if (size >= 18 or (bold and size >= 14)) else 4.5


class PaletteMatcher:
    """Цвет «из палитры», если он совпадает с токеном или является его оттенком (смесь с фоном/белым/чёрным)."""

    def __init__(self, profile: TemplateProfile):
        base = list(dict.fromkeys([c.upper() for c in profile.palette.allowed()] +
                                  [c.bg.upper() for c in profile.canvases] + ["FFFFFF", "000000"]))
        pts = [hex_to_rgb(c) for c in base]
        for a in base[:16]:
            for b in base[:16] + ["FFFFFF", "000000"]:
                if a == b:
                    continue
                for k in np.arange(0.04, 0.97, 0.04):
                    pts.append(hex_to_rgb(mix(a, b, float(k))))
        self.pts = np.array(pts, dtype=np.float32)

    def ok(self, hexv: str, tol: float = 14.0) -> bool:
        c = np.array(hex_to_rgb(hexv), dtype=np.float32)
        d = np.sqrt(((self.pts - c) ** 2).sum(axis=1)).min()
        return bool(d <= tol)


def _issue(n: list, check: str, title: str, cat: str, slide: int, msg: str, sev: str = "warning",
           bbox: Optional[ShapeInfo | Box] = None, element: Optional[str] = None, fix: Optional[dict] = None) -> None:
    bb = None
    if bbox is not None:
        bb = [int(bbox.x), int(bbox.y), int(bbox.w), int(bbox.h)]
    n.append(Issue(id=f"{check}-{slide}-{len(n)}", check=check, title=title, category=cat, severity=sev,
                   deterministic=True, slide=slide, message=msg, bbox=bb, element=element, fix=fix,
                   fixable=fix is not None))


def _ir_id(name: str) -> Optional[str]:
    return name.split("|", 1)[1] if "|" in (name or "") else None


def _need_height(s: ShapeInfo) -> float:
    """Высота текста по метрикам шрифта (pt)."""
    w = (s.w - s.insets[0] - s.insets[2]) / EMU_PT
    if w <= 1:
        return 0.0
    h = 0.0
    for p in s.paras:
        size = p.style.size or 12
        t = p.text.upper() if p.style.caps else p.text
        h += fonts.text_height_pt(t, w * 0.99, p.style.font or "Arial", size, p.style.bold, p.line_spacing or 1.0)
    return h


def _intersection(a, b) -> int:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    return ix * iy


def _contains(outer, inner, tol: int) -> bool:
    return (inner.x >= outer.x - tol and inner.y >= outer.y - tol and inner.x + inner.w <= outer.x + outer.w + tol
            and inner.y + inner.h <= outer.y + outer.h + tol)


def _words(t: str) -> int:
    return len([w for w in re.split(r"\s+", t.strip()) if re.search(r"\w", w)])


def _latin_ratio(t: str) -> float:
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 20:
        return 0.0
    return sum(1 for c in letters if "a" <= c.lower() <= "z") / len(letters)


class DeterministicAuditor:
    def __init__(self, profile: TemplateProfile):
        self.p = profile
        self.pal = PaletteMatcher(profile)
        ty = profile.typography
        self.allowed_fonts = {f.lower() for f in [ty.heading_font, ty.body_font, ty.title.font, ty.number.font,
                                                  ty.caption.font] if f}
        self.allowed_fonts |= {f.lower() for f in profile.fonts_found}
        self.scale = sorted(set(ty.scale))
        self._src_cache: dict[int, dict[str, ShapeInfo]] = {}
        self._tpl: Optional[TemplateAnalyzer] = None

    def _template_shapes(self, slide_index: int) -> dict[str, ShapeInfo]:
        if slide_index not in self._src_cache:
            if self._tpl is None:
                self._tpl = TemplateAnalyzer(Path(self.p.file))
            s = self._tpl.prs.slides[slide_index - 1]
            shapes = self._tpl.extractor.extract(s._element, s.part, s.slide_layout._element,
                                                 s.slide_layout.slide_master._element)
            self._src_cache[slide_index] = {x.sid: x for x in shapes if x.depth == 0}
        return self._src_cache[slide_index]

    # ------------------------------------------------------------------ run
    def run(self, pptx_path: Path, layouts: list[SlideLayout], pngs: list[Path], pdf_pages: Optional[int] = None) -> tuple[list[Issue], list[str]]:
        issues: list[Issue] = []
        checks: set[str] = set()
        W, H = self.p.slide_w, self.p.slide_h
        try:
            an = TemplateAnalyzer(Path(pptx_path))
        except Exception as e:
            _issue(issues, "file_open", "Файл не открывается", "integrity", 0, f"python-pptx: {e}", "error")
            return issues, ["file_open"]
        checks.add("file_open")
        slides = list(an.prs.slides)
        if pdf_pages is not None and pdf_pages != len(slides):
            _issue(issues, "file_open", "Файл не открывается", "integrity", 0,
                   f"LibreOffice отрисовал {pdf_pages} стр. из {len(slides)}", "error")
        layout_names = {l.name for m in an.prs.slide_masters for l in m.slide_layouts}
        tpl_layouts = self._template_layout_names()
        texts_by_slide: list[str] = []
        for i, (slide, lay) in enumerate(zip(slides, layouts), 1):
            png = pngs[i - 1] if i - 1 < len(pngs) else None
            img = np.asarray(Image.open(png).convert("RGB")) if png and Path(png).exists() else None
            shapes = an.extractor.extract(slide._element, slide.part, slide.slide_layout._element,
                                          slide.slide_layout.slide_master._element)
            canvas = self.p.canvas(lay.canvas)
            keep = set(canvas.keep_sids) - set(lay.remove_sids)
            slot_sids = {sf.sid for sf in lay.slots}
            tops = [s for s in shapes if s.depth == 0]
            gen = [s for s in tops if s.sid not in keep]
            chrome = [s for s in tops if s.sid in keep and s.sid not in slot_sids]
            slots = [s for s in tops if s.sid in slot_sids]
            texts = [s for s in gen + slots if s.has_text and s.kind in ("text", "shape")]
            all_text = " ".join(s.text for s in tops if s.has_text)
            texts_by_slide.append(all_text)
            structural = canvas.kind in ("title", "section", "closing") and not lay.elements
            tol = int(0.004 * W)

            # ---------------- Вёрстка
            checks.update({"out_of_bounds", "text_cut", "overlap", "text_overflow", "margins", "alignment", "image_stretched"})
            for s in gen:
                if s.x < -tol or s.y < -tol or s.x2 > W + tol or s.y2 > H + tol:
                    if s.has_text:
                        _issue(issues, "text_cut", "Текст обрезан краем слайда", "layout", i,
                               f"Текстовый блок «{s.text[:40]}» выходит за край слайда", "error", s, _ir_id(s.name),
                               {"action": "clamp"})
                    else:
                        _issue(issues, "out_of_bounds", "Элемент вышел за границы слайда", "layout", i,
                               f"{s.kind} «{s.name}» выходит за границы", "error", s, _ir_id(s.name), {"action": "clamp"})
            # поля: контентная область холста с допуском
            cb = canvas.content_box
            g = self.p.gap
            mb = Box(x=cb.x - g, y=0, w=cb.w + 2 * g, h=min(H, cb.y2 + g))
            for s in gen:
                if s.kind == "line":
                    continue
                if s.x < mb.x or s.x2 > mb.x2 or s.y2 > mb.y2:
                    _issue(issues, "margins", "Контент заходит в поля", "layout", i,
                           f"«{s.name.split('|')[0]}» заходит в поля/зону колонтитула", "warning", s, _ir_id(s.name),
                           {"action": "clamp"})
            # наложения
            boxes = [s for s in gen if s.kind != "line" and s.w > 0 and s.h > 0]
            others = [s for s in chrome if s.area < 0.5 * W * H and s.kind != "line"] + slots
            for a_i, a in enumerate(boxes):
                for b in boxes[a_i + 1:] + others:
                    inter = _intersection(a, b)
                    if inter <= 0.03 * min(a.area, b.area) or inter <= 0:
                        continue
                    container_kinds = ("shape",)
                    if (_contains(a, b, tol) and a.kind in container_kinds and not a.has_text) or \
                       (_contains(b, a, tol) and b.kind in container_kinds and not b.has_text):
                        continue
                    if b in others and b.kind in ("shape",) and not b.has_text and b.area > 0.3 * W * H:
                        continue
                    _issue(issues, "overlap", "Блоки наложились друг на друга", "layout", i,
                           f"«{a.name.split('|')[0]}» перекрывает «{(b.name or b.text[:20]).split('|')[0]}»",
                           "error", a, _ir_id(a.name), {"action": "recompose"})
                    break
            # переполнение текста
            for s in texts:
                need = _need_height(s)
                avail = (s.h - s.insets[1] - s.insets[3]) / EMU_PT
                if need > avail * 1.08 + 2:
                    _issue(issues, "text_overflow", "Текст не поместился в рамку", "layout", i,
                           f"«{s.text[:50]}»: нужно {need:.0f} pt, доступно {avail:.0f} pt", "error", s, _ir_id(s.name) or s.sid,
                           {"action": "condense", "target": _ir_id(s.name) or s.sid})
            # выравнивание карточек в ряду
            cards = sorted([s for s in gen if s.name.startswith("card")], key=lambda s: (s.y, s.x))
            rows: list[list[ShapeInfo]] = []
            for c in cards:
                for r in rows:
                    if abs(r[0].y - c.y) < 0.06 * H and abs(r[0].h - c.h) < 0.3 * r[0].h:
                        r.append(c)
                        break
                else:
                    rows.append([c])
            for r in rows:
                if len(r) > 1 and max(c.y for c in r) - min(c.y for c in r) > tol:
                    _issue(issues, "alignment", "Блоки не выровнены по направляющим", "layout", i,
                           "Карточки одного ряда стоят на разной высоте", "warning", r[0], None, {"action": "recompose"})
            lefts = [s.x for s in gen if s.kind not in ("line",) and s.w > 0.02 * W]
            if lefts and abs(min(lefts) - cb.x) > max(tol, int(0.35 * g)) and not structural:
                _issue(issues, "alignment", "Блоки не выровнены по направляющим", "layout", i,
                       "Левый край контента не совпадает с направляющей макета", "info", None, None)
            # пропорции изображений
            for s in gen:
                if s.kind == "picture" and s.image_px and not s.name.startswith("icon"):
                    pw, ph = s.image_px
                    cl, ct, cr, cbm = s.crop or (0, 0, 0, 0)
                    src_ar = (pw * (1 - cl - cr)) / max(1, ph * (1 - ct - cbm))
                    box_ar = s.w / max(1, s.h)
                    if abs(src_ar / box_ar - 1) > 0.03:
                        _issue(issues, "image_stretched", "Картинка растянута, пропорции нарушены", "layout", i,
                               f"Пропорции изменены на {abs(src_ar / box_ar - 1):.0%}", "error", s, _ir_id(s.name),
                               {"action": "recrop"})

            # ---------------- Шаблон
            checks.update({"font_not_in_template", "font_families", "size_not_in_scale", "color_not_in_palette",
                           "layout_not_from_template", "chrome_moved", "contrast"})
            fams = set()
            for s in texts:
                for p in s.paras:
                    f = (p.style.font or "").lower()
                    fams.add(f)
                    if f and f not in self.allowed_fonts and not self._font_alias(f):
                        _issue(issues, "font_not_in_template", "Шрифт не из шаблона", "template", i,
                               f"Гарнитура «{p.style.font}» не используется в шаблоне", "warning", s, _ir_id(s.name),
                               {"action": "refont"})
                        break
                    if p.style.size and not any(abs(p.style.size - z) < 0.26 for z in self.scale):
                        _issue(issues, "size_not_in_scale", "Кегль не из типографической шкалы", "template", i,
                               f"Кегль {p.style.size:g} pt отсутствует в шкале шаблона", "info", s, _ir_id(s.name),
                               {"action": "snap_size"})
                        break
            if len({f for f in fams if f}) > int(self._cfg("max_font_families", 2)):
                _issue(issues, "font_families", "Гарнитур больше двух", "template", i,
                       f"На слайде {len(fams)} гарнитуры: {', '.join(sorted(fams))}", "warning", None, None, {"action": "refont"})
            for s in gen:
                cols = []
                if s.fill and s.fill not in ("none", "picture") and not s.fill.startswith("grad:"):
                    cols.append(("заливка", s.fill))
                if s.line:
                    cols.append(("линия", s.line))
                cols += [("текст", p.style.color) for p in s.paras if p.style.color]
                for what, c in cols:
                    if not self.pal.ok(c):
                        _issue(issues, "color_not_in_palette", "Цвет не из палитры шаблона", "template", i,
                               f"{what.capitalize()} #{c} отсутствует в палитре", "warning", s, _ir_id(s.name),
                               {"action": "recolor"})
                        break
            if slide.slide_layout.name not in tpl_layouts:
                _issue(issues, "layout_not_from_template", "Слайд собран не на макете шаблона", "template", i,
                       f"Макет «{slide.slide_layout.name}» отсутствует в шаблоне", "error")
            src = self._template_shapes(canvas.source_slide)
            for s in chrome:
                o = src.get(s.sid)
                if o is None or s.sid == canvas.title_label_sid:
                    continue
                if abs(o.x - s.x) > tol or abs(o.y - s.y) > tol or (abs(o.w - s.w) > tol and s.kind == "picture"):
                    _issue(issues, "chrome_moved", "Логотип или колонтитул сдвинут", "template", i,
                           f"Элемент шаблона «{s.name}» смещён относительно макета", "error", s, s.sid, {"action": "restore_chrome"})
            if img is not None:
                ih, iw = img.shape[:2]
                sx, sy = iw / W, ih / H
                for s in texts:
                    x0, y0 = max(0, int(s.x * sx)), max(0, int(s.y * sy))
                    x1, y1 = min(iw, int(s.x2 * sx)), min(ih, int(s.y2 * sy))
                    if x1 - x0 < 3 or y1 - y0 < 3 or not s.paras:
                        continue
                    region = img[y0:y1, x0:x1].reshape(-1, 3)
                    bg = rgb_to_hex(np.median(region, axis=0))
                    p0 = max(s.paras, key=lambda p: len(p.text))
                    if (p0.style.size or 0) >= 60 and re.fullmatch(r"[\d\s.,%№#]+", p0.text.strip() or "x"):
                        continue   # декоративные цифры (как в шаблоне) — WCAG: incidental text
                    col = p0.style.color or "000000"
                    need = _min_contrast(p0.style.size or 12, p0.style.bold)
                    ratio = contrast(col, bg)
                    if ratio < need - 0.05:
                        _issue(issues, "contrast", "Контраст текста к фону ниже нормы", "template", i,
                               f"Контраст {ratio:.1f}:1 (нужно ≥ {need:g}:1) для «{s.text[:30]}»", "error", s,
                               _ir_id(s.name) or s.sid, {"action": "recolor_text", "bg": bg})

            # ---------------- Плотность
            checks.update({"too_many_bullets", "long_bullet", "table_size", "chart_series", "fill_ratio"})
            bullets = sum(1 for s in texts for p in s.paras if p.bullet)
            heads = sum(1 for s in gen if s.name.startswith("heading"))
            n_items = max(bullets, heads)
            if n_items > int(self._cfg("max_bullets", 6)):
                _issue(issues, "too_many_bullets", "Больше 6 буллетов на слайде", "density", i,
                       f"На слайде {n_items} пунктов", "warning", None, None, {"action": "split"})
            for s in gen:
                role = s.name.split(" ")[0].split("|")[0]
                for p in s.paras:
                    if (p.bullet or role in ("body",)) and _words(p.text) > int(self._cfg("max_words_per_bullet", 15)):
                        _issue(issues, "long_bullet", "Буллет длиннее 15 слов", "density", i,
                               f"«{p.text[:50]}…» — {_words(p.text)} слов", "warning", s, _ir_id(s.name),
                               {"action": "condense", "target": _ir_id(s.name)})
                        break
                if s.kind == "table" and s.table:
                    r, c = s.table["rows"] - 1, s.table["cols"]
                    if r > int(self._cfg("max_table_rows", 7)) or c > int(self._cfg("max_table_cols", 5)):
                        _issue(issues, "table_size", "Таблица больше 7 строк или 5 колонок", "density", i,
                               f"Таблица {r}×{c}", "warning", s, _ir_id(s.name), {"action": "split"})
            for gf in xp(slide._element, ".//p:graphicFrame"):
                cref = first(gf, ".//c:chart")
                if cref is None:
                    continue
                try:
                    cpart = slide.part.rels[cref.get(qn("r:id"))].target_part
                    root = etree.fromstring(cpart.blob)
                except Exception:
                    continue
                n_ser = len(xp(root, ".//c:ser"))
                if n_ser > int(self._cfg("max_chart_series", 5)):
                    _issue(issues, "chart_series", "Больше 5 серий на диаграмме", "density", i,
                           f"{n_ser} серий", "warning", None, None, {"action": "trim_series"})
                has_labels = bool(xp(root, ".//c:dLbls/c:showVal[@val='1'] | .//c:dLbls/c:showPercent[@val='1']"))
                has_axis_title = bool(xp(root, ".//c:valAx/c:title"))
                has_legend = first(root, ".//c:legend") is not None
                pie = bool(xp(root, ".//c:pieChart | .//c:doughnutChart"))
                checks.add("chart_labels")
                if not has_labels or (not pie and not has_axis_title and n_ser == 1 and not has_legend and False):
                    _issue(issues, "chart_labels", "У диаграммы нет подписей, единиц или легенды", "integrity", i,
                           "Нет подписей значений", "warning", None, None, {"action": "recompose"})
                if n_ser > 1 and not has_legend:
                    _issue(issues, "chart_labels", "У диаграммы нет подписей, единиц или легенды", "integrity", i,
                           "Несколько серий без легенды", "warning", None, None, {"action": "recompose"})
            if not structural:
                occupied = self._union_ratio([s for s in gen + slots + chrome if s.kind != "line" and s.area < 0.6 * W * H], W, H)
                if occupied < float(self._cfg("min_fill_ratio", 0.25)):
                    _issue(issues, "fill_ratio", "Слайд заполнен меньше чем на четверть", "density", i,
                           f"Заполнено {occupied:.0%} площади", "warning", None, None, {"action": "enlarge"})
                elif occupied > float(self._cfg("max_fill_ratio", 0.75)):
                    _issue(issues, "fill_ratio", "Слайд заполнен больше чем на три четверти", "density", i,
                           f"Заполнено {occupied:.0%} площади", "warning", None, None, {"action": "split"})

            # ---------------- Целостность
            checks.update({"placeholder_text", "empty_slide", "raster_slide", "language"})
            for s in tops:
                generic = next((p.text for p in s.paras if GENERIC_LABEL_RE.match(p.text.strip())), None)
                if s.has_text and generic and not s.name.startswith(("label", "number")):
                    _issue(issues, "placeholder_text", "Остался текст-заглушка", "integrity", i,
                           f"Шаблонная подпись вместо содержания: «{generic}»", "error", s, _ir_id(s.name) or s.sid,
                           {"action": "llm_fix", "kind": "placeholder"})
                    continue
                if s.has_text and PLACEHOLDER_RE.search(s.text):
                    _issue(issues, "placeholder_text", "Остался текст-заглушка", "integrity", i,
                           f"«{PLACEHOLDER_RE.search(s.text).group(0)}» в «{s.text[:40]}»", "error", s, s.sid,
                           {"action": "remove_shape", "sid": s.sid})
            if not structural and not gen:
                _issue(issues, "empty_slide", "Пустой слайд или слайд с одним заголовком", "integrity", i,
                       "На слайде только заголовок", "error", None, None, {"action": "recompose"})
            pics = [s for s in tops if s.kind == "picture" and s.area > 0.9 * W * H]
            if pics and not any(s.has_text for s in tops):
                _issue(issues, "raster_slide", "Слайд оказался картинкой", "integrity", i,
                       "Слайд состоит из одного растрового изображения", "error")
            if _latin_ratio(all_text) > 0.3:
                _issue(issues, "language", "Колода не на одном языке", "content", i,
                       "Значительная часть текста слайда не на русском", "warning", None, None, {"action": "llm_fix", "kind": "language"})
        # дубликаты
        checks.add("duplicate_slides")
        for a in range(len(texts_by_slide)):
            for b in range(a + 1, len(texts_by_slide)):
                wa = set(re.findall(r"\w{3,}", texts_by_slide[a].lower()))
                wb = set(re.findall(r"\w{3,}", texts_by_slide[b].lower()))
                if len(wa) > 5 and len(wb) > 5 and len(wa & wb) / len(wa | wb) > 0.8:
                    _issue(issues, "duplicate_slides", "Два слайда дублируют друг друга", "integrity", b + 1,
                           f"Слайды {a + 1} и {b + 1} почти совпадают по тексту", "warning", None, None,
                           {"action": "drop_slide"})
        return issues, sorted(checks)

    # ------------------------------------------------------------------ helpers
    def _cfg(self, k, d):
        from ..config import get_settings
        return get_settings().audit.get(k, d)

    def _font_alias(self, f: str) -> bool:
        return any(f.startswith(a) or a.startswith(f) for a in self.allowed_fonts)

    def _template_layout_names(self) -> set[str]:
        if self._tpl is None:
            self._tpl = TemplateAnalyzer(Path(self.p.file))
        return {l.name for m in self._tpl.prs.slide_masters for l in m.slide_layouts}

    @staticmethod
    def _union_ratio(shapes: list[ShapeInfo], W: int, H: int) -> float:
        grid = np.zeros((90, 160), dtype=bool)
        for s in shapes:
            x0, y0 = max(0, int(s.x / W * 160)), max(0, int(s.y / H * 90))
            x1, y1 = min(160, int(np.ceil(s.x2 / W * 160))), min(90, int(np.ceil(s.y2 / H * 90)))
            if x1 > x0 and y1 > y0:
                grid[y0:y1, x0:x1] = True
        return float(grid.mean())

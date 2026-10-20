"""Брендбук из PDF-гайдлайна (PyMuPDF): цвета из текста (HEX, RGB, CMYK) с подписями, шрифты документа,
палитра по рендеру страниц (вес — площадь), логотип — крупная картинка с прозрачностью, правила — строки
с запретами и требованиями («нельзя», «охранное поле», «минимальный размер»)."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .model import BrandColor, BrandFont, BrandKit, BrandLogo, assign_roles, chroma, norm_hex, pick_fonts

HEX = re.compile(r"#\s?([0-9A-Fa-f]{6})\b|\bHEX\s*[:\-]?\s*#?([0-9A-Fa-f]{6})\b")
RGB = re.compile(r"\bRGB\s*[:\-]?\s*(\d{1,3})[\s,/]+(\d{1,3})[\s,/]+(\d{1,3})|\bR\s*(\d{1,3})\s+G\s*(\d{1,3})\s+B\s*(\d{1,3})", re.I)
CMYK = re.compile(r"\bCMYK\s*[:\-]?\s*(\d{1,3})[\s,/]+(\d{1,3})[\s,/]+(\d{1,3})[\s,/]+(\d{1,3})", re.I)
# «Шрифт заголовков: Manrope Bold», «Гарнитура основного текста — Golos Text», «Typeface: Inter»
FONT_TXT = re.compile(r"(?:шрифт|гарнитур|typeface|font)\w*((?:\s+[а-яёa-z]+){0,3})\s*[:\-—]\s*«?([A-Z][A-Za-z0-9 ]{2,30}?)»?"
                      r"(?:[,.;\n]|\s+(?:Regular|Bold|Medium|Light|SemiBold|Black)|$)", re.I)
MIN_LOGO = re.compile(r"минимальн\w*\s+(?:размер|высот)\w*\s+логотип\w*[^0-9\n]{0,20}(\d+(?:[.,]\d+)?)\s*(px|пикс|pt|мм|mm)", re.I)
CLEAR = re.compile(r"охранн\w*\s+пол\w*[^.\n]{0,40}?(половин|треть|четверт|(\d+(?:[.,]\d+)?)\s*(?:%|высот))", re.I)
RULE = re.compile(r"(нельзя|не допуска|запрещ|не используйте|не следует|охранн|минимальн\w* размер|не менее|do not|don't|never|clear ?space|minimum size)", re.I)


def _cmyk(c, m, y, k) -> str:
    c, m, y, k = (min(100, int(x)) / 100 for x in (c, m, y, k))
    return "%02X%02X%02X" % (round(255 * (1 - c) * (1 - k)), round(255 * (1 - m) * (1 - k)), round(255 * (1 - y) * (1 - k)))


def _label(text: str, pos: int) -> str:
    """Подпись цвета — слова перед значением на той же строке или строкой выше."""
    before = text[max(0, pos - 80):pos]
    lines = [x.strip() for x in before.split("\n") if x.strip()]
    if not lines:
        return ""
    cand = re.sub(r"(HEX|RGB|CMYK|Pantone|PMS)[^A-Za-zА-Яа-я]*$", "", lines[-1], flags=re.I).strip(" :—-")
    if len(cand) < 2 and len(lines) > 1:
        cand = lines[-2]
    return cand[:40]


def _after(text: str, pos: int) -> str:
    """Первая строка после кода цвета, которая сама не код (HEX/RGB/CMYK/Pantone)."""
    for ln in text[pos:pos + 240].split("\n")[1:6]:
        ln = ln.strip()
        if ln and not re.match(r"(HEX|RGB|CMYK|Pantone|PMS|#)", ln, re.I):
            return ln[:60]
    return ""


def palette_by_area(pngs: list, top: int = 10) -> list[tuple[str, float]]:
    """Палитра по рендеру: квантование по 4 бита на канал, вес — доля площади; белый/почти белый — слабее."""
    import numpy as np
    from PIL import Image
    cnt: Counter = Counter()
    total = 0
    for p in pngs:
        im = Image.open(p).convert("RGB") if not isinstance(p, Image.Image) else p.convert("RGB")
        im.thumbnail((320, 320))
        a = (np.asarray(im).reshape(-1, 3) >> 4).astype(np.int32)
        keys, n = np.unique(a[:, 0] * 256 + a[:, 1] * 16 + a[:, 2], return_counts=True)
        for k, v in zip(keys.tolist(), n.tolist()):
            cnt[k] += v
        total += len(a)
    out = []
    for k, v in cnt.most_common(top * 3):
        r, g, b = (k >> 8) & 15, (k >> 4) & 15, k & 15
        hexv = "%02X%02X%02X" % (r * 17, g * 17, b * 17)
        out.append((hexv, v / max(1, total)))
    return out[:top]


def brand_from_pdf(data: bytes, name: str, out_dir: Path) -> BrandKit:
    import pymupdf
    from ..core.mupdf_lock import LOCK
    out_dir.mkdir(parents=True, exist_ok=True)
    kit = BrandKit(name=re.sub(r"\.pdf$", "", name, flags=re.I), sources=[f"PDF-гайдлайн: {name}"])
    colors: list[BrandColor] = []
    fonts: Counter = Counter()
    rules: list[str] = []
    renders = []
    logo_cands = []
    with LOCK:
        doc = pymupdf.open(stream=data, filetype="pdf")
        t = (doc.metadata or {}).get("title", "").strip()
        if t and not t.lower().startswith(("microsoft", "untitled", "без назв")):
            kit.name = re.split(r"\s+[—–-]\s+", t)[0][:60]
        for pi, page in enumerate(doc):
            if pi >= 40:
                break
            text = page.get_text()
            for k, m in enumerate(HEX.finditer(text)):
                h = norm_hex(m.group(1) or m.group(2))
                if h:
                    # имя — подпись до кода и пояснение после («основной: логотип, акценты»); цвет, названный
                    # в гайдлайне раньше, обычно важнее
                    colors.append(BrandColor(hex=h, name=f"{_label(text, m.start())} · {_after(text, m.end())}",
                                             weight=12 + max(0.0, 6 - 1.5 * k), source="pdf"))
            for m in RGB.finditer(text):
                g = [x for x in m.groups() if x is not None]
                if len(g) == 3 and all(int(x) <= 255 for x in g):
                    colors.append(BrandColor(hex="%02X%02X%02X" % tuple(int(x) for x in g), name=_label(text, m.start()),
                                             weight=10, source="pdf"))
            for m in CMYK.finditer(text):
                colors.append(BrandColor(hex=_cmyk(*m.groups()), name=_label(text, m.start()), weight=6, source="pdf"))
            for m in FONT_TXT.finditer(text):
                role = "heading" if re.search(r"(заголов|head|title|display)", m.group(1) or "", re.I) else \
                    "body" if re.search(r"(текст|основн|body|text)", m.group(1) or "", re.I) else ""
                fonts[(m.group(2).strip(), role)] += 8
            if (mm := MIN_LOGO.search(text)) and kit.logo_min_h is None:
                v = float(mm.group(1).replace(",", "."))
                kit.logo_min_h = v * (960 / 297 if mm.group(2).lower() in ("мм", "mm") else 1.0)  # мм A4 → px сетки
            if (mc := CLEAR.search(text)) and kit.logo_clear is None:
                w = mc.group(1).lower()
                kit.logo_clear = 0.5 if w.startswith("половин") else 1 / 3 if w.startswith("треть") else 0.25 \
                    if w.startswith("четверт") else float((mc.group(2) or "50").replace(",", ".")) / 100
            for f in page.get_fonts(full=False):
                base = re.sub(r"^[A-Z]{6}\+", "", f[3] or "")
                fam = re.sub(r"[-,](Bold|Regular|Medium|Light|Italic|Semibold|SemiBold|Black|Thin|Book|Heavy).*$", "", base)
                fam = re.sub(r"(MT|PS)$", "", fam).replace("-", " ").strip()
                if fam:
                    fonts[(fam, "")] += 1
            for line in text.split("\n"):
                ln = line.strip()
                if 12 <= len(ln) <= 180 and RULE.search(ln) and ln not in rules:
                    rules.append(ln)
            # картинки страницы: крупные с прозрачностью — кандидаты в логотипы
            for img in page.get_images(full=True):
                xref, smask = img[0], img[1]
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                w, h = info.get("width", 0), info.get("height", 0)
                if w * h < 4000:
                    continue
                logo_cands.append((bool(smask), pi, w * h, xref, smask))
            if pi < 12:
                pix = page.get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5))
                p = out_dir / f"page{pi + 1}.png"
                pix.save(str(p))
                renders.append(p)
        # логотип: картинка с прозрачностью с первых страниц
        logo_cands.sort(key=lambda x: (not x[0], x[1], -x[2]))
        for has_mask, pi, area, xref, smask in logo_cands[:6]:
            if len(kit.logos) >= 2:
                break
            try:
                pix = pymupdf.Pixmap(doc, xref)
                if smask:
                    pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, smask))
                if pix.n - pix.alpha >= 4:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                lp = out_dir / f"logo{len(kit.logos) + 1}.png"
                pix.save(str(lp))
                from .fig import _is_light_mark
                dark = _is_light_mark(lp)
                if any(lg.dark_bg == dark for lg in kit.logos):
                    continue                       # нужен второй вариант, а не копия первого
                kit.logos.append(BrandLogo(name=f"логотип со страницы {pi + 1}", png=str(lp), w=pix.width, h=pix.height,
                                           dark_bg=dark))
            except Exception:
                continue
        doc.close()
    # палитра по площади — подтверждает цвета из текста и добавляет те, что не подписаны
    for hexv, share in palette_by_area(renders):
        colors.append(BrandColor(hex=hexv, weight=share * 40 * (2 if chroma(hexv) >= 0.25 else 0.5), source="image"))
    kit.colors = colors[:40]
    kit.palette, kit.accents = assign_roles(colors)
    # подписанные в тексте роли («шрифт заголовков») — именем стиля, чтобы pick_fonts их учёл
    fl = [BrandFont(family=f, name={"heading": "Heading", "body": "Body text"}.get(r, ""), weight=w)
          for (f, r), w in fonts.most_common(8)]
    kit.font_styles = fl
    kit.fonts = pick_fonts(fl)
    kit.rules = rules[:10]
    if not any(c.source == "pdf" for c in colors):
        kit.warnings.append("в тексте PDF нет кодов цветов (HEX/RGB/CMYK) — палитра взята по картинкам страниц")
    if not kit.logos:
        kit.warnings.append("в PDF не найден логотип с прозрачностью — приложите его PNG или SVG")
    return kit

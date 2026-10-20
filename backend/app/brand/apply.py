"""Применение брендбука к оформлению.

Встроенный стиль: цвета ролей, шрифты и логотип → StyleSpec.with_overrides → свой пак (кэшируется).
Шаблон компании: производный шаблон — копия template.pptx, в которой
  • тема: a:clrScheme (accent1–6) и a:fontScheme (major/minor latin) — цвета и шрифты бренда;
  • слайды, макеты, мастер: явные srgbClr фирменных цветов шаблона заменены на роли бренда
    (основной → основной, акценты → акценты), нейтральные (фон, текст) не трогаются;
  • шрифты шаблона заменены шрифтами бренда, если они есть в системе (иначе — предупреждение);
  • картинки на месте логотипа шаблона заменены логотипом бренда с сохранением пропорций.
Затем производный шаблон проходит обычный разбор (parse_template) — дальше пайплайн не отличает его от загруженного.
Приоритет: брендбук важнее шаблона (Brief.brand_priority = "brand"); при "template" меняются только логотипы.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Optional

from lxml import etree

from .model import BrandKit, chroma, dist, hls

log = logging.getLogger("brand.apply")
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# ------------------------------------------------------------------ логотипы: вариант под светлый и тёмный фон
def _tinted(src: str, color: str, out: Path, light_to: bool) -> str:
    """Перекрашивает светлые (light_to=True: белый знак → цвет) или тёмные пиксели знака, альфа сохраняется."""
    import numpy as np
    from PIL import Image
    im = Image.open(src).convert("RGBA")
    a = np.asarray(im).astype(np.float32)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    sat = a[..., :3].max(axis=-1) - a[..., :3].min(axis=-1)
    mask = ((lum > 190) if light_to else (lum < 70)) & (sat < 40) & (a[..., 3] > 0)
    rgb = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
    for k in range(3):
        a[..., k] = np.where(mask, rgb[k], a[..., k])
    Image.fromarray(a.astype(np.uint8), "RGBA").save(out)
    return str(out)


def logo_pair(kit: BrandKit) -> tuple[str, str]:
    """(логотип для светлого фона, для тёмного). Недостающий вариант получаем перекраской знака."""
    if not kit.logos:
        return "", ""
    light = next((lg.png for lg in kit.logos if not lg.dark_bg and Path(lg.png).exists()), "")
    dark = next((lg.png for lg in kit.logos if lg.dark_bg and Path(lg.png).exists()), "")
    text = kit.palette.get("text", "1A1A1A")
    try:
        if not light and dark:
            light = _tinted(dark, text, Path(dark).with_name(Path(dark).stem + "_onlight.png"), light_to=True)
        if not dark and light:
            dark = _tinted(light, "FFFFFF", Path(light).with_name(Path(light).stem + "_ondark.png"), light_to=False)
    except Exception as e:
        log.warning("logo tint failed: %s", e)
    return light, dark


# ------------------------------------------------------------------ шрифты
def usable_font(family: str) -> bool:
    if not family:
        return False
    from ..parsing.fonts import font_available, try_fetch_google_font
    try:
        return font_available(family) or try_fetch_google_font(family)
    except Exception:
        return font_available(family)


def brand_fonts(kit: BrandKit, warnings: list[str]) -> dict[str, str]:
    out = {}
    for role in ("heading", "body"):
        fam = kit.fonts.get(role, "")
        if not fam:
            continue
        if usable_font(fam):
            out[role] = fam
        else:
            msg = f"шрифта бренда «{fam}» нет в системе и в Google Fonts — оставлен шрифт оформления"
            if msg not in warnings:
                warnings.append(msg)
    return out


# ------------------------------------------------------------------ встроенный стиль
def style_args(kit: BrandKit, warnings: list[str]) -> dict:
    p = kit.palette
    colors = {k: v for k, v in {
        "background": p.get("bg"), "primary": p.get("primary"), "secondary": p.get("secondary") or (kit.accents[:1] or [None])[0],
        "auxiliary": (kit.accents[1:2] or kit.accents[:1] or [p.get("secondary")])[0], "dark": p.get("bg_dark"),
        "text": p.get("text"), "muted": p.get("muted")}.items() if v}
    light, dark = logo_pair(kit)
    grid = {"margin": kit.spacing.get("margin"), "radius": kit.spacing.get("radius"),
            "logo_min_h": kit.logo_min_h, "logo_clear": kit.logo_clear}
    return {"colors": colors, "fonts": brand_fonts(kit, warnings), "logo": light, "logo_dark": dark,
            "brand_name": kit.name, "grid": {k: v for k, v in grid.items() if v is not None}}


# ------------------------------------------------------------------ шаблон компании
def _shade(base: str, ref: str, c: str) -> str:
    """Оттенок c цвета ref → такой же по светлоте оттенок base (светлый синий → светлый розовый)."""
    from ..styles.model import _mix
    lc, lr = hls(c)[1], hls(ref)[1]
    if abs(lc - lr) < 0.03:
        return base
    if lc > lr:
        return _mix(base, "FFFFFF", min(0.9, (lc - lr) / max(0.01, 1 - lr)))
    return _mix(base, "000000", min(0.9, (lr - lc) / max(0.01, lr)))


def _color_map(profile, kit: BrandKit, used: dict[str, int] | None = None) -> dict[str, str]:
    """Фирменные (насыщенные) цвета шаблона → роли бренда, нейтральные остаются.

    Цвета шаблона группируются по тону: семейство основного цвета (0077FF, 8CC2FF, 4CA0FF — один синий
    в разной светлоте) становится семейством основного цвета бренда, следующие семейства — акцентами бренда."""
    pal = profile.palette
    src = [pal.primary] + [c for c in pal.accents if c] + [c for c in pal.chart if c] + \
        [x["hex"] for x in pal.colors if x.get("hex")]
    # плюс все насыщенные цвета, которые реально стоят в слайдах и макетах (заголовки, плашки), по частоте
    src += [c for c, _ in sorted((used or {}).items(), key=lambda kv: -kv[1])]
    src = [c.upper() for c in dict.fromkeys(x.upper() for x in src if x) if chroma(c.upper()) >= 0.25]
    dst = [d for d in dict.fromkeys([kit.palette.get("primary"), kit.palette.get("secondary")] + kit.accents) if d]
    if not src or not dst:
        return {}
    families: list[list[str]] = []
    for c in src:
        fam = next((f for f in families if min(abs(hls(c)[0] - hls(f[0])[0]), 1 - abs(hls(c)[0] - hls(f[0])[0])) < 0.05), None)
        if fam is None:
            families.append([c])
        else:
            fam.append(c)
    m: dict[str, str] = {}
    for i, fam in enumerate(families):
        base = dst[min(i, len(dst) - 1)]
        ref = fam[0]
        for c in fam:
            m[c] = _shade(base, ref, c)
    return m


def mapped_palette(profile, kit: BrandKit, cmap: dict[str, str]):
    """Палитра производного шаблона: роли известны точно — не угадываем их заново по площадям."""
    pal = profile.palette.model_copy(deep=True)
    f = lambda c: cmap.get((c or "").upper(), c)            # noqa: E731
    pal.primary = kit.palette.get("primary") or f(pal.primary)
    pal.accents = [a for a in dict.fromkeys([kit.palette.get("secondary")] + kit.accents + [f(a) for a in pal.accents]) if a][:4]
    pal.chart = [c for c in dict.fromkeys([pal.primary] + [f(c) for c in pal.chart] + pal.accents) if c][:6]
    pal.colors = [{**x, "hex": f(x.get("hex"))} for x in pal.colors]
    # все цвета, в которые перекрашен шаблон, — «свои» для аудита палитры
    have = {x.get("hex") for x in pal.colors}
    pal.colors += [{"hex": c, "weight": 0.0, "role": "brand"} for c in dict.fromkeys(cmap.values()) if c not in have]
    return pal


def _theme(xml: bytes, kit: BrandKit, fonts: dict[str, str], cmap: dict[str, str] | None = None) -> bytes:
    root = etree.fromstring(xml)
    ns = {"a": A}
    cs = root.find(".//a:clrScheme", ns)
    roles = [kit.palette.get("primary"), kit.palette.get("secondary")] + kit.accents
    roles = [r for r in dict.fromkeys(roles) if r]
    if cs is not None and roles:
        for i in range(6):
            el = cs.find(f"a:accent{i + 1}", ns)
            if el is None:
                continue
            for ch in list(el):
                el.remove(ch)
            etree.SubElement(el, f"{{{A}}}srgbClr", val=roles[i % len(roles)])
        # тёмный/светлый цвет 2 и ссылки бывают фирменными (синие заголовки) — их тоже в цвета бренда
        for tag in ("dk2", "lt2", "hlink", "folHlink"):
            clr = cs.find(f"a:{tag}/a:srgbClr", ns)
            if clr is not None and cmap and clr.get("val", "").upper() in cmap:
                clr.set("val", cmap[clr.get("val").upper()])
    fs = root.find(".//a:fontScheme", ns)
    if fs is not None:
        for tag, role in (("majorFont", "heading"), ("minorFont", "body")):
            lat = fs.find(f"a:{tag}/a:latin", ns)
            if lat is not None and fonts.get(role):
                lat.set("typeface", fonts[role])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _part(xml: bytes, cmap: dict[str, str], fmap: dict[str, str]) -> bytes:
    s = xml.decode("utf-8")
    if cmap:
        s = re.sub(r'(<a:srgbClr\s+val=")([0-9A-Fa-f]{6})(")', lambda m: m.group(1) + cmap.get(m.group(2).upper(), m.group(2)) + m.group(3), s)
    if fmap:
        s = re.sub(r'(<a:(?:latin|ea|cs)\s+typeface=")([^"]+)(")', lambda m: m.group(1) + fmap.get(m.group(2), m.group(2)) + m.group(3), s)
    return s.encode("utf-8")


def _box(el) -> Optional[tuple[int, int, int, int]]:
    xf = el.find(f"{{{P}}}spPr/{{{A}}}xfrm")
    if xf is None:
        xf = el.find(f"{{{P}}}grpSpPr/{{{A}}}xfrm")
    if xf is None:
        return None
    off, ext = xf.find(f"{{{A}}}off"), xf.find(f"{{{A}}}ext")
    if off is None or ext is None:
        return None
    return int(off.get("x", 0)), int(off.get("y", 0)), int(ext.get("cx", 0)), int(ext.get("cy", 0))


def _leaf_media(el, rels: dict[str, str]) -> Optional[list[str]]:
    """Картинки элемента (картинка или группа из одних картинок); None — если внутри есть фигуры с текстом."""
    if el.tag == f"{{{P}}}pic":
        blip = el.find(f".//{{{A}}}blip")
        t = rels.get(blip.get(f"{{{R}}}embed")) if blip is not None else None
        return [t] if t else None
    if el.tag == f"{{{P}}}sp":
        # подложка или рамка без текста внутри группы логотипа допустима; фигура с текстом — уже не логотип
        has_text = any((t.text or "").strip() for t in el.iter(f"{{{A}}}t"))
        return None if has_text else []
    if el.tag != f"{{{P}}}grpSp":
        return None
    out = []
    for ch in el:
        if ch.tag in (f"{{{P}}}nvGrpSpPr", f"{{{P}}}grpSpPr"):
            continue
        sub = _leaf_media(ch, rels)
        if sub is None:
            return None
        out += sub
    return out if 0 < len(out) <= 4 else None


def find_logos(parts: dict[str, bytes], W: int, H: int) -> dict[str, list[tuple[int, tuple, list[str]]]]:
    """Логотип шаблона — общее правило: небольшая картинка или группа картинок у края слайда, которая стоит
    в одном и том же месте хотя бы в трёх слайдах/макетах. → {часть: [(индекс в spTree, рамка, картинки)]}."""
    from collections import defaultdict
    seen: dict[tuple, list] = defaultdict(list)
    for name, data in parts.items():
        if not re.match(r"ppt/(slides|slideLayouts|slideMasters)/[^/]+\.xml$", name):
            continue
        rels_name = re.sub(r"([^/]+)$", r"_rels/\1.rels", name)
        rels = {r.get("Id"): r.get("Target") for r in etree.fromstring(parts[rels_name])} if rels_name in parts else {}
        tree = etree.fromstring(data).find(f".//{{{P}}}cSld/{{{P}}}spTree")
        if tree is None:
            continue
        for i, el in enumerate(tree):
            box = _box(el)
            media = _leaf_media(el, rels)
            if not box or not media:
                continue
            x, y, w, h = box
            if not (0 < w < 0.28 * W and 0 < h < 0.2 * H):
                continue
            if not (y + h > 0.75 * H or y < 0.35 * H):      # верхняя треть или нижняя четверть слайда
                continue
            key = (round(x / W, 2), round(y / H, 2), round(w / W, 2), round(h / H, 2), len(media))
            seen[key].append((name, i, box, media))
    out: dict[str, list] = defaultdict(list)
    known: set[str] = set()
    need = 3 if any(len({n for n, *_ in h}) >= 3 for h in seen.values()) else 2
    if need == 2:
        # логотип на обложке и финале стоит в разных местах — тогда сводим по одним и тем же файлам картинок
        by_media: dict[tuple, list] = defaultdict(list)
        for hits in seen.values():
            for hit in hits:
                by_media[tuple(sorted(m.split("/")[-1] for m in hit[3]))].append(hit)
        seen = by_media
    for key, hits in seen.items():
        if len({n for n, *_ in hits}) >= need:
            for name, i, box, media in hits:
                out[name].append((i, box, media))
                known |= {m.split("/")[-1] for m in media}
    # тот же знак крупно (обложка, финал) — из тех же картинок, что и найденный логотип, в любом размере
    if known:
        for name, data in parts.items():
            if not re.match(r"ppt/(slides|slideLayouts|slideMasters)/[^/]+\.xml$", name):
                continue
            rels_name = re.sub(r"([^/]+)$", r"_rels/\1.rels", name)
            rels = {r.get("Id"): r.get("Target") for r in etree.fromstring(parts[rels_name])} if rels_name in parts else {}
            tree = etree.fromstring(data).find(f".//{{{P}}}cSld/{{{P}}}spTree")
            if tree is None:
                continue
            have = {i for i, *_ in out.get(name, [])}
            for i, el in enumerate(tree):
                media = _leaf_media(el, rels)
                box = _box(el)
                if i in have or not media or not box or box[2] > 0.6 * W:
                    continue
                if {m.split("/")[-1] for m in media} <= known:
                    out[name].append((i, box, media))
    return out


def _media_light(parts: dict[str, bytes], part: str, media: list[str]) -> bool:
    """Исходный логотип светлый (белый знак) → он стоит на тёмном фоне."""
    import numpy as np
    from PIL import Image
    lums = []
    for t in media:
        path = re.sub(r"[^/]+/\.\./", "", str(Path(part).parent.joinpath(t)).replace("\\", "/"))
        try:
            im = Image.open(io.BytesIO(parts[path])).convert("RGBA")
        except Exception:
            continue
        a = np.asarray(im).astype(float)
        m = a[..., 3] > 128
        if m.any():
            lums.append((0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2])[m].mean())
    return bool(lums) and float(np.mean(lums)) > 185


def _replace_logos(parts: dict[str, bytes], found: dict, light: str, dark: str, W: int, min_h: int = 0) -> int:
    """Каждое найденное место логотипа шаблона → одна картинка логотипа бренда (вписана по высоте рамки)."""
    from PIL import Image
    n_done = 0
    media = {}
    for key, src in (("brandlogo_l.png", light), ("brandlogo_d.png", dark)):
        if src and Path(src).exists():
            parts[f"ppt/media/{key}"] = Path(src).read_bytes()
            with Image.open(src) as im:
                media[key] = im.width / max(1, im.height)
    if not media:
        return 0
    ct = parts.get("[Content_Types].xml", b"").decode("utf-8")
    if 'Extension="png"' not in ct:
        ct = ct.replace("<Default ", '<Default Extension="png" ContentType="image/png"/><Default ', 1)
        parts["[Content_Types].xml"] = ct.encode("utf-8")
    for name, items in found.items():
        root = etree.fromstring(parts[name])
        tree = root.find(f".//{{{P}}}cSld/{{{P}}}spTree")
        rels_name = re.sub(r"([^/]+)$", r"_rels/\1.rels", name)
        rels = etree.fromstring(parts[rels_name]) if rels_name in parts else etree.Element(
            "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships")
        ids = [int(x.get("id")) for x in root.iter() if x.tag.endswith("}cNvPr") and str(x.get("id", "")).isdigit()]
        next_id = max(ids, default=100) + 1
        kids = list(tree)
        for i, box, src_media in sorted(items, key=lambda t: -t[0]):
            key = "brandlogo_d.png" if _media_light(parts, name, src_media) and "brandlogo_d.png" in media else \
                "brandlogo_l.png" if "brandlogo_l.png" in media else "brandlogo_d.png"
            rid = f"rIdBrand{key[10]}"
            if not any(r.get("Id") == rid for r in rels):
                etree.SubElement(rels, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship",
                                 Id=rid, Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                                 Target=f"../media/{key}")
            x, y, w, h = box
            ar = media[key]
            nh = max(h, min_h)                     # минимальная высота логотипа по брендбуку
            nw = int(nh * ar)
            if nw > 2.2 * w:                       # длинный словесный знак — не шире двух рамок
                nw = int(2.2 * w)
                nh = int(nw / ar)
            nx = x if x + w / 2 < W / 2 else x + w - nw       # у левого края — от левого, у правого — от правого
            ny = y + (h - nh) // 2
            pic = etree.fromstring(
                f'<p:pic xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:nvPicPr><p:cNvPr id="{next_id}" name="Brand logo"/>'
                f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
                f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
                f'<p:spPr><a:xfrm><a:off x="{nx}" y="{ny}"/><a:ext cx="{nw}" cy="{nh}"/></a:xfrm>'
                f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
            next_id += 1
            old = kids[i]
            tree.replace(old, pic)
            n_done += 1
        parts[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        parts[rels_name] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    return n_done


def derive_template(profile, kit: BrandKit, priority: str = "brand", warnings: Optional[list[str]] = None) -> str:
    """Шаблон компании + брендбук → id производного шаблона (готов к генерации)."""
    from ..parsing.profile import load_profile, parse_template, template_dir
    warnings = warnings if warnings is not None else []
    tid = f"{profile.id}-brand-{kit.id}-{'b' if priority == 'brand' else 't'}"
    if load_profile(tid) is not None:
        return tid
    src = Path(profile.file) if Path(profile.file).exists() else template_dir(profile.id) / "template.pptx"
    fonts = brand_fonts(kit, warnings) if priority == "brand" else {}
    with zipfile.ZipFile(src) as z:
        used: dict[str, int] = {}
        for n in z.namelist():
            if re.match(r"ppt/(slides|slideLayouts|slideMasters|theme)/[^/]+\.xml$", n):
                for v in re.findall(r'<a:srgbClr\s+val="([0-9A-Fa-f]{6})"', z.read(n).decode("utf-8", "ignore")):
                    used[v.upper()] = used.get(v.upper(), 0) + 1
    cmap = _color_map(profile, kit, used) if priority == "brand" else {}
    fmap = {}
    for old, role in ((profile.typography.heading_font, "heading"), (profile.typography.body_font, "body")):
        if old and fonts.get(role) and old != fonts[role]:
            fmap[old] = fonts[role]
    light, dark = logo_pair(kit)
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i.filename) for i in infos}
    for n in list(parts):
        if re.match(r"ppt/theme/theme\d+\.xml$", n) and priority == "brand":
            parts[n] = _theme(parts[n], kit, fonts, cmap)
        elif re.match(r"ppt/(slides|slideLayouts|slideMasters)/[^/]+\.xml$", n):
            parts[n] = _part(parts[n], cmap, fmap)
    n_logo = 0
    if kit.logos and (light or dark):
        found = find_logos(parts, profile.slide_w, profile.slide_h)
        min_h = int(kit.logo_min_h * profile.slide_h / 540) if kit.logo_min_h else 0
        n_logo = _replace_logos(parts, found, light, dark, profile.slide_w, min_h) if found else 0
        if not n_logo:
            warnings.append("логотип шаблона не найден (нарисован фигурами или стоит на одном слайде) — "
                            "логотип бренда не подставлен")
    d = template_dir(tid)
    d.mkdir(parents=True, exist_ok=True)
    out_pptx = d / "derived.pptx"
    buf = io.BytesIO()
    order = [i.filename for i in infos] + [n for n in parts if n not in {i.filename for i in infos}]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as w:
        for n in order:
            w.writestr(n, parts[n])
    out_pptx.write_bytes(buf.getvalue())
    extra = {"image_style": profile.image_style, "style_summary": profile.style_summary, "narrative": profile.narrative}
    if priority == "brand":
        extra["palette"] = mapped_palette(profile, kit, cmap)
    prof = parse_template(out_pptx, name=f"{profile.name} · {kit.name}", use_llm=False, tid=tid, extra=extra)
    log.info("brand template %s: colors %d, fonts %s, logos %d", tid, len(cmap), fmap, n_logo)
    return prof.id

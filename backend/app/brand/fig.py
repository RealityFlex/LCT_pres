"""Брендбук из файла Figma (.fig): свой разбор формата, без Figma и без сети.

Файл .fig — ZIP: canvas.fig (заголовок «fig-kiwi», версия, блок схемы kiwi (deflate) и блок данных
(zstd или deflate)), images/<sha1> — растровые картинки, meta.json, thumbnail.png.
Данные — сообщение Message, в нём nodeChanges: плоский список узлов с parentIndex.

Что достаём:
  цвета — стили заливки (styleType FILL) с именами, переменные-цвета и реальные заливки (вес — площадь);
  шрифты — текстовые стили (имя, семейство, кегль) и тексты макетов (вес — число символов);
  логотипы — узлы с «logo/лого» в имени: вектор собирается в SVG из fillGeometry, картинка — из images/;
  примеры слайдов — фреймы 16:9 верхнего уровня (имя, страница, размер, фон).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import re
import struct
import zipfile
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from .kiwi import Decoder, parse_schema
from .model import BrandColor, BrandFont, BrandKit, BrandLogo, assign_roles, pick_fonts

log = logging.getLogger("brand.fig")

SKIP = ("derivedSymbolData", "derivedTextData", "glyphs", "overrideStash", "overrideStashV2", "vectorData",
        "componentPropAssignments", "fontMetaData", "baselines", "decorations")
LOGO_NAME = re.compile(r"(logo|лого|логотип|brand ?mark|знак)", re.I)
NOT_LOGO = re.compile(r"(placeholder|\bwf\b|заглушк|partner|партн|atlassian|jira|slack|google|apple|github)", re.I)


class FigError(ValueError):
    pass


def _hex(c: dict) -> str:
    return "%02X%02X%02X" % tuple(max(0, min(255, round(c.get(k, 0) * 255))) for k in ("r", "g", "b"))


def _gid(g: Optional[dict]) -> Optional[str]:
    return f"{g['sessionID']}:{g['localID']}" if g else None


def _chunks(data: bytes) -> list[bytes]:
    if data[:8] != b"fig-kiwi":
        raise FigError("это не файл Figma: нет заголовка fig-kiwi")
    pos, out = 12, []
    while pos + 4 <= len(data):
        n = struct.unpack("<I", data[pos:pos + 4])[0]
        out.append(data[pos + 4:pos + 4 + n])
        pos += 4 + n
    return out


def _inflate(chunk: bytes) -> bytes:
    if chunk[:4] == b"\x28\xb5\x2f\xfd":
        try:
            import zstandard
        except ImportError as e:   # pragma: no cover
            raise FigError("для этого .fig нужен пакет zstandard") from e
        return zstandard.ZstdDecompressor().decompressobj().decompress(chunk)
    for wbits in (-15, 15):
        try:
            return zlib.decompress(chunk, wbits)
        except zlib.error:
            continue
    raise FigError("неизвестное сжатие блока .fig")


@dataclass
class FigDoc:
    name: str
    nodes: list[dict]
    blobs: list[bytes]
    images: dict[str, bytes]               # sha1 (hex) → байты картинки
    thumbnail: bytes = b""
    by_id: dict[str, dict] = field(default_factory=dict)
    kids: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    page_of: dict[str, str] = field(default_factory=dict)

    def index(self) -> None:
        self.by_id = {_gid(n.get("guid")): n for n in self.nodes}
        for n in self.nodes:
            p = n.get("parentIndex")
            if p:
                self.kids[_gid(p["guid"])].append(n)
        for lst in self.kids.values():
            lst.sort(key=lambda n: (n.get("parentIndex") or {}).get("position", ""))
        for n in self.nodes:
            if n.get("type") == "CANVAS":
                stack = [n]
                while stack:
                    x = stack.pop()
                    self.page_of[_gid(x.get("guid"))] = n.get("name", "")
                    stack.extend(self.kids.get(_gid(x.get("guid")), []))


def load(data: bytes, name: str = "") -> FigDoc:
    """Разбор .fig (ZIP или «голый» canvas.fig)."""
    images: dict[str, bytes] = {}
    thumb = b""
    meta_name = ""
    if data[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise FigError("повреждённый .fig (ZIP не читается)") from e
        names = z.namelist()
        canvas = next((n for n in names if n.endswith("canvas.fig")), None)
        if canvas is None:
            raise FigError("в архиве .fig нет canvas.fig")
        raw = z.read(canvas)
        for n in names:
            if n.startswith("images/") and not n.endswith("/"):
                images[n.split("/")[-1].lower()] = z.read(n)
        if "thumbnail.png" in names:
            thumb = z.read("thumbnail.png")
        if "meta.json" in names:
            try:
                meta_name = json.loads(z.read("meta.json")).get("file_name", "")
            except Exception:
                pass
    else:
        raw = data
    chunks = _chunks(raw)
    if len(chunks) < 2:
        raise FigError("в .fig нет блока данных")
    schema = parse_schema(_inflate(chunks[0]))
    if "Message" not in schema or "NodeChange" not in schema:
        raise FigError("неизвестная схема .fig: нет Message/NodeChange")
    try:
        msg = Decoder(schema, skip=SKIP).decode(_inflate(chunks[1]))
    except Exception as e:
        raise FigError(f"не удалось раскодировать данные .fig: {e}") from e
    blobs = [b.get("bytes", b"") for b in msg.get("blobs", [])]
    doc = FigDoc(name=meta_name or re.sub(r"\.fig$", "", name), nodes=msg.get("nodeChanges", []), blobs=blobs,
                 images=images, thumbnail=thumb)
    doc.index()
    return doc


# ------------------------------------------------------------------ векторы → SVG
def _path(blob: bytes, m: tuple) -> str:
    """Команды геометрии Figma: 0 — закрыть, 1 — moveTo, 2 — lineTo, 3 — quadTo, 4 — cubicTo (float32 LE)."""
    a, b, c, d, e, f = m
    out = []
    i, n = 0, len(blob)

    def pt(j):
        x, y = struct.unpack_from("<ff", blob, j)
        return f"{a * x + b * y + c:.2f} {d * x + e * y + f:.2f}"
    while i < n:
        cmd = blob[i]
        i += 1
        if cmd == 0:
            out.append("Z")
        elif cmd == 1:
            out.append("M" + pt(i)); i += 8
        elif cmd == 2:
            out.append("L" + pt(i)); i += 8
        elif cmd == 3:
            out.append("Q" + pt(i) + " " + pt(i + 8)); i += 16
        elif cmd == 4:
            out.append("C" + pt(i) + " " + pt(i + 8) + " " + pt(i + 16)); i += 24
        else:
            break
    return " ".join(out)


def _mul(p: tuple, t: Optional[dict]) -> tuple:
    if not t:
        return p
    a, b, c, d, e, f = p
    A, B, C, D, E, F = t.get("m00", 1), t.get("m01", 0), t.get("m02", 0), t.get("m10", 0), t.get("m11", 1), t.get("m12", 0)
    return (a * A + b * D, a * B + b * E, a * C + b * F + c, d * A + e * D, d * B + e * E, d * C + e * F + f)


def _paint(p: dict, op: float) -> Optional[tuple[str, float]]:
    if not p.get("visible", True):
        return None
    alpha = float(p.get("opacity", 1.0)) * op
    if p.get("type") == "SOLID" and p.get("color"):
        return _hex(p["color"]), alpha * float(p["color"].get("a", 1.0))
    if str(p.get("type", "")).startswith("GRADIENT") and p.get("stops"):
        c = p["stops"][0].get("color") or {}
        return _hex(c), alpha * float(c.get("a", 1.0))
    return None


class SvgBuilder:
    def __init__(self, doc: FigDoc):
        self.doc = doc
        self.parts: list[str] = []
        self.depth = 0

    def node(self, n: dict, m: tuple, op: float) -> None:
        if not n.get("visible", True) or self.depth > 40:
            return
        op = op * float(n.get("opacity", 1.0))
        if op <= 0.01:
            return
        t = n.get("type")
        for p in n.get("fillPaints") or []:
            if p.get("type") == "IMAGE" and p.get("visible", True) and p.get("image", {}).get("hash"):
                h = p["image"]["hash"]
                h = h.hex() if isinstance(h, (bytes, bytearray)) else str(h)
                data = self.doc.images.get(h.lower())
                if data:
                    import base64
                    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
                    sz = n.get("size") or {}
                    self.parts.append(f'<image transform="matrix({m[0]:.4f} {m[3]:.4f} {m[1]:.4f} {m[4]:.4f} {m[2]:.2f} {m[5]:.2f})" '
                                      f'width="{sz.get("x", 0):.2f}" height="{sz.get("y", 0):.2f}" preserveAspectRatio="xMidYMid slice" '
                                      f'opacity="{op:.3f}" href="data:{mime};base64,{base64.b64encode(data).decode()}"/>')
        if t == "TEXT":
            td = n.get("textData") or {}
            txt = td.get("characters", "").strip()
            fp = next((x for x in (_paint(p, op) for p in n.get("fillPaints") or []) if x), None)
            if txt and fp:
                fs = float(n.get("fontSize") or 12)
                fam = (n.get("fontName") or {}).get("family", "sans-serif")
                bold = re.search(r"(bold|black|heavy|semi|demi)", (n.get("fontName") or {}).get("style", ""), re.I)
                for k, line in enumerate(txt.split("\n")[:6]):
                    y = fs * (0.85 + 1.2 * k)
                    self.parts.append(f'<text transform="matrix({m[0]:.4f} {m[3]:.4f} {m[1]:.4f} {m[4]:.4f} {m[2]:.2f} {m[5]:.2f})" '
                                      f'y="{y:.1f}" font-family="{escape(fam)}" font-size="{fs:.1f}" '
                                      f'{"font-weight=" + chr(34) + "bold" + chr(34) if bold else ""} fill="#{fp[0]}" '
                                      f'fill-opacity="{fp[1]:.3f}">{escape(line)}</text>')
        else:
            for key, paints in (("fillGeometry", n.get("fillPaints")), ("strokeGeometry", n.get("strokePaints"))):
                geo = n.get(key) or []
                fp = next((x for x in (_paint(p, op) for p in paints or []) if x), None)
                if not geo or fp is None:
                    continue
                for g in geo:
                    bi = g.get("commandsBlob")
                    if bi is None or bi >= len(self.doc.blobs):
                        continue
                    d = _path(self.doc.blobs[bi], m)
                    if d:
                        rule = "evenodd" if g.get("windingRule") in ("EVENODD", "ODD") else "nonzero"
                        self.parts.append(f'<path d="{d}" fill="#{fp[0]}" fill-opacity="{fp[1]:.3f}" fill-rule="{rule}"/>')
        kids = self.doc.kids.get(_gid(n.get("guid")), [])
        if t == "INSTANCE" and not kids:
            sym = self.doc.by_id.get(_gid((n.get("symbolData") or {}).get("symbolID")))
            kids = self.doc.kids.get(_gid(sym.get("guid")), []) if sym else []
        self.depth += 1
        for k in kids:
            self.node(k, _mul(m, k.get("transform")), op)
        self.depth -= 1

    def render(self, root: dict) -> tuple[str, float, float]:
        sz = root.get("size") or {"x": 100, "y": 100}
        w, h = float(sz.get("x", 100)), float(sz.get("y", 100))
        self.parts = []
        # фон самого фрейма логотипа не рисуем — нужен знак на прозрачном фоне
        bare = dict(root)
        bare["fillPaints"] = [p for p in root.get("fillPaints") or [] if p.get("type") == "IMAGE"]
        self.node(bare, (1, 0, 0, 0, 1, 0), 1.0)
        body = "\n".join(self.parts)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.2f} {h:.2f}" width="{w:.2f}" height="{h:.2f}">\n'
                f"{body}\n</svg>"), w, h


def svg_to_png(svg: str, out: Path, width: int = 600) -> bool:
    try:
        import pymupdf
        from ..core.mupdf_lock import LOCK
        with LOCK:
            doc = pymupdf.open(stream=svg.encode("utf-8"), filetype="svg")
            page = doc[0]
            k = width / max(1.0, page.rect.width)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(k, k), alpha=True)
            pix.save(str(out))
            doc.close()
        return out.exists()
    except Exception as e:
        log.warning("svg → png failed: %s", e)
        return False


# ------------------------------------------------------------------ брендбук
def _area(n: dict) -> float:
    s = n.get("size") or {}
    return max(0.0, float(s.get("x", 0)) * float(s.get("y", 0)))


def _variables(doc: FigDoc) -> list[BrandColor]:
    """Переменные-цвета (Figma Variables): значение первого режима."""
    out = []
    for n in doc.nodes:
        if n.get("type") != "VARIABLE":
            continue
        name = n.get("name", "")
        stack = [n.get("variableDataValues")]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if "colorValue" in x and isinstance(x["colorValue"], dict):
                    out.append(BrandColor(hex=_hex(x["colorValue"]), name=name, weight=50, source="variable"))
                    break
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return out


def _logos(doc: FigDoc) -> list[dict]:
    cand = []
    for n in doc.nodes:
        name = n.get("name", "")
        if not LOGO_NAME.search(name) or NOT_LOGO.search(name) or not n.get("visible", True):
            continue
        if n.get("type") not in ("FRAME", "SYMBOL", "INSTANCE", "GROUP", "VECTOR", "BOOLEAN_OPERATION", "RECTANGLE",
                                 "ROUNDED_RECTANGLE"):
            continue
        has_img = any(p.get("type") == "IMAGE" for p in n.get("fillPaints") or [])
        kids = doc.kids.get(_gid(n.get("guid")), [])
        if not (has_img or kids or n.get("fillGeometry") or n.get("symbolData")):
            continue
        s = n.get("size") or {}
        w, h = float(s.get("x", 0)), float(s.get("y", 0))
        if w < 8 or h < 8:
            continue
        # бренд файла в имени логотипа — сильный сигнал; мастер-компонент лучше копии
        brand = re.sub(r"[^a-zа-яё]+", " ", doc.name.lower()).split()
        sc = (3 if any(len(b) > 2 and b in name.lower() for b in brand) else 0) + (1 if n.get("type") == "SYMBOL" else 0) \
            + (2 if has_img else 0) + min(2.0, math.log10(max(10.0, w * h)) - 2)
        cand.append((sc, name, n))
    cand.sort(key=lambda x: -x[0])
    seen, out = set(), []
    for sc, name, n in cand:
        key = re.sub(r"\s*\d+$", "", name.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
        if len(out) >= 3:
            break
    return out


def brand_from_fig(data: bytes, name: str, out_dir: Path) -> BrandKit:
    doc = load(data, name)
    out_dir.mkdir(parents=True, exist_ok=True)
    kit = BrandKit(name=doc.name or name, sources=[f"Figma: {name}"])
    colors: list[BrandColor] = []
    fonts: list[BrandFont] = []
    n_styles = 0
    for n in doc.nodes:
        st = n.get("styleType")
        if st == "FILL" and n.get("fillPaints"):
            p = n["fillPaints"][0]
            if p.get("type") == "SOLID" and p.get("color"):
                colors.append(BrandColor(hex=_hex(p["color"]), name=n.get("name", ""), weight=20, source="style"))
                n_styles += 1
        elif st == "TEXT" and n.get("fontName"):
            fonts.append(BrandFont(family=n["fontName"].get("family", ""), style=n["fontName"].get("style", ""),
                                   size=n.get("fontSize"), name=n.get("name", ""), weight=5))
            n_styles += 1
    colors += _variables(doc)
    internal = re.compile(r"(internal only|metadata)", re.I)
    for n in doc.nodes:
        if internal.search(doc.page_of.get(_gid(n.get("guid")), "")) or not n.get("visible", True):
            continue
        t = n.get("type")
        if t == "TEXT":
            ch = len((n.get("textData") or {}).get("characters", ""))
            fn = n.get("fontName") or {}
            if fn.get("family") and ch:
                fonts.append(BrandFont(family=fn["family"], style=fn.get("style", ""), size=n.get("fontSize"),
                                       weight=ch / 50))
            for p in n.get("fillPaints") or []:
                if p.get("type") == "SOLID" and p.get("visible", True) and p.get("color"):
                    colors.append(BrandColor(hex=_hex(p["color"]), weight=ch / 20, source="fill"))
            continue
        if t in ("CANVAS", "DOCUMENT"):
            continue
        for p in n.get("fillPaints") or []:
            if p.get("type") == "SOLID" and p.get("visible", True) and p.get("color") and float(p.get("opacity", 1)) > 0.4:
                colors.append(BrandColor(hex=_hex(p["color"]), weight=math.sqrt(_area(n)) / 10, source="fill"))
    # примеры слайдов: фреймы 16:9 верхнего уровня
    slides, slide_bgs = [], []
    for n in doc.nodes:
        if n.get("type") != "FRAME" or not n.get("visible", True):
            continue
        par = doc.by_id.get(_gid((n.get("parentIndex") or {}).get("guid")))
        if not par or par.get("type") != "CANVAS" or internal.search(par.get("name", "")):
            continue
        s = n.get("size") or {}
        w, h = float(s.get("x", 0)), float(s.get("y", 0))
        if w >= 900 and h and abs(w / h - 16 / 9) < 0.03:
            bg = next((_hex(p["color"]) for p in n.get("fillPaints") or [] if p.get("type") == "SOLID" and p.get("color")
                       and p.get("visible", True)), "")
            slides.append({"name": n.get("name", ""), "page": par.get("name", ""), "w": w, "h": h, "bg": bg})
            if bg:
                slide_bgs.append(bg)
    # фоны слайдов «Presentation»-страниц — главный сигнал фона бренда
    pres = [s["bg"] for s in slides if s["bg"] and re.search(r"(present|slide|deck|презент|слайд)", s["page"], re.I)]
    kit.slides = slides[:30]
    kit.colors = [c for c in sorted(_merge_for_view(colors), key=lambda c: -c.weight)][:24]
    kit.palette, kit.accents = assign_roles(colors, pres or slide_bgs)
    kit.font_styles = [f for f in fonts if f.name][:40]
    kit.fonts = pick_fonts(fonts)
    # логотипы
    sb = SvgBuilder(doc)
    for k, n in enumerate(_logos(doc), 1):
        try:
            svg, w, h = sb.render(n)
        except Exception as e:
            log.warning("logo %s render failed: %s", n.get("name"), e)
            continue
        if "<path" not in svg and "<image" not in svg:
            continue
        stem = f"logo{k}"
        (out_dir / f"{stem}.svg").write_text(svg, encoding="utf-8")
        png = out_dir / f"{stem}.png"
        if svg_to_png(svg, png, width=min(1200, max(300, int(w * 4)))):
            dark = _is_light_mark(png)
            kit.logos.append(BrandLogo(name=n.get("name", ""), png=str(png), svg=str(out_dir / f"{stem}.svg"),
                                       w=w, h=h, dark_bg=dark))
    if doc.thumbnail:
        (out_dir / "thumbnail.png").write_bytes(doc.thumbnail)
    if not n_styles:
        kit.warnings.append("в файле нет опубликованных стилей — цвета и шрифты взяты из самих макетов")
    if not kit.logos:
        kit.warnings.append("логотип не найден: назовите слой «Logo» или приложите логотип файлом")
    kit.id = hashlib.sha256(data[:1 << 20]).hexdigest()[:12]
    return kit


def _merge_for_view(colors: list[BrandColor]) -> list[BrandColor]:
    from .model import merge
    return merge(colors)


def _is_light_mark(png: Path) -> bool:
    """Светлый знак (белый логотип) — для тёмного фона."""
    try:
        import numpy as np
        from PIL import Image
        a = np.asarray(Image.open(png).convert("RGBA")).astype(float)
        m = a[..., 3] > 128
        if not m.any():
            return False
        lum = (0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2])[m]
        sat = (a[..., :3].max(axis=-1) - a[..., :3].min(axis=-1))[m]
        white = ((lum > 215) & (sat < 30)).mean()
        dark = ((lum < 90) & (sat < 40)).mean()
        return bool(white > 0.25 and white > dark) or float(lum.mean()) > 200
    except Exception:
        return False


def as_dict(kit: BrandKit) -> dict[str, Any]:
    return kit.model_dump()

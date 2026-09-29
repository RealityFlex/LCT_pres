"""Шрифты: извлечение встроенных шрифтов (EOT .fntdata), поиск файлов, измерение текста.

Измерение текста нужно для детерминированной подгонки кегля и для аудита
«текст не поместился в рамку». Если нужного шрифта нет, подбирается метрически
близкий запасной и ширина корректируется коэффициентом.
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
import logging
import threading
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import ImageFont

from ..config import BACKEND, get_settings

_lock = threading.Lock()
log = logging.getLogger("fonts")


def extracted_fonts_dir() -> Path:
    d = get_settings().data_dir / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def font_dirs_for_render() -> list[Path]:
    return [p for p in (BACKEND / "assets" / "fonts", extracted_fonts_dir()) if p.exists()]


# ------------------------------------------------------------------ EOT

def eot_to_ttf(data: bytes) -> Optional[bytes]:
    """Достаёт TTF из Embedded OpenType. MTX-сжатые шрифты не поддерживаются."""
    if len(data) < 16:
        return None
    if data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return data  # уже sfnt
    eot_size, font_size, version, flags = struct.unpack("<IIII", data[:16])
    if eot_size != len(data) or font_size > eot_size:
        return None
    if flags & 0x4:  # TTEMBED_TTCOMPRESSED
        return None
    font = bytearray(data[eot_size - font_size: eot_size])
    if flags & 0x10000000:  # XOR-обфускация
        font = bytearray(b ^ 0x50 for b in font)
    if bytes(font[:4]) not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return None
    return bytes(font)


def extract_embedded_fonts(pptx_path: Path) -> list[dict]:
    """Сохраняет встроенные шрифты шаблона в data/fonts. Возвращает список {family, file}."""
    res = []
    out = extracted_fonts_dir()
    with zipfile.ZipFile(pptx_path) as z:
        for n in z.namelist():
            if not n.lower().endswith((".fntdata", ".odttf", ".ttf", ".otf")):
                continue
            ttf = eot_to_ttf(z.read(n))
            if not ttf:
                continue
            fam, sub = _names_from_bytes(ttf)
            if not fam:
                continue
            fname = re.sub(r"[^\w\-]+", "_", f"{fam}-{sub or 'Regular'}") + ".ttf"
            p = out / fname
            if not p.exists():
                p.write_bytes(ttf)
            res.append({"family": fam, "style": sub, "file": str(p)})
    if res:
        _index.cache_clear()
    return res


def _names_from_bytes(ttf: bytes) -> tuple[Optional[str], Optional[str]]:
    import io
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(io.BytesIO(ttf), lazy=True, fontNumber=0)
        return _names(f)
    except Exception:
        return None, None


def _names(f) -> tuple[Optional[str], Optional[str]]:
    name = f["name"]
    fam = name.getDebugName(16) or name.getDebugName(1)
    sub = name.getDebugName(17) or name.getDebugName(2)
    return fam, sub


# ------------------------------------------------------------------ index

def _system_font_dirs() -> list[Path]:
    dirs = [BACKEND / "assets" / "fonts", extracted_fonts_dir()]
    if sys.platform.startswith("win"):
        dirs += [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    elif sys.platform == "darwin":
        dirs += [Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path.home() / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
                 Path.home() / ".local/share/fonts"]
    return [d for d in dirs if d.exists()]


@lru_cache(maxsize=1)
def _index() -> dict[str, dict[str, str]]:
    """family(lower) -> {style(lower): path}"""
    cache = get_settings().cache_dir / "font_index.json"
    files = []
    for d in _system_font_dirs():
        for ext in ("*.ttf", "*.otf", "*.TTF", "*.OTF"):
            files += list(d.rglob(ext))
    sig = f"{len(files)}:{sum(int(f.stat().st_mtime) for f in files[:4000]) % 10**9}"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("sig") == sig:
                return data["index"]
        except Exception:
            pass
    from fontTools.ttLib import TTFont
    idx: dict[str, dict[str, str]] = {}
    for f in files:
        try:
            t = TTFont(str(f), lazy=True, fontNumber=0)
            fam, sub = _names(t)
            t.close()
        except Exception:
            continue
        if not fam:
            continue
        idx.setdefault(fam.lower(), {})[(sub or "regular").lower()] = str(f)
        # «Montserrat Medium» → семейство Montserrat, стиль medium (для legacy-имён)
    cache.write_text(json.dumps({"sig": sig, "index": idx}, ensure_ascii=False), encoding="utf-8")
    return idx


def find_font_file(family: str, bold: bool = False, italic: bool = False) -> Optional[str]:
    if not family:
        return None
    idx = _index()
    fam = family.lower().strip()
    styles = idx.get(fam)
    if styles is None:
        # «Montserrat Medium» / «Lato Light» → базовое семейство
        parts = fam.split()
        while len(parts) > 1 and styles is None:
            parts = parts[:-1]
            styles = idx.get(" ".join(parts))
        if styles is None:
            return None
    want = []
    if bold and italic:
        want = ["bold italic", "bolditalic"]
    elif bold:
        want = ["bold", "semibold", "medium"]
    elif italic:
        want = ["italic"]
    want += ["regular", "normal", "book", "roman", "medium"]
    for w in want:
        if w in styles:
            return styles[w]
    return next(iter(styles.values()))


def font_available(family: str) -> bool:
    p = find_font_file(family)
    return p is not None and has_cyrillic(p)


FALLBACKS = ["Arial", "Liberation Sans", "DejaVu Sans", "Helvetica", "Segoe UI"]
# чем рендерер (LibreOffice) подменяет глифы, которых нет в шрифте: мерим тем же, чем рисуется
RENDER_FALLBACK = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"


@lru_cache(maxsize=256)
def _pil_font(path: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, 1000)


@lru_cache(maxsize=256)
def has_cyrillic(path: str) -> bool:
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(path, lazy=True, fontNumber=0)
        cmap = f.getBestCmap() or {}
        f.close()
        return all(ord(ch) in cmap for ch in "АБВжщЯ")
    except Exception:
        return True


@lru_cache(maxsize=128)
def _resolve(family: str, bold: bool) -> tuple[Optional[str], float]:
    p = find_font_file(family, bold)
    if p and has_cyrillic(p):
        # жирного файла нет — рендерер утолщает обычный начертание, строка выходит шире
        synthetic = bold and not re.search(r"(bold|black|heavy|semibold|demi|extrab)", Path(p).stem, re.I)
        return p, 1.07 if synthetic else 1.0
    if p:
        # шрифт есть, но без кириллицы — русские буквы рисуются запасным шрифтом рендерера
        q = find_font_file(RENDER_FALLBACK, bold)
        if q:
            return q, 1.02
    for fb in FALLBACKS:
        p = find_font_file(fb, bold)
        if p:
            # незнакомые шрифты в среднем чуть шире Arial — берём запас 6%
            return p, 1.06
    return None, 1.1


def text_width_pt(text: str, family: str, size_pt: float, bold: bool = False,
                  spacing_pt: float = 0.0) -> float:
    path, k = _resolve(family or "Arial", bold)
    if not text:
        return 0.0
    if path is None:
        return len(text) * size_pt * 0.55 * k
    f = _pil_font(path)
    w = f.getlength(text) / 1000 * size_pt * k
    return w + spacing_pt * max(0, len(text) - 1)


def line_height_factor(family: str) -> float:
    """Высота строки в долях кегля (single spacing ≈ ascent+descent)."""
    # высоту строки задаёт шрифт абзаца, даже если отдельные глифы рисуются запасным
    path = find_font_file(family or "Arial", False) or _resolve(family or "Arial", False)[0]
    if path is None:
        return 1.2
    try:
        f = _pil_font(path)
        asc, desc = f.getmetrics()
        return max(1.1, min(1.45, (asc + desc) / 1000))
    except Exception:
        return 1.2


def wrap_lines(text: str, width_pt: float, family: str, size_pt: float, bold: bool = False,
               spacing_pt: float = 0.0) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            cand = (cur + " " + w).strip() if cur else w
            if text_width_pt(cand, family, size_pt, bold, spacing_pt) <= width_pt or not cur:
                cur = cand
                # слово длиннее строки — переносим посимвольно
                while text_width_pt(cur, family, size_pt, bold, spacing_pt) > width_pt and len(cur) > 1:
                    cut = len(cur)
                    while cut > 1 and text_width_pt(cur[:cut], family, size_pt, bold, spacing_pt) > width_pt:
                        cut -= 1
                    lines.append(cur[:cut])
                    cur = cur[cut:]
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def text_height_pt(text: str, width_pt: float, family: str, size_pt: float, bold: bool = False,
                   line_spacing: float = 1.0, para_space_pt: float = 0.0, spacing_pt: float = 0.0) -> float:
    lines = wrap_lines(text, width_pt, family, size_pt, bold, spacing_pt)
    n_paras = text.count("\n") + 1
    return len(lines) * size_pt * line_height_factor(family) * line_spacing + para_space_pt * (n_paras - 1)


# ------------------------------------------------------------------ Google Fonts (OFL)

def try_fetch_google_font(family: str) -> bool:
    """Скачивает регулярное и жирное начертание из Google Fonts (для измерения и рендера)."""
    if font_available(family) or not get_settings().render.get("fetch_google_fonts", True):
        return font_available(family)
    import httpx
    slug = re.sub(r"[^a-z0-9]", "", family.lower())
    with _lock:
        out = extracted_fonts_dir()
        got = False
        for lic in ("ofl", "apache", "ufl"):
            try:
                r = httpx.get(f"https://api.github.com/repos/google/fonts/contents/{lic}/{slug}", timeout=15,
                              headers={"Accept": "application/vnd.github+json"})
                if r.status_code != 200:
                    continue
                files = [f for f in r.json() if f["name"].lower().endswith(".ttf") and "italic" not in f["name"].lower()]
                # статические Regular/Medium/Bold либо одна вариативная
                pick = [f for f in files if re.search(r"-(Regular|Medium|SemiBold|Bold)\.ttf$", f["name"])] or files[:1]
                for f in pick[:4]:
                    data = httpx.get(f["download_url"], timeout=60, follow_redirects=True).content
                    (out / f["name"].replace("[", "_").replace("]", "_").replace(",", "_")).write_bytes(data)
                    got = True
                if got:
                    break
            except Exception:
                continue
        if got:
            for f in list(out.glob("*.ttf")):
                make_static_instances(f)
            _index.cache_clear()
            _resolve.cache_clear()
        return got


def make_static_instances(path: Path) -> list[Path]:
    """Вариативный шрифт → статические Regular/Bold (LibreOffice плохо работает с вариативными)."""
    from fontTools.ttLib import TTFont
    try:
        f = TTFont(str(path))
    except Exception:
        return []
    if "fvar" not in f:
        return []
    from fontTools.varLib.instancer import instantiateVariableFont
    fam, _ = _names(f)
    axes = {a.axisTag: a for a in f["fvar"].axes}
    res = []
    for style, wght in (("Regular", 400), ("Bold", 700)):
        target = path.parent / f"{(fam or path.stem).replace(' ', '_')}-{style}.ttf"
        if target.exists():
            res.append(target)
            continue
        loc = {}
        for tag, a in axes.items():
            if tag == "wght":
                loc[tag] = max(a.minValue, min(a.maxValue, wght))
            else:
                loc[tag] = a.defaultValue
        try:
            inst = instantiateVariableFont(TTFont(str(path)), loc)
            name = inst["name"]
            for rec in list(name.names):
                if rec.nameID in (1, 2, 4, 6, 16, 17):
                    name.removeNames(nameID=rec.nameID)
            name.setName(fam, 1, 3, 1, 0x409)
            name.setName(style, 2, 3, 1, 0x409)
            name.setName(f"{fam} {style}", 4, 3, 1, 0x409)
            name.setName(f"{fam.replace(' ', '')}-{style}", 6, 3, 1, 0x409)
            if "OS/2" in inst:
                inst["OS/2"].usWeightClass = wght
                inst["OS/2"].fsSelection = (inst["OS/2"].fsSelection & ~0b1100001) | (0b100000 if wght >= 700 else 0b1000000)
            if "head" in inst:
                inst["head"].macStyle = 1 if wght >= 700 else 0
            inst.save(str(target))
            res.append(target)
        except Exception:
            continue
    if res:
        try:
            path.rename(path.with_suffix(".var"))  # убираем вариативный файл из индекса
        except OSError:
            pass
    return res


RIBBI = {"regular", "bold", "italic", "bold italic"}


def normalize_for_renderer(path: Path) -> Optional[Path]:
    """Копия шрифта со стандартным начертанием (Regular/Bold/Italic/Bold Italic) для рендера.

    Windows GDI (через него LibreOffice видит шрифты) не собирает семейство, если начертание названо
    нестандартно — «Normal», «Book», «Medium»: тогда «MiSans» у рендера не существует, обычный текст
    уходит в Liberation Sans, а жирный — в Arial Black, и вся подгонка текста, сделанная по метрикам
    настоящего шрифта, разъезжается. Возвращает путь копии или None, если нормализация не нужна."""
    from fontTools.ttLib import TTFont
    try:
        t = TTFont(str(path))
    except Exception:
        return None
    name = t["name"]
    fam = name.getDebugName(16) or name.getDebugName(1)
    sub = (name.getDebugName(2) or "").strip()
    if not fam or sub.lower() in RIBBI:
        t.close()
        return None
    bold = "bold" in sub.lower() or t["OS/2"].usWeightClass >= 600
    italic = "italic" in sub.lower() or "oblique" in sub.lower()
    style = ("Bold " if bold else "") + ("Italic" if italic else "") or "Regular"
    style = style.strip() or "Regular"
    for rec in list(name.names):
        if rec.nameID in (1, 2, 4, 6, 16, 17):
            name.removeNames(nameID=rec.nameID)
    ps = (fam + "-" + style).replace(" ", "")
    for nid, val in ((1, fam), (2, style), (4, f"{fam} {style}" if style != "Regular" else fam), (6, ps)):
        name.setName(val, nid, 3, 1, 0x409)
        name.setName(val, nid, 1, 0, 0)
    os2 = t["OS/2"]
    os2.fsSelection = (os2.fsSelection & ~0b1100001) | (0b100000 if bold else 0) | (0b1 if italic else 0) | (0 if (bold or italic) else 0b1000000)
    out = extracted_fonts_dir() / f"{ps}-render.ttf"
    try:
        if not out.exists():        # уже зарегистрированный шрифт Windows держит открытым — не перезаписываем
            t.save(str(out))
    except OSError as e:
        log.warning("font normalize %s: %s", path.name, e)
        return out if out.exists() else None
    finally:
        t.close()
    return out


def stage_fonts_for_render(families: list[str]) -> None:
    """Копирует файлы шрифтов шаблона в data/fonts, чтобы их видел LibreOffice (в т.ч. пользовательские)."""
    import shutil
    out = extracted_fonts_dir()
    win_fonts = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts").lower()
    idx = _index()
    for fam in families:
        styles = idx.get(fam.lower())
        if not styles:
            base = fam.lower().split()
            while len(base) > 1 and not styles:
                base = base[:-1]
                styles = idx.get(" ".join(base))
        for p in (styles or {}).values():
            if not p.lower().startswith(win_fonts) and Path(p).parent != out:
                try:
                    shutil.copy2(p, out / Path(p).name)
                except OSError:
                    pass
            if not Path(p).stem.endswith("-render"):
                try:
                    normalize_for_renderer(Path(p))
                except Exception as e:      # шрифт без копии хуже, чем упавший разбор шаблона
                    log.warning("font normalize %s: %s", p, e)

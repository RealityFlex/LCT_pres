"""Брендбук из картинок: логотипы (PNG/SVG, «logo» в имени или PNG с прозрачностью) и примеры слайдов;
палитра — по площади цветов на картинках. Принимает отдельные файлы или ZIP-архив."""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from .model import BrandColor, BrandKit, BrandLogo, assign_roles, chroma
from .pdf import palette_by_area

IMG = re.compile(r"\.(png|jpe?g|webp|svg)$", re.I)
LOGO = re.compile(r"(logo|лого|mark|знак)", re.I)


def unpack(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    out = []
    for name, data in files:
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist()[:200]:
                    if IMG.search(n) and not n.startswith("__MACOSX"):
                        out.append((n.split("/")[-1], z.read(n)))
        else:
            out.append((name, data))
    return out


def brand_from_images(files: list[tuple[str, bytes]], out_dir: Path) -> BrandKit:
    from PIL import Image
    from .fig import svg_to_png
    out_dir.mkdir(parents=True, exist_ok=True)
    kit = BrandKit(name="", sources=["картинки: " + ", ".join(n for n, _ in files[:5])])
    pics = []
    for k, (name, data) in enumerate(unpack(files)):
        if not IMG.search(name):
            continue
        safe = f"img{k}" + Path(name).suffix.lower()
        p = out_dir / safe
        p.write_bytes(data)
        if name.lower().endswith(".svg"):
            png = p.with_suffix(".png")
            if not svg_to_png(data.decode("utf-8", "replace"), png):
                continue
            p = png
        try:
            im = Image.open(p)
            im.load()
        except Exception:
            continue
        alpha = im.mode in ("RGBA", "LA") and im.getextrema()[-1][0] < 250
        is_logo = bool(LOGO.search(name)) or (alpha and max(im.size) <= 2400)
        if is_logo and len(kit.logos) < 3:
            from .fig import _is_light_mark
            kit.logos.append(BrandLogo(name=name, png=str(p), svg=str(out_dir / safe) if safe.endswith(".svg") else "",
                                       w=im.width, h=im.height,
                                       dark_bg=bool(re.search(r"(white|light|inverse|negative|бел|светл)", name, re.I)) or _is_light_mark(p)))
        pics.append(im)
    colors = []
    for hexv, share in palette_by_area(pics):
        colors.append(BrandColor(hex=hexv, weight=share * 40 * (2 if chroma(hexv) >= 0.25 else 0.5), source="image"))
    kit.colors = colors
    kit.palette, kit.accents = assign_roles(colors)
    if not kit.logos:
        kit.warnings.append("среди картинок нет логотипа: назовите файл logo.png или приложите PNG с прозрачностью")
    return kit

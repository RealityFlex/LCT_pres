"""Приём брендбука: файлы любых поддержанных видов → один BrandKit, сохранённый в data/brands/<id>/.

Несколько файлов дополняют друг друга: цвета и шрифты — из самого точного источника
(.fig и токены точнее PDF, PDF точнее картинок), логотипы — откуда нашлись, правила — из PDF."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Optional

from ..config import get_settings
from .model import BrandKit

log = logging.getLogger("brand")
RANK = {"fig": 0, "tokens": 1, "pdf": 2, "images": 3}
# меняется при правках разбора — иначе ранее загруженный брендбук вернётся из кэша со старыми ролями
PARSER_VERSION = 6


def brands_dir() -> Path:
    d = get_settings().data_dir / "brands"
    d.mkdir(parents=True, exist_ok=True)
    return d


def kind_of(name: str) -> Optional[str]:
    n = name.lower()
    if n.endswith(".fig"):
        return "fig"
    if n.endswith(".json"):
        return "tokens"
    if n.endswith(".pdf"):
        return "pdf"
    if re.search(r"\.(png|jpe?g|webp|svg|zip)$", n):
        return "images"
    return None


def build(files: list[tuple[str, bytes]]) -> BrandKit:
    """Файлы брендбука → BrandKit (сохраняется на диск)."""
    if not files:
        raise ValueError("не приложено ни одного файла брендбука")
    h = hashlib.sha256(f"v{PARSER_VERSION}".encode())
    for n, d in sorted(files):
        h.update(n.encode()); h.update(hashlib.sha256(d).digest())
    bid = "b" + h.hexdigest()[:12]
    out = brands_dir() / bid
    if (out / "brand.json").exists():
        return load(bid)
    out.mkdir(parents=True, exist_ok=True)
    kits: list[tuple[int, BrandKit]] = []
    errors = []
    images = []
    for name, data in files:
        k = kind_of(name)
        try:
            if k == "fig":
                from .fig import brand_from_fig
                kits.append((RANK[k], brand_from_fig(data, name, out / f"fig{len(kits)}")))
            elif k == "tokens":
                from .tokens import brand_from_tokens
                kits.append((RANK[k], brand_from_tokens(data, name)))
            elif k == "pdf":
                from .pdf import brand_from_pdf
                kits.append((RANK[k], brand_from_pdf(data, name, out / f"pdf{len(kits)}")))
            elif k == "images":
                images.append((name, data))
            else:
                errors.append(f"«{name}»: формат не поддерживается (нужны .fig, .json, .pdf, .png/.svg или .zip)")
        except Exception as e:
            log.warning("brand %s failed: %s", name, e)
            errors.append(f"«{name}»: {e}")
    if images:
        from .images import brand_from_images
        try:
            kits.append((RANK["images"], brand_from_images(images, out / "img")))
        except Exception as e:
            errors.append(f"картинки: {e}")
    if not kits:
        raise ValueError("; ".join(errors) or "брендбук не распознан")
    kits.sort(key=lambda x: x[0])
    main = kits[0][1].model_copy(deep=True)
    for _, k in kits[1:]:
        main.sources += k.sources
        for role, v in k.palette.items():
            main.palette.setdefault(role, v)
        if not main.accents:
            main.accents = k.accents
        for role, v in k.fonts.items():
            main.fonts.setdefault(role, v)
        main.logos += [lg for lg in k.logos if len(main.logos) < 4]
        main.rules += [r for r in k.rules if r not in main.rules]
        for key, v in k.spacing.items():
            main.spacing.setdefault(key, v)
        main.logo_min_h = main.logo_min_h if main.logo_min_h is not None else k.logo_min_h
        main.logo_clear = main.logo_clear if main.logo_clear is not None else k.logo_clear
        main.slides += k.slides
        main.colors += k.colors
    # логотипы из отдельных файлов — первыми: их приложили нарочно
    main.logos.sort(key=lambda lg: 0 if "/img/" in lg.png.replace("\\", "/") else 1)
    main.warnings = [w for _, k in kits for w in k.warnings if not (main.logos and "логотип" in w)] + errors
    main.id = bid
    main.name = main.name or files[0][0]
    (out / "brand.json").write_text(main.model_dump_json(indent=1), encoding="utf-8")
    return main


def load(bid: str) -> BrandKit:
    if not re.fullmatch(r"b[0-9a-f]{12}", bid or ""):
        raise KeyError(bid)
    p = brands_dir() / bid / "brand.json"
    if not p.exists():
        raise KeyError(bid)
    return BrandKit.model_validate_json(p.read_text(encoding="utf-8"))


def public(kit: BrandKit) -> dict:
    """Для API: без путей на диске — логотипы отдаются по ссылке."""
    d = json.loads(kit.model_dump_json())
    for i, lg in enumerate(d.get("logos", [])):
        lg["url"] = f"/api/brand/{kit.id}/logo/{i}.png"
        lg.pop("png", None)
        lg.pop("svg", None)
    d["colors"] = d.get("colors", [])[:16]
    d["summary"] = kit.summary()
    return d

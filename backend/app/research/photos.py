"""Фото к слайдам-иллюстрациям из Wikimedia Commons (свободные лицензии, автор указывается).

Кандидаты: поиск Commons по короткому английскому запросу иллюстратора + главные картинки прочитанных
статей Википедии. Код отсеивает мелкие, вертикальные и нефото-форматы, Qwen-vision по контактному листу
выбирает одно фото или отказывается — тогда слайд получает иллюстрацию генератора, как раньше.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from ..llm.skills import SkillRun
from ..planning.models import ContentSlide
from .wiki import wiki

log = logging.getLogger("photos")
FREE = ("cc0", "public domain", "no restrictions", "cc by", "cc-by", "pd", "attribution")


# рисунки из научных статей, схемы, карты, логотипы и сканы — не фото для слайда
NOT_PHOTO = re.compile(r"(\.g\d{3}|\bfig(ure)?\b|pone\.|journal|diagram|chart|graph|\bmap\b|karte|carte|logo|screenshot|"
                       r"scheme|schema|infographic|poster|plakat|flag|coat of arms|герб|флаг|схема|карта|скриншот|"
                       r"plan\b|drawing|illustration|page \d|scan|\.pdf)", re.I)


# политики и знаменитости на учебном или деловом слайде читаются как намёк или реклама — такие снимки
# не берём (на Commons их много: официальные фото пресс-служб в общественном достоянии)
PUBLIC_FIGURE = re.compile(r"(white house|kremlin|president|prime minister|minister|senator|governor|mayor|congress|"
                           r"parliament|official portrait|campaign|biden|obama|trump|putin|zelensk|"
                           r"президент|премьер|министр|губернатор|сенатор|депутат|кремл)", re.I)


def _ok_meta(c: dict) -> bool:
    lic = (c.get("license") or "").lower()
    meta = f"{c.get('title', '')} {c.get('description', '')} {c.get('artist', '')}"
    if NOT_PHOTO.search(meta) or PUBLIC_FIGURE.search(meta):
        return False
    return (c.get("mime") in ("image/jpeg", "image/webp") and c.get("width", 0) >= 1000
            and 1.15 <= c["width"] / max(1, c.get("height", 1)) <= 2.4 and any(f in lic for f in FREE)
            and "nc" not in lic.replace("-", " ").split() and "nd" not in lic.replace("-", " ").split())


def _sheet(ims: list[Image.Image]) -> bytes:
    """Контактный лист 3×2 с крупными номерами — одна картинка вместо шести для модели."""
    tw, th = 400, 260
    cols = 3
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 8, rows * th + (rows + 1) * 8), (235, 235, 235))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    for i, im in enumerate(ims):
        t = im.copy()
        t.thumbnail((tw, th))
        x, y = 8 + (i % cols) * (tw + 8), 8 + (i // cols) * (th + 8)
        sheet.paste(t, (x + (tw - t.width) // 2, y + (th - t.height) // 2))
        d.rectangle([x, y, x + 52, y + 46], fill=(220, 30, 30))
        d.text((x + 14, y + 4), str(i + 1), fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _credit(c: dict) -> str:
    who = (c.get("artist") or "").strip() or "автор не указан"
    if len(who) > 40:
        who = who[:38].rsplit(" ", 1)[0] + "…"
    return f"Фото: {who}, {c.get('license') or 'свободная лицензия'}"


async def _candidates(query: str, files: list[str]) -> list[dict]:
    w = wiki()
    tasks = [w.commons(query, 14)] if query else []
    if files:
        tasks.append(w.commons("", files=files))
    got = await asyncio.gather(*tasks, return_exceptions=True)
    out, seen = [], set()
    for g in got:
        if isinstance(g, BaseException):
            log.warning("commons failed: %s", g)
            continue
        for c in g:
            if c["url"] and c["url"] not in seen and _ok_meta(c):
                seen.add(c["url"])
                out.append(c)
    return out


async def _download(cands: list[dict], limit: int = 6) -> list[tuple[dict, Image.Image]]:
    w = wiki()

    async def one(c):
        try:
            data = await w.download(c["url"])
            im = Image.open(io.BytesIO(data))
            im.load()
            return c, im.convert("RGB")
        except Exception as e:
            log.info("photo download failed %s: %s", c["url"][:80], e)
            return None
    got = await asyncio.gather(*(one(c) for c in cands[:limit]))
    return [g for g in got if g is not None and g[1].width >= 900]


async def find_photo(s: ContentSlide, topic: str, run: SkillRun, out_dir: Path,
                     article_images: Optional[list[str]] = None,
                     exclude: Optional[set[str]] = None) -> Optional[tuple[Path, str, str]]:
    """Путь к фото, подпись автора/лицензии и адрес или None (нет подходящего — пусть рисует генератор)."""
    query = s.image_query or ""
    cands = [c for c in await _candidates(query, article_images or []) if not {c["url"], c.get("page")} & (exclude or set())]
    if not cands:
        return None
    pool = await _download(cands)
    if not pool:
        return None
    theses = "; ".join(f"{it.head} — {it.text}" if it.text else it.head for it in s.items[:4])
    try:
        raw = await run.call("photo_picker", images=[_sheet([im for _, im in pool])], topic=topic,
                             slide=f"{s.title}. {theses}"[:500], count=len(pool))
        pick = int((raw or {}).get("pick") or 0) if isinstance(raw, dict) else 0
    except Exception as e:
        log.warning("photo_picker failed: %s", e)
        return None
    if not 1 <= pick <= len(pool):
        return None
    c, im = pool[pick - 1]
    im.thumbnail((1800, 1800))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{s.id}_{hashlib.sha1(c['url'].encode()).hexdigest()[:8]}.jpg"
    im.save(path, "JPEG", quality=88)
    return path, _credit(c), c.get("page") or c["url"]


async def find_photos(slides: list[ContentSlide], topic: str, run: SkillRun, out_dir: Path, limit: int,
                      article_images: Optional[list[str]] = None) -> dict[str, tuple[Path, str, str]]:
    """{slide_id: (путь, подпись «Фото: автор, лицензия», страница файла на Commons)}"""
    out: dict[str, tuple[Path, str, str]] = {}
    used: set[str] = set()
    for s in slides[:limit]:        # по очереди: разные слайды не должны получить одно и то же фото
        try:
            got = await find_photo(s, topic, run, out_dir, article_images, used)
        except Exception as e:
            log.warning("photo for %s failed: %s", s.id, e)
            got = None
        if got:
            out[s.id] = got
            used.add(got[2])
    return out

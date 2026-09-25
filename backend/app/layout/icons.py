"""Пиктограммы: набор Lucide (ISC), поиск по имени/тегам, растеризация в цвет палитры."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pymupdf

from ..config import BACKEND

ICON_DIR = BACKEND / "assets" / "icons" / "lucide"

# русские подсказки → ключевые слова (планировщик обычно выдаёт английские, это запасной путь)
RU = {
    "безопасн": "shield-check", "рост": "trending-up", "деньг": "banknote", "бюджет": "wallet", "команд": "users",
    "клиент": "user-round", "время": "clock", "скорост": "gauge", "цель": "target", "идея": "lightbulb",
    "данн": "database", "облак": "cloud", "аналит": "chart-column", "отчёт": "file-text", "отчет": "file-text",
    "интеграц": "plug", "автомат": "bot", "поиск": "search", "качеств": "badge-check", "риск": "triangle-alert",
    "запуск": "rocket", "план": "calendar", "процесс": "workflow", "настрой": "settings", "код": "code",
    "тест": "flask-conical", "обучен": "graduation-cap", "мобил": "smartphone", "почт": "mail", "документ": "file-text",
    "сеть": "network", "сервер": "server", "экономи": "piggy-bank", "договор": "handshake", "rocket": "rocket",
}


@lru_cache(maxsize=1)
def _tags() -> dict[str, list[str]]:
    p = ICON_DIR / "tags.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def all_names() -> list[str]:
    return sorted(p.stem for p in ICON_DIR.glob("*.svg"))


@lru_cache(maxsize=2048)
def find_icon(query: Optional[str]) -> Optional[str]:
    if not query:
        return None
    names = set(all_names())
    q = query.strip().lower().replace("_", "-").replace(" ", "-")
    if q in names:
        return q
    for ru, name in RU.items():
        if ru in q and name in names:
            return name
    words = [w for w in re.split(r"[-\s,/]+", q) if len(w) > 2]
    tags = _tags()
    best, best_score = None, 0.0
    for name in names:
        score = 0.0
        parts = name.split("-")
        for w in words:
            if w in parts:
                score += 3
            elif any(p.startswith(w) or w.startswith(p) for p in parts if len(p) > 2):
                score += 1.5
            if w in tags.get(name, []):
                score += 2
        score -= 0.05 * len(parts)
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 1.5 else None


@lru_cache(maxsize=512)
def render_icon(name: str, color: str, px: int = 256, stroke: float = 2.0) -> bytes:
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        path = ICON_DIR / "circle.svg"
    svg = path.read_text(encoding="utf-8").replace("currentColor", f"#{color}")
    svg = re.sub(r'stroke-width="[\d.]+"', f'stroke-width="{stroke}"', svg)
    from ..core.mupdf_lock import LOCK
    with LOCK:
        doc = pymupdf.open(stream=svg.encode("utf-8"), filetype="svg")
        page = doc[0]
        zoom = px / max(page.rect.width, 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
        data = pix.tobytes("png")
        doc.close()
    return data


def icon_catalog_hint(limit: int = 140) -> str:
    """Короткий список имён для промпта планировщика."""
    preferred = ["rocket", "target", "users", "user-round", "shield-check", "lock", "trending-up", "chart-column",
                 "chart-pie", "database", "cloud", "server", "cpu", "bot", "brain", "sparkles", "lightbulb", "zap",
                 "gauge", "clock", "calendar", "timer", "wallet", "banknote", "piggy-bank", "coins", "handshake",
                 "briefcase", "building-2", "factory", "store", "shopping-cart", "truck", "package", "globe", "map-pin",
                 "network", "plug", "workflow", "git-branch", "code", "terminal", "bug", "flask-conical", "wrench",
                 "settings", "sliders-horizontal", "search", "eye", "file-text", "files", "clipboard-check", "list-checks",
                 "badge-check", "award", "trophy", "star", "heart", "smile", "message-circle", "mail", "phone",
                 "smartphone", "monitor", "layers", "layout-dashboard", "puzzle", "box", "boxes", "graduation-cap",
                 "book-open", "school", "leaf", "sun", "droplet", "flame", "recycle", "triangle-alert", "circle-alert",
                 "circle-check", "circle-x", "refresh-cw", "repeat", "arrow-right", "move-right", "scale", "landmark",
                 "stethoscope", "activity", "hospital", "car", "plane", "train-front", "house", "key", "fingerprint",
                 "scan-face", "camera", "image", "video", "music", "mic", "megaphone", "newspaper", "pen-tool",
                 "palette", "wand-sparkles", "user-check", "users-round", "user-plus", "hand-helping", "life-buoy",
                 "headphones", "shield", "server-cog", "hard-drive", "wifi", "radio", "satellite", "compass", "flag",
                 "milestone", "route", "signpost", "hourglass", "infinity", "percent", "calculator", "receipt"]
    names = set(all_names())
    return ", ".join([n for n in preferred if n in names][:limit])

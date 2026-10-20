"""Каталог встроенных стилей и превращение стиля в обычный template_id."""
from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import yaml

from ..config import get_settings
from ..parsing.profile import load_profile, parse_template
from .generator import build_pack
from ..parsing.model import Palette
from .model import StyleSpec, _mix

CATALOG = Path(__file__).parent / "catalog"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

CATEGORY_RU = {"work": "Работа", "finance": "Финансы", "promo": "Промо", "academic": "Учёба", "consulting": "Консалтинг"}


@lru_cache(maxsize=1)
def _load() -> dict[str, StyleSpec]:
    out: dict[str, StyleSpec] = {}
    for f in sorted(CATALOG.glob("*.yaml")):
        spec = StyleSpec.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
        out[spec.id] = spec
    return out


def list_styles() -> list[StyleSpec]:
    return list(_load().values())


def get_style(style_id: str) -> StyleSpec:
    try:
        return _load()[style_id]
    except KeyError:
        raise KeyError(f"нет стиля {style_id}") from None


# меняется при правках generator.py — иначе старые паки остаются в кэше с прежней вёрсткой
GENERATOR_VERSION = 5


def style_tid(spec: StyleSpec) -> str:
    import hashlib
    h = hashlib.sha256(f"{spec.digest()}|{GENERATOR_VERSION}".encode()).hexdigest()[:8]
    return f"style-{spec.id}-{h}"


def resolve(style_id: str, colors: Optional[dict[str, str]] = None, fonts: Optional[dict[str, str]] = None,
            progress: Optional[Callable[[str, float], None]] = None, logo: str = "", logo_dark: str = "",
            brand_name: str = "", grid: Optional[dict] = None) -> str:
    """Стиль (+ свои цвета/шрифты) → template_id готового профиля. Пак собирается один раз и кэшируется."""
    base = get_style(style_id)
    spec = base.with_overrides(colors, fonts, logo, logo_dark, grid)
    tid = style_tid(spec)
    if load_profile(tid) is not None:
        return tid
    with _locks_guard:
        lock = _locks.setdefault(tid, threading.Lock())
    with lock:
        if load_profile(tid) is not None:
            return tid
        pack = get_settings().cache_dir / "styles" / f"{tid}.pptx"
        build_pack(spec, pack)
        name = spec.name + (f" · {brand_name}" if brand_name else " · свои цвета" if colors else "")
        parse_template(pack, name=name, progress=progress, use_llm=False, tid=tid, extra={
            "source": "style", "style_id": spec.id, "mono_font": spec.fonts.mono,
            "style_summary": f"{spec.description} Настроение: {spec.mood}.".strip(),
            "palette": spec_palette(spec),
        })
    return tid


def spec_palette(spec: StyleSpec) -> Palette:
    """Палитра стиля известна точно — не угадываем её по площадям, как у загруженного шаблона."""
    p = spec.palette
    roles = [("bg", p.bg), ("surface", p.surface), ("primary", p.primary), ("secondary", p.secondary),
             ("accent", p.accent), ("text", p.text), ("muted", p.muted), ("rule", p.rule),
             ("dark_bg", p.dark_bg), ("dark_text", p.dark_text)]
    tints = [_mix(p.primary, p.bg, 0.45), _mix(p.accent, p.bg, 0.45), _mix(p.secondary, p.bg, 0.5)]
    return Palette(
        colors=[{"hex": h, "weight": 1.0, "role": r} for r, h in roles],
        bg_light=p.bg, bg_dark=p.dark_bg, text_dark=p.text, text_light=p.dark_text,
        muted_dark=p.muted, muted_light=_mix(p.dark_text, p.dark_bg, 0.35), primary=p.primary,
        accents=list(dict.fromkeys([p.accent, p.secondary])),
        chart=list(dict.fromkeys([p.primary, p.accent, p.secondary] + tints)), surface=p.surface)


# назначение брифа → категория стиля, если модель не ответила
PURPOSE_CATEGORY = {"обучение": "academic", "продукт": "promo", "фича": "promo", "проект": "work",
                    "инициатива": "consulting"}


def fallback_style(purpose: str = "") -> str:
    styles = list_styles()
    cat = PURPOSE_CATEGORY.get((purpose or "").strip().lower())
    for s in styles:
        if s.category == cat:
            return s.id
    return styles[0].id


async def pick_style(brief, run, recent: Optional[list[str]] = None) -> str:
    """«Авто — подберу по теме»: модель называет три подходящих стиля по теме/назначению/аудитории, берётся
    первый, которого не было в недавних колодах (иначе все занятия выходили бы в одном стиле); без ответа
    модели — стиль по назначению, тоже не из недавних, если есть замена той же категории."""
    styles = list_styles()
    ids = {s.id for s in styles}
    recent = [r for r in (recent or []) if r in ids]
    catalog = "\n".join(f"{s.id} — {s.name} — {CATEGORY_RU.get(s.category, s.category)} — {s.mood}" for s in styles)
    cands: list[str] = []
    try:
        raw = await run.call("style_picker", topic=brief.topic, purpose=brief.purpose or "", audience=brief.audience or "",
                             details=(brief.details or "")[:600], catalog=catalog)
        if isinstance(raw, dict):
            got = raw.get("style_ids") or ([raw["style_id"]] if raw.get("style_id") else [])
            cands = [str(x) for x in got if str(x) in ids]
    except Exception:
        pass
    if not cands:
        cat = PURPOSE_CATEGORY.get((brief.purpose or "").strip().lower())
        cands = [s.id for s in styles if s.category == cat] or [fallback_style(brief.purpose)]
    cands = list(dict.fromkeys(cands))
    # чем недавнее стиль, тем хуже: сначала не встречавшиеся, потом давно встречавшиеся
    age = {sid: i for i, sid in reversed(list(enumerate(recent)))}
    return min(cands, key=lambda c: (-(len(recent) + 1) if c not in age else -age[c], cands.index(c)))

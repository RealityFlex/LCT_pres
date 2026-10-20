"""Встроенные стили: каждый пак из каталога собирается, разбирается тем же парсером и даёт всё нужное
для генерации без корпоративного шаблона."""
from __future__ import annotations

import pytest

from app.styles.registry import fallback_style, get_style, list_styles, resolve, style_tid
from app.styles.model import StyleSpec

STYLES = [s.id for s in list_styles()]


def test_catalog_has_enough_styles():
    assert len(STYLES) >= 8
    assert len({get_style(s).category for s in STYLES}) == 5, "в каталоге представлены все пять категорий"


def test_tid_is_deterministic_and_depends_on_colors():
    spec = get_style(STYLES[0])
    assert style_tid(spec) == style_tid(get_style(STYLES[0]))
    custom = spec.with_overrides({"primary": "#123456"})
    assert style_tid(custom) != style_tid(spec)
    assert custom.palette.primary == "123456" and custom.palette.dark_bg


def test_custom_background_recomputes_text_colors():
    dark = get_style(STYLES[0]).with_overrides({"background": "101418"})
    assert dark.palette.bg == "101418" and dark.palette.text.upper() == "F2F2F2"


def test_numeric_hex_from_yaml_is_kept():
    spec = StyleSpec.model_validate({
        "id": "x", "name": "x", "category": "work",
        "palette": {"bg": 0, "surface": 111111, "primary": 233057, "secondary": "AABBCC", "accent": "#FF0000",
                    "text": "000000", "muted": "777777", "rule": "DDDDDD", "dark_bg": 233057, "dark_text": "FFFFFF"},
        "fonts": {"heading": "Inter", "body": "Inter"}})
    assert spec.palette.bg == "000000" and spec.palette.primary == "233057" and spec.palette.accent == "FF0000"


def test_fallback_by_purpose():
    assert get_style(fallback_style("обучение")).category == "academic"
    assert fallback_style("неизвестно") in STYLES


@pytest.mark.parametrize("sid", STYLES)
def test_pack_parses_into_usable_profile(sid):
    from app.parsing.profile import load_profile
    tid = resolve(sid)
    p = load_profile(tid)
    assert p is not None and p.source == "style" and p.style_id == sid
    kinds = {c.kind for c in p.canvases}
    assert {"title", "agenda", "section", "content", "closing"} <= kinds
    roles = {sl.role for c in p.canvases for sl in c.slots}
    assert {"title", "kicker", "pagenum", "footer"} <= roles
    closing = next(c for c in p.canvases if c.kind == "closing")
    assert any(sl.role == "body" for sl in closing.slots), "итоговый холст принимает список выводов"
    spec = get_style(sid)
    assert p.palette.primary == spec.palette.primary and spec.palette.accent in p.palette.accents
    assert all(p.fonts_found.values()), f"шрифты стиля не найдены: {p.fonts_found}"

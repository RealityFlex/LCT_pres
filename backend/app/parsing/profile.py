"""Оркестратор декомпозиции шаблона → TemplateProfile (с кэшем по sha256)."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from ..config import get_settings
from . import fonts
from .analyze import TemplateAnalyzer
from .canvases import draft_canvases, render_canvases
from .model import Narrative, SlideInfo, TemplateProfile
from .render import render_deck
from .tokens import build_card_styles, build_grid, build_palette, build_table_style, build_typography

Progress = Optional[Callable[[str, float], None]]


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def template_dir(tid: str) -> Path:
    return get_settings().templates_dir / tid


def load_profile(tid: str) -> Optional[TemplateProfile]:
    p = template_dir(tid) / "profile.json"
    if p.exists():
        return TemplateProfile.model_validate_json(p.read_text(encoding="utf-8"))
    return None


def save_profile(profile: TemplateProfile) -> None:
    d = template_dir(profile.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.json").write_text(profile.model_dump_json(indent=1), encoding="utf-8")


def list_profiles() -> list[TemplateProfile]:
    res = []
    for d in sorted(get_settings().templates_dir.glob("*/profile.json")):
        try:
            res.append(TemplateProfile.model_validate_json(d.read_text(encoding="utf-8")))
        except Exception:
            continue
    return res


def parse_template(src: Path, name: Optional[str] = None, progress: Progress = None, use_llm: bool = True,
                   force: bool = False) -> TemplateProfile:
    t0 = time.time()
    say = progress or (lambda m, p: None)
    tid = file_hash(src)
    if not force:
        cached = load_profile(tid)
        if cached is not None:
            return cached
    d = template_dir(tid)
    d.mkdir(parents=True, exist_ok=True)
    tpl = d / "template.pptx"
    if Path(src).resolve() != tpl.resolve():
        shutil.copy2(src, tpl)

    say("Шрифты шаблона", 0.05)
    fonts.extract_embedded_fonts(tpl)

    say("Структура слайдов", 0.12)
    an = TemplateAnalyzer(tpl)
    slides = an.run()
    used_fonts = sorted({p.style.font for sa in slides for s in sa.shapes for p in s.paras if p.style.font})
    fonts_found = {}
    for f in used_fonts[:8]:
        ok = fonts.font_available(f) or fonts.try_fetch_google_font(f)
        fonts_found[f] = ok
    fonts.stage_fonts_for_render(list(fonts_found))

    say("Рендер шаблона", 0.2)
    prev_dir = d / "preview"
    _, pngs = render_deck(tpl, prev_dir, prefix="slide")

    say("Дизайн-токены", 0.5)
    usable = [s for s in slides if not s.service]
    grid, gap = build_grid(an, usable)
    canvases = draft_canvases(an, slides, grid, gap)

    say("Холсты", 0.6)
    render_canvases(tpl, canvases, d / "canvases", an.W, an.H, gap)
    bg_samples = [c.bg for c in canvases]
    palette = build_palette(an, usable, bg_samples)
    typo = build_typography(an, usable, palette)
    cards = build_card_styles(an, usable, palette)
    table = build_table_style(usable, palette, typo.body)

    infos = []
    for sa, png in zip(slides, pngs):
        infos.append(SlideInfo(
            index=sa.index, layout=sa.layout, kind=sa.kind, service=sa.service, service_reason=sa.service_reason or None,
            title=(sa.title.text if sa.title else "")[:120],
            text_excerpt=" | ".join(it.text.replace("\n", " ")[:60] for it in sa.items if it.has_text)[:400],
            n_shapes=len(sa.shapes), features=sa.features, groups=sa.groups, preview=str(png)))
    for c in canvases:
        for si in infos:
            if si.index == c.source_slide:
                si.dark, si.bg = c.dark, c.bg

    narrative = _narrative(slides, typo)
    profile = TemplateProfile(
        id=tid, name=name or Path(src).stem, file=str(tpl), slide_w=an.W, slide_h=an.H, n_slides=len(slides),
        fonts_found=fonts_found, palette=palette, typography=typo, margins=grid, gap=gap, card_styles=cards,
        table_style=table, canvases=canvases, slides=infos, narrative=narrative)

    if use_llm:
        say("Разметка слайдов моделью", 0.8)
        try:
            from .vlm_labels import enrich_profile
            enrich_profile(profile)
        except Exception as e:  # модель недоступна — профиль остаётся детерминированным
            profile.style_summary = profile.style_summary or f"(VLM недоступна: {e.__class__.__name__})"
    profile.parse_seconds = round(time.time() - t0, 1)
    save_profile(profile)
    say("Готово", 1.0)
    return profile


def _narrative(slides, typo) -> Narrative:
    usable = [s for s in slides if not s.service]
    kinds = [s.kind for s in usable]
    kick = [sl.text for s in usable for sl in s.slots if sl.role == "kicker" and sl.text.strip()]
    titles = [s.title.text for s in usable if s.title and s.title.text.strip() and s.kind == "content"]
    nums = sum(1 for s in usable if s.features.get("big_numbers"))
    closing = "none"
    for s in usable[::-1]:
        if s.kind == "closing":
            t = (s.title.text if s.title else "").lower()
            closing = "thanks" if ("спасибо" in t or "thank" in t) else "summary"
            break
    return Narrative(
        has_agenda="agenda" in kinds, has_sections=kinds.count("section") >= 1, closing=closing,
        title_caps=typo.title_caps, uses_kicker=len(kick) >= 2, kicker_example=kick[0] if kick else None,
        numbering=nums >= 2, avg_title_words=round(sum(len(t.split()) for t in titles) / len(titles), 1) if titles else 6,
        sequence=kinds[:30])


if __name__ == "__main__":  # pragma: no cover
    import sys
    p = parse_template(Path(sys.argv[1]), use_llm="--no-llm" not in sys.argv, force="--force" in sys.argv,
                       progress=lambda m, x: print(f"[{x:.0%}] {m}", flush=True))
    print(json.dumps({"id": p.id, "canvases": len(p.canvases), "sec": p.parse_seconds}, ensure_ascii=False))

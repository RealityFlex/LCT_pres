"""VLM-обогащение профиля шаблона (описание стиля, тон, стиль иллюстраций).

Детерминированный профиль остаётся первичным: модель только добавляет описания
и может пометить дополнительные служебные слайды.
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

from PIL import Image, ImageDraw

from .model import TemplateProfile


def contact_sheet(profile: TemplateProfile, max_slides: int = 24) -> bytes:
    ims = []
    for s in profile.slides[:max_slides]:
        if s.preview and Path(s.preview).exists():
            im = Image.open(s.preview).convert("RGB")
            im.thumbnail((320, 320))
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, 28, 18], fill=(220, 0, 0))
            d.text((4, 3), str(s.index), fill=(255, 255, 255))
            ims.append(im)
    if not ims:
        raise RuntimeError("нет превью")
    w, h = ims[0].size
    cols = 6
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), "white")
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    buf = io.BytesIO()
    sheet.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


async def _enrich(profile: TemplateProfile) -> None:
    from ..llm.client import reset_llm
    from ..llm.skills import SkillRun
    texts = "\n".join(f"{s.index}. [{s.kind}] {s.text_excerpt[:160]}" for s in profile.slides[:30])
    res = await SkillRun().call("template_analyst", images=[contact_sheet(profile)], texts=texts)
    reset_llm()
    if not isinstance(res, dict):
        return
    profile.style_summary = str(res.get("style_summary") or "")[:600]
    profile.image_style = str(res.get("image_style") or "")[:300]
    profile.narrative.tone = str(res.get("tone") or "")[:300]
    extra = {int(x) for x in res.get("service_slides") or [] if str(x).isdigit()}
    for s in profile.slides:
        if s.index in extra and not s.service and s.kind == "content":
            s.vlm = {"service": True}


def enrich_profile(profile: TemplateProfile) -> None:
    asyncio.run(_enrich(profile))

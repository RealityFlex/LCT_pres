"""CLI: python -m app.cli parse <template.pptx> | generate --template ... --brief brief.yaml

Воспроизводимый запуск: все параметры — в config.yaml и файле брифа.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import yaml

from .parsing.profile import load_profile, parse_template
from .planning.models import Brief, DeckContent


def _progress(msg: str, p: float) -> None:
    print(f"  [{p:4.0%}] {msg}", flush=True)


def cmd_parse(a) -> None:
    prof = parse_template(Path(a.template), use_llm=not a.no_llm, force=a.force, progress=_progress)
    print(json.dumps({"template_id": prof.id, "name": prof.name, "canvases": len(prof.canvases),
                      "palette": prof.palette.primary, "fonts": [prof.typography.heading_font, prof.typography.body_font],
                      "seconds": prof.parse_seconds}, ensure_ascii=False, indent=1))


async def _generate(a) -> None:
    from .pipeline import STORE, run_job
    tpl = Path(a.template)
    prof = parse_template(tpl, progress=_progress, use_llm=not a.no_llm) if tpl.exists() else load_profile(a.template)
    if prof is None:
        raise SystemExit("шаблон не найден")
    if a.brief:
        data = yaml.safe_load(Path(a.brief).read_text(encoding="utf-8"))
        brief = Brief(**data)
    else:
        brief = Brief(topic=a.topic, purpose=a.purpose, audience=a.audience or "", details=a.details or "",
                      slide_count=a.slides)
    content = DeckContent.model_validate_json(Path(a.content).read_text(encoding="utf-8")) if a.content else None
    job = STORE.create(prof.id, brief)
    t0 = time.time()
    orig_emit = STORE.emit

    def emit(job_, stage, message, progress=None, **kw):
        orig_emit(job_, stage, message, progress, **kw)
        print(f"  [{time.time() - t0:5.1f}s] {stage:8} {message}", flush=True)

    STORE.emit = emit  # type: ignore[assignment]
    job = await run_job(job, content)
    print(json.dumps({"job": job.id, "status": job.status, "error": job.error,
                      "variants": [{"id": v.id, "slides": v.n_slides, "audit": v.audit, "files": v.files} for v in job.variants],
                      "skills": job.skills, "llm": job.llm_stats, "seconds": round(time.time() - t0, 1)},
                     ensure_ascii=False, indent=1))


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse", help="декомпозиция шаблона")
    p.add_argument("template")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--force", action="store_true")
    g = sub.add_parser("generate", help="полный прогон: бриф → 3 варианта")
    g.add_argument("--template", required=True, help="путь к .pptx или id шаблона")
    g.add_argument("--brief", help="YAML с полями Brief")
    g.add_argument("--topic", default="")
    g.add_argument("--purpose", default="проект")
    g.add_argument("--audience", default="")
    g.add_argument("--details", default="")
    g.add_argument("--slides", type=int, default=None)
    g.add_argument("--content", help="готовая контент-модель (JSON) — пропустить планирование")
    g.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    if a.cmd == "parse":
        cmd_parse(a)
    else:
        asyncio.run(_generate(a))


if __name__ == "__main__":
    sys.exit(main())

"""HTTP API сервиса (FastAPI). Фронтенд (React + VKUI) собирается в frontend/dist и раздаётся отсюда же."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import ROOT, get_settings
from ..llm import skills as skills_mod
from ..parsing.profile import file_hash, list_profiles, load_profile, parse_template, template_dir
from ..pipeline import STORE, fix_variant, job_dir, load_variant, run_job
from ..planning.models import Brief

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="Цифровой дизайнер презентаций", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PARSE_STATUS: dict[str, dict[str, Any]] = {}
_tasks: set[asyncio.Task] = set()


# ------------------------------------------------------------------ helpers

def _tpl_summary(p) -> dict:
    content = [c for c in p.canvases if c.kind in ("content", "agenda") and c.clean]
    return {
        "id": p.id, "name": p.name, "n_slides": p.n_slides, "slide_w": p.slide_w, "slide_h": p.slide_h,
        "aspect": round(p.slide_w / p.slide_h, 3), "primary": p.palette.primary,
        "colors": [c["hex"] for c in p.palette.colors[:8]], "fonts": [p.typography.heading_font, p.typography.body_font],
        "canvases": len(p.canvases), "content_canvases": len(content), "parse_seconds": p.parse_seconds,
        "cover": f"/api/templates/{p.id}/slide/1.png",
    }


def _tpl_detail(p) -> dict:
    d = _tpl_summary(p)
    ty = p.typography
    d.update({
        "palette": p.palette.model_dump(),
        "typography": {r: getattr(ty, r).model_dump() if getattr(ty, r) else None
                       for r in ("title", "subtitle", "kicker", "heading", "body", "caption", "number")},
        "scale": ty.scale, "title_caps": ty.title_caps,
        "margins": p.margins.model_dump(), "gap": p.gap,
        "narrative": p.narrative.model_dump(),
        "style_summary": p.style_summary, "image_style": p.image_style,
        "fonts_found": p.fonts_found,
        "card_styles": [{"fill": c.fill, "line": c.line, "accent": c.accent, "geom": c.geom} for c in p.card_styles],
        "canvas_list": [{"id": c.id, "kind": c.kind, "dark": c.dark, "clean": c.clean, "score": round(c.score, 2),
                         "layout": c.layout, "slots": [s.role for s in c.slots], "dirty_reason": c.dirty_reason,
                         "content_box": c.content_box.model_dump(),
                         "preview": f"/api/templates/{p.id}/canvas/{c.id}.png"} for c in p.canvases],
        "slides": [{"index": s.index, "kind": s.kind, "service": s.service, "service_reason": s.service_reason,
                    "layout": s.layout, "title": s.title, "groups": [g.count for g in s.groups],
                    "preview": f"/api/templates/{p.id}/slide/{s.index}.png"} for s in p.slides],
    })
    return d


def _thumb(path: Path, w: Optional[int]) -> FileResponse:
    """Миниатюра (WebP) с кэшем рядом с исходником; пересоздаётся, если исходник новее."""
    if not path.exists():
        raise HTTPException(404)
    if not w:
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    w = max(64, min(int(w), 1600))
    t = path.with_name(f"{path.stem}.w{w}.webp")
    if not t.exists() or t.stat().st_mtime < path.stat().st_mtime:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            h = int(im.height * w / im.width)
            im.resize((w, h), Image.LANCZOS).save(t, "WEBP", quality=86, method=4)
    return FileResponse(t, media_type="image/webp", headers={"Cache-Control": "no-cache"})


def _job_card(j) -> dict:
    cover = None
    for v in j.variants:
        p = job_dir(j.id) / v.id / "slides" / "slide-001.png"
        if p.exists():
            cover = f"/api/jobs/{j.id}/variants/{v.id}/slide/1.png?w=640"
            break
    prof = load_profile(j.template_id)
    return {"id": j.id, "title": j.title or j.brief.topic, "topic": j.brief.topic, "purpose": j.brief.purpose,
            "status": j.status, "stage": j.stage, "progress": j.progress, "template_id": j.template_id,
            "template_name": prof.name if prof else "—", "created": j.created, "finished": j.finished,
            "seconds": round((j.finished or time.time()) - j.created, 1) if j.status == "done" else None,
            "variants": [{"id": v.id, "name": v.name, "n_slides": v.n_slides, "audit": v.audit} for v in j.variants],
            "cover": cover, "error": j.error}


def _spawn(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


# ------------------------------------------------------------------ health / skills

@app.get("/api/health")
def health():
    s = get_settings()
    try:
        soffice = s.soffice
    except Exception as e:
        soffice = f"not found: {e}"
    from ..layout.images import image_generator
    return {"ok": True, "llm": {"configured": bool(s.llm_api_key), "model": s.model("text"), "vision": s.model("vision")},
            "images": {"enabled": image_generator().enabled, "provider": s.images.get("provider")},
            "soffice": soffice, "variants": s.variants, "deadline_s": s.pipeline.get("deadline_s")}


@app.get("/api/skills")
def skills():
    active = get_settings().skills
    out = []
    for name, versions in skills_mod.available().items():
        v = active.get(name) or versions[-1]
        try:
            sk = skills_mod.load(name, v)
            desc = sk.description
        except Exception:
            desc = ""
        out.append({"name": name, "versions": versions, "active": v, "description": desc})
    return out


# ------------------------------------------------------------------ templates

@app.get("/api/templates")
def templates():
    return [_tpl_summary(p) for p in list_profiles()]


def _parse_worker(tmp: Path, name: str, tid: str, force: bool):
    def prog(msg, x):
        PARSE_STATUS[tid] = {"status": "parsing", "progress": x, "message": msg}
    try:
        parse_template(tmp, name=name, progress=prog, force=force)
        PARSE_STATUS[tid] = {"status": "ready", "progress": 1.0, "message": "Готово"}
    except Exception as e:
        logging.exception("parse failed")
        PARSE_STATUS[tid] = {"status": "error", "progress": 1.0, "message": f"{e.__class__.__name__}: {e}"}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


@app.post("/api/templates")
async def upload_template(file: UploadFile = File(...), force: bool = Form(False)):
    if not file.filename or not file.filename.lower().endswith((".pptx", ".potx")):
        raise HTTPException(400, "Нужен файл .pptx или .potx")
    s = get_settings()
    tmp = Path(tempfile.mkstemp(suffix=".pptx", dir=s.cache_dir)[1])
    with open(tmp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    tid = file_hash(tmp)
    name = Path(file.filename).stem
    if not force and load_profile(tid) is not None:
        tmp.unlink(missing_ok=True)
        return {"id": tid, "status": "ready"}
    PARSE_STATUS[tid] = {"status": "parsing", "progress": 0.01, "message": "Загружено"}
    threading.Thread(target=_parse_worker, args=(tmp, name, tid, force), daemon=True).start()
    return {"id": tid, "status": "parsing"}


@app.get("/api/templates/{tid}/status")
def template_status(tid: str):
    if tid in PARSE_STATUS:
        return PARSE_STATUS[tid]
    if load_profile(tid) is not None:
        return {"status": "ready", "progress": 1.0, "message": "Готово"}
    raise HTTPException(404, "нет такого шаблона")


@app.get("/api/templates/{tid}")
def template_detail(tid: str):
    p = load_profile(tid)
    if p is None:
        raise HTTPException(404, "нет такого шаблона")
    return _tpl_detail(p)


@app.delete("/api/templates/{tid}")
def template_delete(tid: str):
    d = template_dir(tid)
    if not d.exists():
        raise HTTPException(404)
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@app.get("/api/templates/{tid}/slide/{n}.png")
def template_slide(tid: str, n: int, w: Optional[int] = None):
    return _thumb(template_dir(tid) / "preview" / f"slide-{n:03d}.png", w)


@app.get("/api/templates/{tid}/canvas/{cid}.png")
def template_canvas(tid: str, cid: str, w: Optional[int] = None):
    prof = load_profile(tid)
    if prof is None:
        raise HTTPException(404)
    c = next((c for c in prof.canvases if c.id == cid), None)
    if c is None or not c.preview or not Path(c.preview).exists():
        raise HTTPException(404)
    return _thumb(Path(c.preview), w)


# ------------------------------------------------------------------ jobs

class Material(BaseModel):
    name: str
    text: str


class JobIn(BaseModel):
    template_id: str
    brief: Brief
    materials: list[Material] = []      # текст приложенных файлов (см. /api/materials)


@app.post("/api/jobs")
async def create_job(body: JobIn):
    if load_profile(body.template_id) is None:
        raise HTTPException(404, "шаблон не найден")
    if not body.brief.topic.strip():
        raise HTTPException(400, "Опишите тему презентации")
    if body.materials:
        from ..planning.materials import combine
        mats = combine([(m.name, m.text) for m in body.materials if m.text.strip()])
        body.brief.details = (body.brief.details.strip() + "\n\nПРИЛОЖЕННЫЕ МАТЕРИАЛЫ\n" + mats).strip()
    job = STORE.create(body.template_id, body.brief)
    _spawn(run_job(job))
    return {"id": job.id}


@app.post("/api/materials")
async def materials(files: list[UploadFile] = File(...)):
    """Текст из приложенных к брифу файлов (README, документация, отчёты, старые презентации)."""
    from ..planning.materials import MAX_TOTAL_CHARS, extract
    out = []
    for f in files[:10]:
        data = await f.read()
        name = f.filename or "файл"
        try:
            text = await asyncio.to_thread(extract, name, data)
            out.append({"name": name, "chars": len(text), "text": text})
        except Exception as e:      # один битый файл не должен отменять остальные
            out.append({"name": name, "error": str(e)[:200]})
    return {"files": out, "limit": MAX_TOTAL_CHARS}


@app.get("/api/jobs")
def jobs(limit: int = 40):
    return [_job_card(j) for j in STORE.list(limit)]


@app.delete("/api/jobs/{jid}")
def job_delete(jid: str):
    d = job_dir(jid)
    if not d.exists():
        raise HTTPException(404)
    j = STORE.get(jid)
    if j is not None and j.status == "running":
        raise HTTPException(409, "генерация ещё идёт")
    STORE.jobs.pop(jid, None)
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


class RerunIn(BaseModel):
    template_id: Optional[str] = None
    reuse_content: bool = True


@app.post("/api/jobs/{jid}/rerun")
async def job_rerun(jid: str, body: RerunIn):
    """Тот же бриф (и по умолчанию та же контент-модель) — на другом шаблоне."""
    j = STORE.get(jid)
    if j is None:
        raise HTTPException(404)
    tid = body.template_id or j.template_id
    if load_profile(tid) is None:
        raise HTTPException(404, "шаблон не найден")
    content = None
    cp = job_dir(jid) / "content.json"
    if body.reuse_content and cp.exists():
        from ..planning.models import DeckContent
        content = DeckContent.model_validate_json(cp.read_text(encoding="utf-8"))
        for s in content.slides:
            s.image = s.image if s.image and Path(s.image).exists() else None
    new = STORE.create(tid, j.brief)
    _spawn(run_job(new, content))
    return {"id": new.id}


@app.get("/api/examples")
def examples():
    out = []
    for p in sorted((ROOT / "examples").glob("*.yaml")):
        try:
            import yaml
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
            d["id"] = p.stem
            out.append(d)
        except Exception:
            continue
    return out


@app.get("/api/audit/checks")
def audit_checks():
    from ..audit.catalog import CATEGORIES, CHECKS
    return {"checks": CHECKS, "categories": CATEGORIES}


@app.get("/api/stats")
def stats():
    js = STORE.list(200)
    done = [j for j in js if j.status == "done" and j.finished]
    secs = [j.finished - j.created for j in done]
    return {"templates": len(list_profiles()), "projects": len(js), "done": len(done),
            "avg_seconds": round(sum(secs) / len(secs), 1) if secs else None,
            "slides": sum(v.n_slides for j in done for v in j.variants)}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = STORE.get(jid)
    if j is None:
        raise HTTPException(404)
    return j.model_dump()


@app.get("/api/jobs/{jid}/events")
async def job_events(jid: str):
    j = STORE.get(jid)
    if j is None:
        raise HTTPException(404)

    async def gen():
        for ev in list(j.events):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        if j.status in ("done", "error"):
            return
        q = STORE.subscribe(jid)
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("stage") in ("done", "error"):
                    break
        finally:
            STORE.unsubscribe(jid, q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/jobs/{jid}/variants/{vid}")
def variant(jid: str, vid: str):
    j = STORE.get(jid)
    if j is None:
        raise HTTPException(404)
    try:
        plan, layouts, rep = load_variant(jid, vid)
    except FileNotFoundError:
        raise HTTPException(409, "вариант ещё не готов")
    vs = next((v for v in j.variants if v.id == vid), None)
    rev = vs.revision if vs else 0
    slides = []
    for i, (spec, lay) in enumerate(zip(plan.slides, layouts), 1):
        title = next((s.text for s in lay.slots if s.role == "title"), spec.slide.title)
        slides.append({"index": i, "title": title, "recipe": lay.recipe, "intent": spec.slide.intent,
                       "canvas": lay.canvas, "notes": lay.notes,
                       "image": f"/api/jobs/{jid}/variants/{vid}/slide/{i}.png?r={rev}",
                       "thumb": f"/api/jobs/{jid}/variants/{vid}/slide/{i}.png?w=360&r={rev}"})
    prof = load_profile(j.template_id)
    return {"variant": vs.model_dump() if vs else None, "slides": slides,
            "audit": rep.model_dump() if rep else None, "slide_w": prof.slide_w, "slide_h": prof.slide_h}


@app.get("/api/jobs/{jid}/variants/{vid}/slide/{n}.png")
def variant_slide(jid: str, vid: str, n: int, w: Optional[int] = None):
    return _thumb(job_dir(jid) / vid / "slides" / f"slide-{n:03d}.png", w)


class FixIn(BaseModel):
    issue_ids: list[str]


@app.post("/api/jobs/{jid}/variants/{vid}/fix")
async def variant_fix(jid: str, vid: str, body: FixIn):
    j = STORE.get(jid)
    if j is None:
        raise HTTPException(404)
    if not body.issue_ids:
        raise HTTPException(400, "не выбрано ни одного замечания")
    return await fix_variant(j, vid, body.issue_ids)


@app.get("/api/jobs/{jid}/variants/{vid}/download/{fmt}")
def download(jid: str, vid: str, fmt: str, inline: bool = False):
    j = STORE.get(jid)
    if j is None:
        raise HTTPException(404)
    vs = next((v for v in j.variants if v.id == vid), None)
    if vs is None or fmt not in vs.files:
        raise HTTPException(404)
    path = job_dir(jid) / vid / vs.files[fmt]
    media = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
             "pdf": "application/pdf", "html": "text/html"}[fmt]
    if inline:
        return FileResponse(path, media_type=media)
    safe = "".join(ch for ch in (j.title or "presentation") if ch.isalnum() or ch in " -_").strip()[:60] or "presentation"
    return FileResponse(path, media_type=media, filename=f"{safe} — вариант {vid}.{fmt}")


@app.get("/api/jobs/{jid}/content")
def job_content(jid: str):
    p = job_dir(jid) / "content.json"
    if not p.exists():
        raise HTTPException(404)
    return JSONResponse(json.loads(p.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ static frontend
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="frontend")

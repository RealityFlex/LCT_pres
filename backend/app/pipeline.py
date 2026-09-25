"""Оркестратор: бриф → контент → 3 варианта → сборка → рендер → аудит → экспорт.

Слои вызываются строго по порядку и обмениваются только моделями (DeckContent, VariantPlan,
SlideLayout, AuditReport), поэтому каждый слой тестируется отдельно.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .audit.contextual import audit_deck, audit_slides
from .audit.deterministic import DeterministicAuditor
from .audit.model import AuditReport, Issue
from .config import get_settings
from .export.html import pdf_to_html
from .layout.builder import DeckBuilder
from .layout.images import generate_many, image_generator
from .layout.ir import SlideLayout
from .layout.recipes import Composer
from .llm.skills import SkillRun
from .parsing.model import TemplateProfile
from .parsing.profile import load_profile
from .parsing.render import pdf_to_pngs, pptx_to_pdf
from .planning.models import Brief, ContentSlide, DeckContent, VariantPlan
from .planning.planner import plan_deck, title_capacity
from .planning.variants import build_variant, slide_extras

log = logging.getLogger("pipeline")


class VariantState(BaseModel):
    id: str
    name: str
    strategy: str
    description: str = ""
    status: str = "pending"
    n_slides: int = 0
    audit: dict[str, int] = Field(default_factory=dict)
    files: dict[str, str] = Field(default_factory=dict)
    seconds: float = 0.0
    revision: int = 0


class JobState(BaseModel):
    id: str
    template_id: str
    brief: Brief
    status: str = "queued"          # queued | running | done | error
    stage: str = ""
    progress: float = 0.0
    events: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    created: float = Field(default_factory=time.time)
    finished: Optional[float] = None
    variants: list[VariantState] = Field(default_factory=list)
    skills: dict[str, str] = Field(default_factory=dict)
    llm_stats: dict[str, Any] = Field(default_factory=dict)
    title: str = ""


def job_dir(jid: str) -> Path:
    return get_settings().jobs_dir / jid


class JobStore:
    def __init__(self):
        self.jobs: dict[str, JobState] = {}
        self.listeners: dict[str, list[asyncio.Queue]] = {}

    def create(self, template_id: str, brief: Brief) -> JobState:
        jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        job = JobState(id=jid, template_id=template_id, brief=brief)
        job_dir(jid).mkdir(parents=True, exist_ok=True)
        self.jobs[jid] = job
        self.save(job)
        return job

    def get(self, jid: str) -> Optional[JobState]:
        if jid in self.jobs:
            return self.jobs[jid]
        p = job_dir(jid) / "job.json"
        if p.exists():
            job = JobState.model_validate_json(p.read_text(encoding="utf-8"))
            self.jobs[jid] = job
            return job
        return None

    def list(self, limit: int = 30) -> list[JobState]:
        out = []
        for p in sorted(get_settings().jobs_dir.glob("*/job.json"), reverse=True)[:limit]:
            try:
                out.append(self.get(p.parent.name))
            except Exception:
                continue
        return [j for j in out if j]

    def save(self, job: JobState) -> None:
        (job_dir(job.id) / "job.json").write_text(job.model_dump_json(indent=1), encoding="utf-8")

    def emit(self, job: JobState, stage: str, message: str, progress: Optional[float] = None, **extra) -> None:
        if progress is not None:
            job.progress = round(progress, 3)
        job.stage = stage
        ev = {"t": round(time.time() - job.created, 1), "stage": stage, "message": message, "progress": job.progress, **extra}
        job.events.append(ev)
        self.save(job)
        for q in self.listeners.get(job.id, []):
            q.put_nowait(ev)

    def subscribe(self, jid: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.listeners.setdefault(jid, []).append(q)
        return q

    def unsubscribe(self, jid: str, q: asyncio.Queue) -> None:
        if q in self.listeners.get(jid, []):
            self.listeners[jid].remove(q)


STORE = JobStore()


# ====================================================================== composition helpers

def compose_variant(profile: TemplateProfile, content: DeckContent, plan: VariantPlan) -> list[SlideLayout]:
    comp = Composer(profile)
    layouts = []
    for i, spec in enumerate(plan.slides, 1):
        layouts.append(comp.compose_best(spec, i, content.title, slide_extras(content, spec)))
    return layouts


def _find_field(slide: ContentSlide, text: str) -> Optional[str]:
    t = text.strip()
    if slide.title.strip() == t or slide.title.upper().strip() == t:
        return "title"
    if slide.lead.strip() == t:
        return "lead"
    if slide.quote.strip() == t:
        return "quote"
    for i, it in enumerate(slide.items):
        if it.text.strip() == t:
            return f"items.{i}.text"
        if it.head.strip() == t:
            return f"items.{i}.head"
    for j, c in enumerate(slide.columns):
        for k, pnt in enumerate(c.points):
            if pnt.strip() == t:
                return f"columns.{j}.points.{k}"
    return None


def _set_field(slide: ContentSlide, path: str, value: str) -> None:
    parts = path.split(".")
    if parts[0] in ("title", "lead", "quote"):
        setattr(slide, parts[0], value)
    elif parts[0] == "items":
        setattr(slide.items[int(parts[1])], parts[2], value)
    elif parts[0] == "columns":
        slide.columns[int(parts[1])].points[int(parts[3])] = value


def collect_overflows(profile: TemplateProfile, content: DeckContent, layouts: list[SlideLayout]) -> list[dict]:
    by_id = {s.id: s for s in content.slides}
    out = []
    cap_title = title_capacity(profile)
    for lay in layouts:
        s = by_id.get(lay.content_id)
        if s is None:
            continue
        if "title_overflow" in lay.warnings:
            out.append({"slide": s.id, "field": "title", "text": s.title, "max_chars": max(20, int(cap_title * 0.85))})
        for ov in lay.overflows:
            field = _find_field(s, str(ov.get("text", "")).replace("\u00a0", " "))
            if field:
                out.append({"slide": s.id, "field": field, "text": ov["text"],
                            "max_chars": max(10, min(int(ov.get("max_chars", 40)), len(ov["text"]) - 3))})
        for e in lay.elements:
            if not e.overflow or not e.paras:
                continue
            txt = e.paras[0].text if len(e.paras) == 1 else None
            if not txt:
                continue
            field = _find_field(s, txt.replace(" ", " "))
            if field is None:
                continue
            size = e.size or 12
            cap = int((e.box.w / 12700) / (size * 0.52) * max(1, (e.box.h / 12700) / (size * 1.25)) * 0.85)
            out.append({"slide": s.id, "field": field, "text": txt, "max_chars": max(12, min(cap, len(txt) - 5))})
    # уникальные
    seen, uniq = set(), []
    for o in out:
        k = (o["slide"], o["field"])
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    return uniq


async def condense(content: DeckContent, overflows: list[dict], run: SkillRun) -> int:
    if not overflows:
        return 0
    items = [{"id": f"{o['slide']}:{o['field']}", "text": o["text"], "max_chars": o["max_chars"]} for o in overflows]
    try:
        res = await run.call("text_condenser", items=items)
    except Exception as e:
        log.warning("condense failed: %s", e)
        return 0
    by_id = {s.id: s for s in content.slides}
    n = 0
    for it in (res.get("items") if isinstance(res, dict) else []) or []:
        try:
            sid, field = str(it["id"]).split(":", 1)
            txt = str(it["text"]).strip()
            if sid in by_id and txt:
                _set_field(by_id[sid], field, txt)
                n += 1
        except Exception:
            continue
    return n


# ====================================================================== variant build / render / audit

def build_and_render(profile: TemplateProfile, layouts: list[SlideLayout], vdir: Path, name: str) -> dict:
    vdir.mkdir(parents=True, exist_ok=True)
    b = DeckBuilder(profile)
    for lay in layouts:
        b.add(lay)
    pptx = b.save(vdir / f"{name}.pptx")
    pdf = pptx_to_pdf(pptx, vdir)
    sl_dir = vdir / "slides"
    for old in sl_dir.glob("*.png"):
        old.unlink()
    pngs = pdf_to_pngs(pdf, sl_dir, prefix="slide")
    return {"pptx": pptx, "pdf": pdf, "pngs": pngs}


def slide_kinds(profile: TemplateProfile, layouts: list[SlideLayout]) -> list[str]:
    out = []
    for lay in layouts:
        c = profile.canvas(lay.canvas)
        if lay.recipe in ("agenda",):
            out.append("agenda")
        elif lay.recipe in ("section_synth", "section"):
            out.append("section")
        elif lay.recipe in ("title", "closing"):
            out.append(lay.recipe)
        else:
            out.append(c.kind if c.kind != "agenda" else "content")
    return out


async def audit_variant(profile: TemplateProfile, layouts: list[SlideLayout], files: dict, source: str,
                        run: SkillRun, variant: str, contextual: bool, deadline: Optional[float]) -> AuditReport:
    t0 = time.time()
    det = DeterministicAuditor(profile)
    import pymupdf
    with pymupdf.open(files["pdf"]) as d:
        pages = d.page_count
    det_task = asyncio.to_thread(det.run, files["pptx"], layouts, files["pngs"], pages)
    tasks = [det_task]
    if contextual:
        tasks.append(audit_slides(layouts, files["pngs"], slide_kinds(profile, layouts), source, run,
                                  title_capacity(profile), deadline))
        tasks.append(audit_deck(layouts, run))
    res = await asyncio.gather(*tasks, return_exceptions=True)
    issues: list[Issue] = []
    checks: list[str] = []
    if not isinstance(res[0], Exception):
        issues += res[0][0]
        checks += res[0][1]
    else:
        log.error("det audit failed: %s", res[0])
    if contextual:
        if not isinstance(res[1], Exception):
            issues += res[1][0]
            checks += ["q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q10"]
        if not isinstance(res[2], Exception):
            issues += res[2]
            checks += ["q9", "q11"]
    rep = AuditReport(variant=variant, issues=issues, checks_run=sorted(set(checks)), seconds=round(time.time() - t0, 1))
    rep.stats = {"deterministic": sum(1 for i in issues if i.deterministic),
                 "contextual": sum(1 for i in issues if not i.deterministic)}
    return rep


def source_text(brief: Brief, content: DeckContent) -> str:
    return f"Тема: {brief.topic}\nНазначение: {brief.purpose}\nАудитория: {brief.audience}\nДанные: {brief.details}\n" \
           f"Факты: {'; '.join(content.facts)}"


def save_variant(vdir: Path, plan: VariantPlan, layouts: list[SlideLayout], report: Optional[AuditReport]) -> None:
    (vdir / "plan.json").write_text(plan.model_dump_json(indent=1), encoding="utf-8")
    (vdir / "layouts.json").write_text(json.dumps([l.model_dump() for l in layouts], ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    if report is not None:
        (vdir / "audit.json").write_text(report.model_dump_json(indent=1), encoding="utf-8")


def load_variant(jid: str, vid: str) -> tuple[VariantPlan, list[SlideLayout], Optional[AuditReport]]:
    vdir = job_dir(jid) / vid
    plan = VariantPlan.model_validate_json((vdir / "plan.json").read_text(encoding="utf-8"))
    layouts = [SlideLayout.model_validate(x) for x in json.loads((vdir / "layouts.json").read_text(encoding="utf-8"))]
    ap = vdir / "audit.json"
    rep = AuditReport.model_validate_json(ap.read_text(encoding="utf-8")) if ap.exists() else None
    return plan, layouts, rep


def export_html(vdir: Path, files: dict, layouts: list[SlideLayout], title: str) -> Path:
    from .audit.contextual import slide_text
    return pdf_to_html(files["pdf"], vdir / f"{vdir.name}.html", title, [slide_text(l) for l in layouts])


# ====================================================================== main job

async def run_job(job: JobState, content_override: Optional[DeckContent] = None) -> JobState:
    s = get_settings()
    t0 = time.time()
    deadline = t0 + float(s.pipeline.get("deadline_s", 300)) - 25
    job.status = "running"
    run = SkillRun(trace_path=job_dir(job.id) / "llm_trace.jsonl")
    store = STORE
    try:
        profile = load_profile(job.template_id)
        if profile is None:
            raise RuntimeError("шаблон не найден — загрузите его заново")
        store.emit(job, "plan", "Проектирую структуру и тексты колоды", 0.04)
        content = content_override or await plan_deck(job.brief, profile, run)
        job.title = content.title
        jd = job_dir(job.id)
        (jd / "content.json").write_text(content.model_dump_json(indent=1), encoding="utf-8")
        store.emit(job, "plan", f"Структура готова: {len(content.slides)} слайдов", 0.2,
                   slides=[{"id": x.id, "intent": x.intent, "title": x.title} for x in content.slides])

        # --- изображения (генерируются один раз и переиспользуются всеми вариантами)
        prompts = [(sl.id, sl.image_prompt) for sl in content.slides if sl.image_prompt]
        if prompts and image_generator().enabled:
            store.emit(job, "images", f"Генерирую иллюстрации ({len(prompts)}) — GigaChat / Kandinsky", 0.22)
            style = profile.image_style or f"минималистичная 3D-иллюстрация, фирменные цвета #{profile.palette.primary}, без текста"
            imgs = await generate_many(prompts, style, int(s.images.get("max_per_deck", 3)))
            for sl in content.slides:
                if sl.id in imgs:
                    sl.image = str(imgs[sl.id])
                elif sl.intent == "image":
                    sl.intent = "bullets"
            (jd / "content.json").write_text(content.model_dump_json(indent=1), encoding="utf-8")
        else:
            for sl in content.slides:
                if sl.intent == "image":
                    sl.intent = "bullets"

        # --- композиция трёх вариантов + сокращение не влезающих текстов
        store.emit(job, "compose", "Раскладываю контент по макетам шаблона (3 варианта)", 0.3)
        vdefs = s.variants
        plans = {v["id"]: build_variant(content, profile, v["id"], v["name"], v["strategy"], v.get("description", ""))
                 for v in vdefs}
        layouts = {vid: compose_variant(profile, content, p) for vid, p in plans.items()}
        over = []
        for vid, lays in layouts.items():
            over += collect_overflows(profile, content, lays)
        if over:
            store.emit(job, "compose", f"Сокращаю {len(over)} фрагм. текста, не поместившихся в макет", 0.36)
            if await condense(content, over, run):
                plans = {v["id"]: build_variant(content, profile, v["id"], v["name"], v["strategy"], v.get("description", ""))
                         for v in vdefs}
                layouts = {vid: compose_variant(profile, content, p) for vid, p in plans.items()}
                (jd / "content.json").write_text(content.model_dump_json(indent=1), encoding="utf-8")
        job.variants = [VariantState(id=v["id"], name=v["name"], strategy=v["strategy"],
                                     description=v.get("description", ""), n_slides=len(layouts[v["id"]]))
                        for v in vdefs]

        # --- сборка и рендер параллельно
        store.emit(job, "build", "Собираю PPTX нативными объектами и рендерю превью", 0.42)
        async def bnr(vid):
            vs = next(v for v in job.variants if v.id == vid)
            vs.status = "building"
            tv = time.time()
            files = await asyncio.to_thread(build_and_render, profile, layouts[vid], jd / vid, f"deck_{vid}")
            vs.seconds = round(time.time() - tv, 1)
            vs.status = "rendered"
            store.emit(job, "build", f"Вариант {vid} «{vs.name}» собран", None, variant=vid)
            return vid, files
        built = dict(await asyncio.gather(*(bnr(v) for v in plans)))
        store.emit(job, "audit", "Аудит: детерминированные проверки и VLM-ревью слайдов", 0.7)

        # --- аудит
        src = source_text(job.brief, content)
        contextual = bool(s.pipeline.get("contextual_audit", True))
        async def aud(vid):
            rep = await audit_variant(profile, layouts[vid], built[vid], src, run, vid, contextual, deadline)
            vs = next(v for v in job.variants if v.id == vid)
            vs.audit = rep.summary()
            save_variant(jd / vid, plans[vid], layouts[vid], rep)
            store.emit(job, "audit", f"Вариант {vid}: найдено {len(rep.issues)} замечаний", None, variant=vid)
            return rep
        await asyncio.gather(*(aud(v) for v in plans))

        # --- экспорт
        store.emit(job, "export", "Экспорт в HTML и PDF", 0.93)
        for vid in plans:
            html_path = await asyncio.to_thread(export_html, jd / vid, built[vid], layouts[vid], content.title)
            vs = next(v for v in job.variants if v.id == vid)
            vs.files = {"pptx": built[vid]["pptx"].name, "pdf": built[vid]["pdf"].name, "html": html_path.name}
            vs.status = "done"
        job.status = "done"
        job.skills = run.used
        from .llm.client import get_llm
        job.llm_stats = dict(get_llm().stats)
        job.finished = time.time()
        store.emit(job, "done", f"Готово за {time.time() - t0:.0f} с", 1.0)
    except Exception as e:
        job.status = "error"
        job.error = f"{e.__class__.__name__}: {e}"
        log.error("job %s failed\n%s", job.id, traceback.format_exc())
        store.emit(job, "error", job.error, job.progress)
    return job


# ====================================================================== исправления по выбору пользователя

async def fix_variant(job: JobState, vid: str, issue_ids: list[str]) -> dict:
    """Применяет выбранные исправления, пересобирает вариант и повторно проверяет изменённые слайды."""
    from .audit.fixes import apply_fixes
    profile = load_profile(job.template_id)
    jd = job_dir(job.id)
    content = DeckContent.model_validate_json((jd / "content.json").read_text(encoding="utf-8"))
    plan, layouts, report = load_variant(job.id, vid)
    if report is None:
        raise RuntimeError("нет отчёта аудита")
    chosen = [i for i in report.issues if i.id in set(issue_ids)]
    run = SkillRun(trace_path=jd / "llm_trace.jsonl")
    src = source_text(job.brief, content)
    layouts, changed, log_lines = await apply_fixes(profile, content, plan, layouts, chosen, src, run)
    vs = next(v for v in job.variants if v.id == vid)
    vs.revision += 1
    vdir = jd / vid
    files = await asyncio.to_thread(build_and_render, profile, layouts, vdir, f"deck_{vid}")
    # детерминированный аудит — целиком, контекстный — только по изменённым слайдам
    det = DeterministicAuditor(profile)
    import pymupdf
    with pymupdf.open(files["pdf"]) as d:
        pages = d.page_count
    det_issues, checks = await asyncio.to_thread(det.run, files["pptx"], layouts, files["pngs"], pages)
    keep_ctx = [i for i in report.issues if not i.deterministic and i.slide not in changed and i.id not in set(issue_ids)]
    new_ctx: list[Issue] = []
    if changed and get_settings().pipeline.get("contextual_audit", True):
        idx = sorted(changed)
        sub_l = [layouts[n - 1] for n in idx if n - 1 < len(layouts)]
        sub_p = [files["pngs"][n - 1] for n in idx if n - 1 < len(files["pngs"])]
        kinds = slide_kinds(profile, sub_l)
        ctx, _ = await audit_slides(sub_l, sub_p, kinds, src, run, title_capacity(profile))
        for iss in ctx:  # перенумеровать на реальные номера
            iss.slide = idx[iss.slide - 1]
            iss.id = f"{iss.check}-{iss.slide}-r{vs.revision}"
        new_ctx = ctx
    rep = AuditReport(variant=vid, issues=det_issues + keep_ctx + new_ctx, checks_run=report.checks_run,
                      stats={"revision": vs.revision, "fixed": len(chosen), "log": log_lines})
    save_variant(vdir, plan, layouts, rep)
    await asyncio.to_thread(export_html, vdir, files, layouts, content.title)
    vs.audit = rep.summary()
    vs.n_slides = len(layouts)
    STORE.save(job)
    return {"revision": vs.revision, "changed": sorted(changed), "log": log_lines, "audit": rep.model_dump()}

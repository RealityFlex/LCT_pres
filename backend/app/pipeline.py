"""Оркестратор: бриф → контент → 3 варианта → сборка → рендер → аудит → экспорт.

Слои вызываются строго по порядку и обмениваются только моделями (DeckContent, VariantPlan,
SlideLayout, AuditReport), поэтому каждый слой тестируется отдельно.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
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
    status: str = "queued"          # queued | running | outline | done | error
    mode: str = "direct"            # direct — сразу собрать; outline — остановиться на плане для правки
    only: list[str] = Field(default_factory=list)   # собрать только эти варианты (A/B/C); пусто — все
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
            if job.status in ("queued", "running"):
                # задача с диска, но не из этого процесса: сервер перезапускался посреди генерации
                job.status = "error"
                job.error = "Генерация прервана: сервер был перезапущен. Запустите её заново."
                job.finished = job.finished or time.time()
                self.save(job)
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
    section = ""
    for i, spec in enumerate(plan.slides, 1):
        if spec.slide.intent == "section":
            section = spec.slide.title
        ex = slide_extras(content, spec)
        ex["section_name"] = section      # кикер по умолчанию — раздел, в котором стоит слайд
        layouts.append(comp.compose_best(spec, i, content.title, ex))
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


def brief_no_data(source: str) -> bool:
    """В брифе нет своих данных (поле «Данные» пустое или почти пустое)."""
    m = re.search(r"Данные:(.*?)(?:\nФакты:|$)", source, re.S)
    return len((m.group(1) if m else "").strip()) < 20


def short_titles(profile) -> bool:
    """Нарратив шаблона — короткие заголовки-темы (2–3 слова), а не заголовки-выводы."""
    n = profile.narrative
    return bool(n and 0 < (n.avg_title_words or 0) <= 3.5)


def slide_kinds(profile: TemplateProfile, layouts: list[SlideLayout]) -> list[str]:
    out = []
    for lay in layouts:
        c = profile.canvas(lay.canvas)
        if lay.recipe in ("agenda",) or lay.intent == "agenda":
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
    from .core.mupdf_lock import LOCK
    with LOCK, pymupdf.open(files["pdf"]) as d:
        pages = d.page_count
    det_task = asyncio.to_thread(det.run, files["pptx"], layouts, files["pngs"], pages)
    tasks = [det_task]
    if contextual:
        tasks.append(audit_slides(layouts, files["pngs"], slide_kinds(profile, layouts), source, run,
                                  title_capacity(profile), deadline, short_titles(profile), brief_no_data(source)))
        tasks.append(_bounded(audit_deck(layouts, run), deadline, []))
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


async def _bounded(coro, deadline: Optional[float], default=None):
    """Корутина с потолком по времени: к дедлайну не успела — значение по умолчанию, прогон не ждёт."""
    if deadline is None:
        return await coro
    left = deadline - time.time()
    if left <= 1:
        coro.close()
        return default
    try:
        return await asyncio.wait_for(coro, left)
    except asyncio.TimeoutError:
        return default


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


# ====================================================================== images

async def add_images(job: JobState, content: DeckContent, profile: TemplateProfile, run: SkillRun,
                     research=None) -> None:
    s = get_settings()
    store = STORE
    limit = int(s.images.get("max_per_deck", 3))
    src = (job.brief.image_source or "auto").lower()
    need = [sl for sl in content.slides if sl.intent == "image" and not sl.image][:limit]
    if need and src in ("auto", "web"):
        from .research.photos import find_photos
        store.emit(job, "images", f"Подбираю фото в Wikimedia Commons ({len(need)})", 0.22)
        files = [a["image"] for a in (research.articles if research else []) if a.get("image")]
        if not files and (job_dir(job.id) / "research.json").exists():
            try:
                arts = json.loads((job_dir(job.id) / "research.json").read_text(encoding="utf-8")).get("articles", [])
                files = [a["image"] for a in arts if a.get("image")]
            except Exception:
                files = []
        photos = await find_photos(need, job.brief.topic, run, job_dir(job.id) / "photos", limit, files)
        for sl in need:
            if sl.id in photos:
                path, credit, page = photos[sl.id]
                sl.image, sl.image_credit = str(path), credit
                sl.notes = (sl.notes.rstrip() + f"\n\n{credit}, Wikimedia Commons — {page}").strip()
        if photos:
            store.emit(job, "images", f"Фото из Wikimedia Commons: {len(photos)} из {len(need)}", 0.24)
    rest = [sl for sl in need if not sl.image]
    prompts = [(sl.id, sl.image_prompt) for sl in rest if sl.image_prompt]
    if prompts and src in ("auto", "generate") and image_generator().enabled:
        store.emit(job, "images", f"Генерирую иллюстрации ({len(prompts)}) — GigaChat / Kandinsky", 0.25)
        # описание стиля шаблона («векторная инфографика, иконки, интерфейс») тянет генератор в схемы
        # с псевдобуквами — ему передаём только фирменные цвета словами
        from .layout.images import palette_words
        imgs = await generate_many(prompts, palette_words(profile), limit)
        for sl in rest:
            if sl.id in imgs:
                sl.image = str(imgs[sl.id])
    for sl in content.slides:
        if sl.intent == "image" and not sl.image:
            sl.intent = "bullets"


# ====================================================================== main job

async def run_job(job: JobState, content_override: Optional[DeckContent] = None) -> JobState:
    s = get_settings()
    t0 = time.time()
    # обычный режим: три колоды не дольше deadline_s (5 минут) — у этапов с моделью свой потолок времени;
    # extended thinking: без лимита — все попытки дизайнера, полный аудит и автоисправление оформления
    extended = job.brief.quality == "extended"
    ext = s.pipeline.get("extended", {}) or {}
    deadline = t0 + (float(ext.get("deadline_s", 3600)) if extended else float(s.pipeline.get("deadline_s", 300)) - 25)
    job.status = "running"
    run = SkillRun(trace_path=job_dir(job.id) / "llm_trace.jsonl")
    store = STORE
    try:
        if not job.template_id:
            # без корпоративного шаблона: встроенный стиль Лекала (пак собирается один раз и кэшируется)
            from .styles.registry import pick_style, resolve
            store.emit(job, "style", "Подбираю стиль презентации", 0.02)
            sid = job.brief.style_id or "auto"
            if sid == "auto":
                # недавние колоды в стилях Лекала — «Авто» не повторяет их без нужды
                recent = [j.brief.style_id for j in store.list(8)
                          if j.id != job.id and (j.template_id or "").startswith("style-") and j.brief.style_id][:3]
                sid = await pick_style(job.brief, run, recent)
            job.brief.style_id = sid
            kwargs: dict = {}
            colors, fonts = job.brief.style_colors, job.brief.style_fonts
            if job.brief.brand_id:
                # брендбук задаёт цвета, шрифты и логотип стиля (свои цвета пользователя — поверх, если заданы)
                from .brand import apply as brand_apply, store as brand_store
                kit = brand_store.load(job.brief.brand_id)
                warn: list[str] = []
                args = brand_apply.style_args(kit, warn)
                colors = {**args["colors"], **(colors or {})}
                fonts = {**args["fonts"], **(fonts or {})}
                kwargs = {"logo": args["logo"], "logo_dark": args["logo_dark"], "brand_name": args["brand_name"],
                          "grid": args["grid"]}
                store.emit(job, "brand", f"Брендбук «{kit.name}»: {kit.summary()}", 0.02,
                           warnings=warn + kit.warnings)
            job.template_id = await asyncio.to_thread(resolve, sid, colors, fonts, None, **kwargs)
            store.save(job)
        elif job.brief.brand_id and "-brand-" not in job.template_id:
            # шаблон компании + брендбук: производный шаблон в цветах, шрифтах и с логотипом бренда
            from .brand import apply as brand_apply, store as brand_store
            kit = brand_store.load(job.brief.brand_id)
            base = load_profile(job.template_id)
            if base is None:
                raise RuntimeError("шаблон не найден — загрузите его заново")
            store.emit(job, "brand", f"Применяю брендбук «{kit.name}» к шаблону «{base.name}»", 0.02)
            warn = []
            job.template_id = await asyncio.to_thread(brand_apply.derive_template, base, kit,
                                                      job.brief.brand_priority, warn)
            store.emit(job, "brand", f"Шаблон в стиле бренда готов: {kit.summary()}", 0.03, warnings=warn + kit.warnings)
            store.save(job)
        profile = load_profile(job.template_id)
        if profile is None:
            raise RuntimeError("шаблон не найден — загрузите его заново")
        src = job.brief.source_text
        if content_override is None and src and "ПРИЛОЖЕННЫЕ МАТЕРИАЛЫ" not in job.brief.details:
            # длинный документ: читаем целиком по кускам и сводим в выжимку для планировщика
            mcfg = s.raw.get("materials", {})
            from .planning.digest import digest
            store.emit(job, "plan", f"Читаю материалы целиком: {len(src) // 1000} тыс. знаков", 0.03)
            d = await digest(src, job.brief.topic, run, int(mcfg.get("chunk_chars", 8000)), int(mcfg.get("digest_chars", 12000)))
            job.brief.details = (job.brief.details.strip() + "\n\nПРИЛОЖЕННЫЕ МАТЕРИАЛЫ (выжимка документа целиком)\n" + d).strip()
            store.save(job)
        insights = []
        failed: list[dict] = []
        cross: list[str] = []
        if content_override is None and job.brief.datasets:
            # файлы с данными: природа каждого датасета, расчёты и визуализация — кодом, выводы — моделью
            from .analytics import story
            paths = [s.data_dir / "uploads" / d for d in job.brief.datasets if re.fullmatch(r"[\w.\-]+", d)]
            store.emit(job, "data", f"Анализирую данные: файлов — {len(paths)}", 0.03)
            # цель анализа — из брифа человека (без приложенных материалов) и из карточек датасетов
            own = job.brief.details.split("\n\nПРИЛОЖЕННЫЕ МАТЕРИАЛЫ")[0]
            insights, texts = await asyncio.to_thread(story.load_insights, [p for p in paths if p.exists()],
                                                      job.brief.dataset_goals, f"{job.brief.topic}. {own}", failed, cross)
            story.save(insights, job_dir(job.id) / "analysis.json")
            if insights:
                job.brief.details = (job.brief.details.strip() + story.planner_note(insights)
                                     + ("\n\nТЕКСТ ИЗ ФАЙЛОВ С ДАННЫМИ\n" + "\n\n".join(texts) if texts else "")).strip()
                store.save(job)
                kinds = ", ".join(dict.fromkeys(x.nature_ru for x in insights))
                store.emit(job, "data", f"Датасетов: {len(insights)} — {kinds}", 0.035,
                           datasets=[{"name": x.dataset, "nature": x.nature_ru, "rows": x.rows,
                                      "task": story.TASK_RU.get(x.nature, x.nature),
                                      "viz": x.options[0]["label"] if x.options else ""} for x in insights]
                           + [{"name": f["name"], "nature": "не распознано", "rows": 0, "reason": f["reason"]} for f in failed])
        research = None
        if content_override is None and job.brief.web_search and "ДАННЫЕ ИЗ ИНТЕРНЕТА" not in job.brief.details:
            # как Genspark/Kimi: сначала фактура из интернета (бесплатно — API Википедии), потом план
            from .research.web import research as do_research
            # подробный материал пользователя (методичка, отчёт) — главный источник, из сети только дополнение
            supplement = max(len(job.brief.source_text), len(job.brief.details)) > 10000
            store.emit(job, "research", "Дополняю материал фактами из Википедии" if supplement
                       else "Ищу факты по теме в Википедии", 0.035)
            research = await _bounded(do_research(job.brief, run, supplement),
                                      None if extended else t0 + float(s.pipeline.get("research_s", 40)))
            if research is None:
                from .research.web import Research
                research = Research()
            (job_dir(job.id) / "research.json").write_text(research.model_dump_json(indent=1), encoding="utf-8")
            if research.facts:
                job.brief.details = (job.brief.details.strip() + "\n\n" + research.text()).strip()
                store.save(job)
                store.emit(job, "research", f"Найдено фактов: {len(research.facts)} из {len(research.sources)} статей", 0.04,
                           sources=[{"title": x.title, "url": x.url} for x in research.sources])
            else:
                store.emit(job, "research", "В Википедии ничего полезного по теме не нашлось — работаю по брифу", 0.04)
        store.emit(job, "plan", "Проектирую структуру и тексты колоды", 0.04)
        plan_brief = job.brief
        # колода по данным: несколько датасетов (или только данные без других материалов) — каркас сюжета
        # строит код (титул → главное → данные → выводы → рекомендации → финал), модель пишет слова
        data_mode = content_override is None and bool(insights) and (
            len(insights) >= 2 or "ПРИЛОЖЕННЫЕ МАТЕРИАЛЫ" not in job.brief.details)
        if insights and not data_mode:
            # слайды с данными добавляются отдельно — сценарист пишет вступление, выводы и рекомендации
            total = job.brief.slide_count or max(10, min(16, len(insights) + 6))
            plan_brief = job.brief.model_copy(update={"slide_count": max(5, total - len(insights))})
        if data_mode:
            from .analytics import story
            store.emit(job, "data", "Выстраиваю историю по данным: главная мысль, порядок, выводы", 0.1)
            content = await story.data_deck(insights, failed, cross, job.brief, profile, run, texts)
            store.emit(job, "data", f"Слайды с данными: {sum(1 for x in content.slides if x.data)}"
                       + (f"; перекрёстных фактов — {len(cross)}" if cross else ""), 0.19)
        else:
            content = content_override or await plan_deck(plan_brief, profile, run)
        if content_override is None and not data_mode:
            # числа, которых нет в брифе, правятся до вёрстки, а не только помечаются аудитом
            from .planning.facts import enforce
            fixed = await enforce(content, job.brief, run, title_capacity(profile))
            if fixed:
                store.emit(job, "plan", f"Сверка с брифом: исправлено слайдов — {len(fixed)}", 0.18)
            if insights or failed:
                from .analytics import story
                store.emit(job, "data", "Формулирую выводы по каждому датасету", 0.185)
                dslides = await story.data_slides(insights, job.brief, profile, run)
                # нераспознанный датасет в презентацию не идёт: причина видна в карточке файла в форме и в событиях
                story.insert_data_slides(content, dslides)
                store.emit(job, "data", f"Слайды с данными: {len(dslides)}", 0.19)
            if research is not None and research.facts:
                from .research.web import attach_sources
                n_src = attach_sources(content, research)
                if n_src:
                    store.emit(job, "plan", f"Источники указаны на слайдах: {n_src}", 0.19)
        job.title = content.title
        jd = job_dir(job.id)
        (jd / "content.json").write_text(content.model_dump_json(indent=1), encoding="utf-8")
        store.emit(job, "plan", f"Структура готова: {len(content.slides)} слайдов", 0.2,
                   slides=[{"id": x.id, "intent": x.intent, "title": x.title} for x in content.slides])
        if job.mode == "outline" and content_override is None:
            # как outline у Kimi/Gamma: человек правит план, сборка — по кнопке (POST /api/jobs/{id}/build)
            job.status = "outline"
            job.skills = run.used
            store.emit(job, "outline", "План готов: проверьте структуру и соберите презентацию", 0.2)
            return job

        # --- изображения (один раз на задачу, общие для всех вариантов): сначала свободные фото
        # Wikimedia Commons, где их нет — иллюстрации генератора
        await add_images(job, content, profile, run, research)
        (jd / "content.json").write_text(content.model_dump_json(indent=1), encoding="utf-8")

        # --- композиция трёх вариантов + сокращение не влезающих текстов
        store.emit(job, "compose", "Раскладываю контент по макетам шаблона", 0.3)
        vdefs = [v for v in s.variants if not job.only or v["id"] in job.only] or s.variants
        # послайдовые варианты (как Kimi): модель рисует слайды сама, поэтому слайды-паттерны шаблона им не нужны
        ffcfg = s.raw.get("freeform", {}) or {}
        free = set(ffcfg.get("variants", []) if ffcfg.get("enabled", True) else [])
        bare = profile.model_copy(update={"patterns": []})

        def make_plans():
            return {v["id"]: build_variant(content, bare if v["id"] in free else profile, v["id"], v["name"], v["strategy"],
                                           v.get("description", "")) for v in vdefs}
        plans = make_plans()
        layouts = {vid: compose_variant(profile, content, p) for vid, p in plans.items()}
        over = []
        for vid, lays in layouts.items():
            over += collect_overflows(profile, content, lays)
        if over:
            store.emit(job, "compose", f"Сокращаю {len(over)} фрагм. текста, не поместившихся в макет", 0.36)
            if await condense(content, over, run):
                plans = make_plans()
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
            designs = {}
            if vid in free:
                from .layout.freeform import critique, design_deck
                store.emit(job, "build", f"Вариант {vid}: модель компонует каждый слайд по дизайн-системе", None, variant=vid)
                designs = await design_deck(content, layouts[vid], profile, run, content.title,
                                            int(ext.get("designer_attempts", 4)) if extended else int(ffcfg.get("attempts", 3)),
                                            None if extended else t0 + float(s.pipeline.get("designer_s", 200)))
                fell = sum(1 for l in layouts[vid] if "freeform_fallback" in l.warnings)
                store.emit(job, "build", f"Вариант {vid}: модель нарисовала {len(designs)} слайдов"
                           + (f", рецептом — {fell}" if fell else ""), None, variant=vid)
            files = await asyncio.to_thread(build_and_render, profile, layouts[vid], jd / vid, f"deck_{vid}")
            if designs and ffcfg.get("critic", True) and (extended or time.time() < deadline - 60):
                store.emit(job, "build", f"Вариант {vid}: проверяю слайды по скриншотам", None, variant=vid)
                fixed = await critique(layouts[vid], designs, files["pngs"], run)
                if fixed:
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
            return vid, rep
        reports = dict(await asyncio.gather(*(aud(v) for v in plans)))

        # --- extended thinking: исправимые замечания оформления правятся автоматически, слайды проверяются заново
        if extended:
            from .audit.fixes import apply_fixes
            for rnd in range(int(ext.get("fix_rounds", 2))):
                todo = {vid: [i for i in rep.issues if i.fixable and i.severity in ("error", "warning")]
                        for vid, rep in reports.items()}
                todo = {k: v for k, v in todo.items() if v}
                if not todo:
                    break
                store.emit(job, "audit", f"Extended thinking, круг {rnd + 1}: исправляю замечаний — "
                           f"{sum(len(v) for v in todo.values())}", 0.8 + 0.05 * rnd)

                async def fix_one(vid, chosen, rnd=rnd):
                    lays, changed, _ = await apply_fixes(profile, content, plans[vid], layouts[vid], chosen, src, run)
                    if not changed:
                        return vid, reports[vid]
                    layouts[vid] = lays
                    out = await rebuild_variant(job, vid, profile, content, plans[vid], lays, reports[vid], set(changed),
                                                {i.id for i in chosen}, run, {"auto_fix_round": rnd + 1}, time.time())
                    return vid, AuditReport.model_validate(out["audit"])
                reports.update(dict(await asyncio.gather(*(fix_one(v, c) for v, c in todo.items()))))
            (jd / "content.json").write_text(content.model_dump_json(indent=1), encoding="utf-8")
            for vid, rep in reports.items():
                left = sum(1 for i in rep.issues if i.severity == "error")
                store.emit(job, "audit", f"Вариант {vid}: после автоисправления ошибок оформления — {left}", None, variant=vid)

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

async def rebuild_variant(job: JobState, vid: str, profile: TemplateProfile, content: DeckContent, plan: VariantPlan,
                          layouts: list[SlideLayout], report: AuditReport, changed: set[int], drop_ids: set[str],
                          run: SkillRun, stats: dict, t0: float) -> dict:
    """Пересборка варианта после правки: PPTX/PDF/PNG, детерминированный аудит целиком,
    контекстный — только по изменённым слайдам, HTML; состояние варианта сохраняется."""
    vs = next(v for v in job.variants if v.id == vid)
    vs.revision += 1
    jd = job_dir(job.id)
    vdir = jd / vid
    src = source_text(job.brief, content)
    files = await asyncio.to_thread(build_and_render, profile, layouts, vdir, f"deck_{vid}")
    det = DeterministicAuditor(profile)
    import pymupdf
    from .core.mupdf_lock import LOCK
    with LOCK, pymupdf.open(files["pdf"]) as d:
        pages = d.page_count
    det_issues, checks = await asyncio.to_thread(det.run, files["pptx"], layouts, files["pngs"], pages)
    keep_ctx = [i for i in report.issues if not i.deterministic and i.slide not in changed and i.id not in drop_ids]
    new_ctx: list[Issue] = []
    if changed and get_settings().pipeline.get("contextual_audit", True):
        idx = sorted(changed)
        sub_l = [layouts[n - 1] for n in idx if n - 1 < len(layouts)]
        sub_p = [files["pngs"][n - 1] for n in idx if n - 1 < len(files["pngs"])]
        kinds = slide_kinds(profile, sub_l)
        ctx, _ = await audit_slides(sub_l, sub_p, kinds, src, run, title_capacity(profile),
                                    short_titles=short_titles(profile), no_data=brief_no_data(src))
        for iss in ctx:  # перенумеровать на реальные номера
            iss.slide = idx[iss.slide - 1]
            iss.id = f"{iss.check}-{iss.slide}-r{vs.revision}"
        new_ctx = ctx
    rep = AuditReport(variant=vid, issues=det_issues + keep_ctx + new_ctx, checks_run=report.checks_run,
                      stats={"revision": vs.revision, **stats}, seconds=round(time.time() - t0, 1))
    save_variant(vdir, plan, layouts, rep)
    await asyncio.to_thread(export_html, vdir, files, layouts, content.title)
    vs.audit = rep.summary()
    vs.n_slides = len(layouts)
    STORE.save(job)
    return {"revision": vs.revision, "changed": sorted(changed), "audit": rep.model_dump()}


async def fix_variant(job: JobState, vid: str, issue_ids: list[str]) -> dict:
    """Применяет выбранные исправления, пересобирает вариант и повторно проверяет изменённые слайды."""
    from .audit.fixes import apply_fixes
    t0 = time.time()
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
    out = await rebuild_variant(job, vid, profile, content, plan, layouts, report, set(changed), set(issue_ids), run,
                                {"fixed": len(chosen), "log": log_lines}, t0)
    return {**out, "log": log_lines}


def _insight_for(job: JobState, slide: ContentSlide):
    from .analytics.analyze import Insight
    path = job_dir(job.id) / "analysis.json"
    if not path.exists():
        return None
    for d in json.loads(path.read_text(encoding="utf-8")):
        if d.get("dataset") == slide.data.get("dataset"):
            return Insight.from_dict(d)
    return None


async def switch_chart(job: JobState, vid: str, n: int, viz: str) -> dict:
    """Альтернативная визуализация слайда данных: тот же агрегат → другой тип, пересборка одного слайда."""
    from .analytics import story
    t0 = time.time()
    profile = load_profile(job.template_id)
    jd = job_dir(job.id)
    content = DeckContent.model_validate_json((jd / "content.json").read_text(encoding="utf-8"))
    plan, layouts, report = load_variant(job.id, vid)
    if report is None or not (1 <= n <= len(plan.slides)):
        raise ValueError("нет такого слайда")
    spec = plan.slides[n - 1]
    slide = spec.slide
    opts = [o["type"] for o in slide.data.get("options", [])]
    if viz not in opts:
        raise ValueError("этот вариант визуализации не предлагался для слайда")
    ins = _insight_for(job, slide)
    if ins is None:
        raise ValueError("нет расчёта по датасету слайда")
    story.apply_viz(slide, ins, viz)
    # рецепт и холст — заново под новое намерение слайда (диаграмма / таблица / карточки)
    mini = DeckContent(title=content.title, slides=[slide], target_slides=1)
    new_spec = build_variant(mini, profile, vid, plan.name, plan.strategy).slides[0]
    new_spec.slide = slide
    plan.slides[n - 1] = new_spec
    section = next((x.slide.title for x in reversed(plan.slides[:n - 1]) if x.slide.intent == "section"), "")
    ex = slide_extras(content, new_spec)
    ex["section_name"] = section
    layouts[n - 1] = Composer(profile).compose_best(new_spec, n, content.title, ex)
    for i, x in enumerate(content.slides):
        if x.id == slide.id:
            content.slides[i] = slide
    (jd / "content.json").write_text(content.model_dump_json(indent=1), encoding="utf-8")
    run = SkillRun(trace_path=jd / "llm_trace.jsonl")
    label = next((o["label"] for o in slide.data.get("options", []) if o["type"] == viz), viz)
    out = await rebuild_variant(job, vid, profile, content, plan, layouts, report, {n}, set(), run,
                                {"switched": f"слайд {n}: {label}"}, t0)
    return {**out, "viz": viz, "label": label}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Icon20CheckCircleOn,
  Icon24ArrowLeftOutline,
  Icon24CopyOutline,
  Icon24DeleteOutline,
  Icon24MagicWandOutline,
  Icon24NarrativeOutline,
  Icon24PaletteOutline,
  Icon24TextOutline,
  Icon24WarningTriangleOutline,
} from "@vkontakte/icons";
import { clsx } from "clsx";
import { motion } from "motion/react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge, Button, Panel, Segmented, SectionHead, Spinner, useToast } from "../components/ui";
import { api, withW, type CanvasInfo, type TemplateDetail as TD } from "../lib/api";
import { CANVAS_KIND, hex, isDark, ROLE } from "../lib/format";

const ROLES: [string, string][] = [
  ["title", "Заголовок"], ["subtitle", "Подзаголовок"], ["kicker", "Кикер"], ["heading", "Заголовок пункта"],
  ["body", "Основной текст"], ["caption", "Подпись"], ["number", "Крупная цифра"],
];
const KIND_COLOR: Record<string, string> = { title: "var(--brand)", section: "var(--purple)", agenda: "var(--pink)", closing: "var(--green)", content: "var(--text-4)" };

function Tile({ color, label, big }: { color: string; label: string; big?: boolean }) {
  const toast = useToast();
  const c = hex(color);
  return (
    <button onClick={() => { navigator.clipboard?.writeText(c.toUpperCase()); toast({ tone: "ok", title: `Скопировано ${c.toUpperCase()}` }); }}
      className={clsx("group relative overflow-hidden rounded-2xl text-left ring-1 ring-[var(--line)] transition-transform hover:-translate-y-0.5", big ? "h-32" : "h-24")}
      style={{ background: c }}>
      <div className={clsx("absolute inset-x-0 bottom-0 flex items-end justify-between p-3", isDark(c) ? "text-white" : "text-black")}>
        <div>
          <div className="text-[11px] font-semibold opacity-75">{label}</div>
          <div className="font-mono text-[13px] font-semibold">{c.toUpperCase()}</div>
        </div>
        <Icon24CopyOutline width={16} height={16} className="opacity-0 transition-opacity group-hover:opacity-80" />
      </div>
    </button>
  );
}

function CanvasCard({ c, t }: { c: CanvasInfo; t: TD }) {
  const [hover, setHover] = useState(false);
  const b = c.content_box;
  return (
    <div onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      className="overflow-hidden rounded-2xl border border-line bg-surface">
      <div className="relative" style={{ aspectRatio: `${t.slide_w}/${t.slide_h}` }}>
        <img src={withW(c.preview, 480)} alt="" loading="lazy" className="h-full w-full object-cover" />
        <motion.div initial={false} animate={{ opacity: hover ? 1 : 0 }}
          className="pointer-events-none absolute rounded border-2 border-dashed border-brand bg-[color-mix(in_srgb,var(--brand)_12%,transparent)]"
          style={{ left: `${(b.x / t.slide_w) * 100}%`, top: `${(b.y / t.slide_h) * 100}%`, width: `${(b.w / t.slide_w) * 100}%`, height: `${(b.h / t.slide_h) * 100}%` }} />
      </div>
      <div className="flex flex-wrap items-center gap-1.5 p-2.5">
        <Badge className="!h-5 !text-[10px]" tone="accent">{CANVAS_KIND[c.kind] ?? c.kind}</Badge>
        <Badge className="!h-5 !text-[10px]">{c.dark ? "тёмный" : "светлый"}</Badge>
        {c.clean ? <Badge className="!h-5 !text-[10px]" tone="ok">чистый</Badge> : <Badge className="!h-5 !text-[10px]" tone="warn">декор</Badge>}
        <span className="ml-auto font-mono text-[10px] text-fg-4">{c.id} · {c.score.toFixed(1)}</span>
      </div>
    </div>
  );
}

export default function TemplateDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["template", id], queryFn: () => api.template(id) });
  const [canvF, setCanvF] = useState<"all" | "content" | "struct">("all");
  const del = useMutation({
    mutationFn: () => api.deleteTemplate(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["templates"] }); toast({ tone: "ok", title: "Шаблон удалён" }); nav("/templates"); },
  });
  if (q.isLoading || !q.data) return <div className="grid min-h-[60vh] place-items-center"><Spinner size={30} className="text-accent" /></div>;
  const t = q.data;
  const p = t.palette;
  const totalW = p.colors.reduce((a, c) => a + c.weight, 0) || 1;
  const canv = t.canvas_list.filter((c) => canvF === "all" || (canvF === "content" ? c.kind === "content" || c.kind === "agenda" : c.kind !== "content" && c.kind !== "agenda"));
  const service = t.slides.filter((s) => s.service).length;
  const n = t.narrative;

  return (
    <div className="mx-auto max-w-[1360px] px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
      <Link to="/templates" className="mb-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-fg-3 hover:text-fg">
        <Icon24ArrowLeftOutline width={16} height={16} /> Шаблоны
      </Link>

      {/* ------------------------------------------ шапка */}
      <div className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
        <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}
          className="overflow-hidden rounded-[22px] shadow-[var(--shadow-2)] ring-1 ring-[var(--line)]">
          <img src={withW(t.cover, 1200)} alt="" className="w-full" style={{ aspectRatio: `${t.slide_w}/${t.slide_h}`, objectFit: "cover" }} />
        </motion.div>
        <div className="flex flex-col">
          <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">Дизайн-система</div>
          <h1 className="font-display text-[30px] font-semibold leading-tight tracking-tight sm:text-[36px]">{t.name}</h1>
          <div className="mt-4 grid grid-cols-3 gap-3">
            {[
              [t.n_slides, "слайдов в образце"],
              [t.canvases, "холстов-основ"],
              [service, "служебных отброшено"],
            ].map(([v, l]) => (
              <div key={String(l)} className="rounded-2xl border border-line bg-[color-mix(in_srgb,var(--surface)_60%,transparent)] p-3">
                <div className="font-display text-[24px] font-semibold">{v}</div>
                <div className="text-[11px] leading-tight text-fg-3">{l}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 space-y-2 text-[13px]">
            {Object.entries(t.fonts_found).map(([f, ok]) => (
              <div key={f} className="flex items-center gap-2">
                {ok ? <Icon20CheckCircleOn className="text-ok" /> : <Icon24WarningTriangleOutline width={18} height={18} className="text-orange" />}
                <span className="font-semibold">{f}</span>
                <span className="text-fg-3">{ok ? "шрифт найден" : "будет заменён метрически близким"}</span>
              </div>
            ))}
          </div>
          {t.style_summary && !t.style_summary.startsWith("(") && (
            <p className="mt-4 text-[14px] leading-relaxed text-fg-2 text-pretty">{t.style_summary}</p>
          )}
          <div className="mt-auto flex flex-wrap gap-2 pt-6">
            <Button variant="primary" glow size="lg" onClick={() => nav(`/new?template=${t.id}`)} icon={<Icon24MagicWandOutline width={20} height={20} />}>
              Создать презентацию
            </Button>
            <Button variant="danger" size="lg" loading={del.isPending} onClick={() => del.mutate()} icon={<Icon24DeleteOutline width={20} height={20} />} title="Удалить шаблон" />
          </div>
        </div>
      </div>

      {/* ------------------------------------------ палитра */}
      <section className="mt-14">
        <SectionHead eyebrow="Токены" title={<span className="inline-flex items-center gap-2"><Icon24PaletteOutline className="text-accent" /> Палитра</span>} />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
          <Tile big color={p.primary} label="Основной" />
          {p.accents.slice(0, 3).map((a, k) => <Tile big key={a} color={a} label={`Акцент ${k + 1}`} />)}
          <Tile big color={p.bg_light} label="Светлый фон" />
          <Tile big color={p.bg_dark} label="Тёмный фон" />
          <Tile big color={p.text_dark} label="Текст" />
          {p.surface ? <Tile big color={p.surface} label="Подложка" /> : <Tile big color={p.muted_dark} label="Второстеп." />}
        </div>
        <Panel className="mt-4 p-4">
          <div className="mb-2 text-[12px] font-semibold text-fg-3">Вес цветов в шаблоне (по площади и объёму текста)</div>
          <div className="flex h-10 overflow-hidden rounded-xl ring-1 ring-[var(--line)]">
            {p.colors.map((c) => (
              <div key={c.hex} title={`${hex(c.hex)} · ${ROLE[c.role] ?? c.role}`} style={{ background: hex(c.hex), flexGrow: Math.max(0.02, c.weight / totalW) }} />
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="text-[12px] text-fg-3">Цвета диаграмм:</span>
            {p.chart.map((c) => <span key={c} className="h-5 w-10 rounded-md ring-1 ring-[var(--line)]" style={{ background: hex(c) }} />)}
          </div>
        </Panel>
      </section>

      {/* ------------------------------------------ типографика */}
      <section className="mt-14">
        <SectionHead eyebrow="Токены" title={<span className="inline-flex items-center gap-2"><Icon24TextOutline className="text-accent" /> Типографика</span>} />
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <Panel className="divide-y divide-[var(--line)]">
            {ROLES.map(([k, label]) => {
              const s = t.typography[k];
              if (!s) return null;
              return (
                <div key={k} className="flex items-center gap-4 px-5 py-4">
                  <div className="w-32 shrink-0 text-[12px] font-semibold text-fg-3">{label}</div>
                  <div className="min-w-0 flex-1 truncate" style={{
                    fontFamily: `'${s.font}', var(--font-sans)`, fontSize: Math.min(40, Math.max(13, s.size * 1.15)),
                    fontWeight: s.bold ? 700 : 400, textTransform: s.caps || (k === "title" && t.title_caps) ? "uppercase" : undefined, lineHeight: 1.15,
                  }}>
                    {k === "number" ? "91%" : "Лекало читает шаблон"}
                  </div>
                  <div className="shrink-0 text-right font-mono text-[11px] leading-tight text-fg-3">
                    <div className="text-fg-2">{s.font}</div>
                    <div>{s.size} pt{s.bold ? " · bold" : ""}{s.caps ? " · caps" : ""}</div>
                  </div>
                  <span className="size-4 shrink-0 rounded-full ring-1 ring-[var(--line)]" style={{ background: hex(s.color) }} />
                </div>
              );
            })}
          </Panel>
          <Panel className="p-5">
            <div className="mb-4 text-[13px] font-semibold">Шкала кеглей</div>
            <div className="flex h-44 items-end gap-1.5">
              {t.scale.map((z) => (
                <div key={z} className="group flex flex-1 flex-col items-center justify-end gap-1.5">
                  <span className="font-mono text-[9px] text-fg-4 opacity-0 transition-opacity group-hover:opacity-100">{z}</span>
                  <motion.div initial={{ height: 0 }} whileInView={{ height: `${Math.max(6, (z / Math.max(...t.scale)) * 100)}%` }} viewport={{ once: true }}
                    className="w-full rounded-t-md bg-[linear-gradient(180deg,var(--brand),var(--purple))]" />
                </div>
              ))}
            </div>
            <div className="mt-3 font-mono text-[11px] text-fg-3">{t.scale.join(" · ")} pt</div>
            <div className="mt-5 grid grid-cols-2 gap-3 text-[12px]">
              <div className="rounded-xl bg-[color-mix(in_srgb,var(--text)_5%,transparent)] p-3">
                <div className="text-fg-3">Поля слева/справа</div>
                <div className="mt-0.5 font-mono font-semibold">{(t.margins.x / 914400).toFixed(2)}″</div>
              </div>
              <div className="rounded-xl bg-[color-mix(in_srgb,var(--text)_5%,transparent)] p-3">
                <div className="text-fg-3">Шаг сетки</div>
                <div className="mt-0.5 font-mono font-semibold">{(t.gap / 914400).toFixed(2)}″</div>
              </div>
            </div>
          </Panel>
        </div>
      </section>

      {/* ------------------------------------------ нарратив */}
      <section className="mt-14">
        <SectionHead eyebrow="Повествование" title={<span className="inline-flex items-center gap-2"><Icon24NarrativeOutline className="text-accent" /> Формат рассказа</span>} />
        <Panel className="p-5">
          <div className="flex flex-wrap gap-2">
            <Badge tone={n.has_agenda ? "ok" : "neutral"}>{n.has_agenda ? "есть слайд-план" : "без плана"}</Badge>
            <Badge tone={n.has_sections ? "ok" : "neutral"}>{n.has_sections ? "разделители блоков" : "без разделителей"}</Badge>
            <Badge tone={n.uses_kicker ? "ok" : "neutral"}>{n.uses_kicker ? `кикеры: «${n.kicker_example}»` : "без кикеров"}</Badge>
            <Badge tone={n.title_caps ? "purple" : "neutral"}>{n.title_caps ? "ЗАГОЛОВКИ КАПСОМ" : "заголовки строчными"}</Badge>
            <Badge>финал: {n.closing === "summary" ? "итоги" : n.closing === "thanks" ? "благодарность" : "нет"}</Badge>
            <Badge>≈ {n.avg_title_words} слов в заголовке</Badge>
            {n.numbering && <Badge tone="accent">нумерация 01 · 02 · 03</Badge>}
          </div>
          {n.tone && <p className="mt-4 text-[14px] leading-relaxed text-fg-2">{n.tone}</p>}
          <div className="mt-5">
            <div className="mb-2 text-[12px] text-fg-3">Последовательность слайдов в образце</div>
            <div className="flex flex-wrap gap-1">
              {n.sequence.map((k, i) => (
                <span key={i} title={CANVAS_KIND[k] ?? k} className="h-7 w-5 rounded-md" style={{ background: KIND_COLOR[k] ?? "var(--text-4)", opacity: k === "content" ? 0.45 : 1 }} />
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-fg-3">
              {Object.entries(KIND_COLOR).map(([k, c]) => (
                <span key={k} className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: c }} />{CANVAS_KIND[k]}</span>
              ))}
            </div>
          </div>
        </Panel>
      </section>

      {/* ------------------------------------------ холсты */}
      <section className="mt-14">
        <SectionHead eyebrow="Композиция" title="Холсты-основы"
          action={<Segmented size="sm" value={canvF} onChange={setCanvF} options={[{ value: "all", label: "Все" }, { value: "content", label: "Контент" }, { value: "struct", label: "Структурные" }]} />} />
        <p className="-mt-2 mb-4 text-[13px] text-fg-3">Слайды шаблона без контента: фон, логотипы, заголовок и колонтитулы остаются, в пунктирную область ложится сгенерированный контент. Наведите курсор.</p>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {canv.map((c) => <CanvasCard key={c.id} c={c} t={t} />)}
        </div>
      </section>

      {/* ------------------------------------------ исходные слайды */}
      <section className="mt-14">
        <SectionHead eyebrow="Разбор" title="Слайды образца" />
        <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
          {t.slides.map((s) => (
            <div key={s.index} title={s.service ? `служебный: ${s.service_reason}` : `${CANVAS_KIND[s.kind] ?? s.kind} · ${s.layout}`}
              className={clsx("relative overflow-hidden rounded-xl ring-1 ring-[var(--line)]", s.service && "opacity-40 grayscale")}>
              <img src={withW(s.preview, 320)} alt="" loading="lazy" className="block w-full" style={{ aspectRatio: `${t.slide_w}/${t.slide_h}`, objectFit: "cover" }} />
              <span className="absolute left-1 top-1 rounded bg-black/60 px-1 font-mono text-[9px] text-white">{s.index}</span>
              {s.service && <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1 text-[9px] text-white">служебный</span>}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

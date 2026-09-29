import { Icon20CheckCircleOn } from "@vkontakte/icons";
import { clsx } from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { url, type Job, type JobEvent } from "../lib/api";
import { clock, INTENTS } from "../lib/format";
import { Badge, LiveDot, Panel, Spinner } from "./ui";

const STAGES = [
  { key: "plan", label: "Сценарий колоды", sub: "структура, заголовки и тексты по брифу" },
  { key: "images", label: "Иллюстрации", sub: "генерация картинок для слайдов", optional: true },
  { key: "compose", label: "Вёрстка трёх вариантов", sub: "раскладка по сетке и стилю шаблона" },
  { key: "build", label: "Сборка и рендер", sub: "редактируемый PPTX и превью" },
  { key: "audit", label: "Аудит", sub: "проверка каждого слайда" },
  { key: "export", label: "Экспорт", sub: "PPTX · PDF · HTML" },
];

function Ring({ elapsed, progress, budget }: { elapsed: number; progress: number; budget: number }) {
  const R = 92;
  const C = 2 * Math.PI * R;
  const r2 = 76;
  const C2 = 2 * Math.PI * r2;
  const t = Math.min(1, elapsed / budget);
  return (
    <div className="relative mx-auto size-[230px]">
      <div className="absolute inset-6 rounded-full bg-[radial-gradient(circle,color-mix(in_srgb,var(--brand)_28%,transparent),transparent_70%)] blur-xl" />
      <svg viewBox="0 0 220 220" className="relative -rotate-90">
        <defs>
          <linearGradient id="ring-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#0077FF" />
            <stop offset=".55" stopColor="#735CE6" />
            <stop offset="1" stopColor="#E03FAB" />
          </linearGradient>
        </defs>
        <circle cx="110" cy="110" r={R} fill="none" stroke="var(--line-2)" strokeWidth="10" opacity=".6" />
        <motion.circle cx="110" cy="110" r={R} fill="none" stroke="url(#ring-g)" strokeWidth="10" strokeLinecap="round"
          strokeDasharray={C} initial={false} animate={{ strokeDashoffset: C * (1 - progress) }} transition={{ type: "spring", stiffness: 60, damping: 18 }} />
        <circle cx="110" cy="110" r={r2} fill="none" stroke="var(--line)" strokeWidth="3" />
        <circle cx="110" cy="110" r={r2} fill="none" stroke="var(--text-4)" strokeWidth="3" strokeLinecap="round"
          strokeDasharray={C2} strokeDashoffset={C2 * (1 - t)} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="font-display text-[46px] font-semibold tabular-nums leading-none">{clock(elapsed)}</div>
        <div className="mt-2 font-mono text-[12px] text-fg-3">из {clock(budget)} · {Math.round(progress * 100)}%</div>
      </div>
    </div>
  );
}

export function GenerationView({ job, events, budget }: { job: Job; events: JobEvent[]; budget: number }) {
  const last = events[events.length - 1];
  const [base, setBase] = useState({ t: last?.t ?? 0, at: Date.now() });
  const [, force] = useState(0);
  useEffect(() => setBase({ t: last?.t ?? 0, at: Date.now() }), [last?.t]);
  useEffect(() => {
    const id = setInterval(() => force((x) => x + 1), 250);
    return () => clearInterval(id);
  }, []);
  const elapsed = job.status === "running" || job.status === "queued" ? base.t + (Date.now() - base.at) / 1000 : last?.t ?? 0;

  const stageIdx = Math.max(0, STAGES.findIndex((s) => s.key === job.stage));
  const hadImages = events.some((e) => e.stage === "images");
  const story = useMemo(() => [...events].reverse().find((e) => e.slides?.length)?.slides ?? [], [events]);
  const built = new Set(events.filter((e) => e.variant && e.stage === "build").map((e) => e.variant!));
  const audited = new Set(events.filter((e) => e.variant && e.stage === "audit").map((e) => e.variant!));

  return (
    <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
      <div className="space-y-6">
        <Panel className="p-6">
          <Ring elapsed={elapsed} progress={job.progress} budget={budget} />
          <div className="mt-6 space-y-1">
            {STAGES.map((s, k) => {
              const skipped = s.optional && !hadImages && stageIdx > k;
              const done = job.status === "done" || k < stageIdx;
              const active = k === stageIdx && job.status === "running";
              if (skipped) return null;
              return (
                <div key={s.key} className={clsx("flex items-start gap-3 rounded-2xl px-3 py-2.5 transition-colors", active && "bg-[color-mix(in_srgb,var(--accent)_10%,transparent)]")}>
                  <div className="mt-0.5 grid size-6 shrink-0 place-items-center">
                    {done ? (
                      <motion.span initial={{ scale: 0.4 }} animate={{ scale: 1 }} className="text-ok"><Icon20CheckCircleOn /></motion.span>
                    ) : active ? (
                      <span className="text-accent"><Spinner size={18} /></span>
                    ) : (
                      <span className="size-4 rounded-full border-2 border-line-2" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className={clsx("text-[14px] font-semibold", !done && !active && "text-fg-3")}>{s.label}</div>
                    <div className="text-[12px] text-fg-3">{active && last?.message ? last.message : s.sub}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel className="p-5">
          <div className="mb-3 flex items-center gap-2 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-4">
            <LiveDot color="var(--accent)" /> Журнал
          </div>
          <div className="max-h-56 space-y-1.5 overflow-y-auto scroll-thin font-mono text-[12px]">
            {[...events].reverse().map((e, k) => (
              <div key={`${e.t}-${k}`} className="flex gap-3 text-fg-2">
                <span className="w-12 shrink-0 text-right text-fg-4">{e.t.toFixed(1)}с</span>
                <span className="min-w-0">{e.message}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="min-w-0 space-y-6">
        <Panel className="p-5 sm:p-6">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <div className="text-[15px] font-semibold">Сценарий колоды</div>
              <div className="text-[12px] text-fg-3">{story.length ? `${story.length} слайдов — структура и заголовки-выводы` : "Модель пишет структуру…"}</div>
            </div>
            {story.length > 0 && <Badge tone="ok" dot>готов</Badge>}
          </div>
          {story.length === 0 ? (
            <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 9 }).map((_, k) => <div key={k} className="skeleton h-[74px] rounded-2xl" style={{ animationDelay: `${k * 90}ms` }} />)}
            </div>
          ) : (
            <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
              <AnimatePresence>
                {story.map((s, k) => (
                  <motion.div key={s.id} initial={{ opacity: 0, y: 12, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={{ delay: k * 0.05, type: "spring", stiffness: 300, damping: 26 }}
                    className="flex gap-3 rounded-2xl border border-line bg-[color-mix(in_srgb,var(--surface)_70%,transparent)] p-3">
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-[color-mix(in_srgb,var(--accent)_12%,transparent)] font-mono text-[12px] font-semibold text-accent">{k + 1}</span>
                    <div className="min-w-0">
                      <div className="text-[11px] font-semibold uppercase tracking-wide text-fg-4">{INTENTS[s.intent] ?? s.intent}</div>
                      <div className="line-clamp-2 text-[13px] font-medium leading-snug">{s.title}</div>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </Panel>

        <div className="grid gap-4 md:grid-cols-3">
          {(job.variants.length ? job.variants : [{ id: "A", name: "Классический" }, { id: "B", name: "Визуальный" }, { id: "C", name: "Компактный" }] as { id: string; name: string; n_slides?: number }[]).map((v) => {
            const isBuilt = built.has(v.id) || job.status === "done";
            const isAudited = audited.has(v.id) || job.status === "done";
            return (
              <Panel key={v.id} className="overflow-hidden">
                <div className={clsx("relative bg-surface-2", !isBuilt && "scan-wrap")} style={{ aspectRatio: "16/9" }}>
                  {isBuilt ? (
                    <motion.img initial={{ opacity: 0 }} animate={{ opacity: 1 }} src={url(`/api/jobs/${job.id}/variants/${v.id}/slide/1.png?w=640`)}
                      alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="grid h-full place-items-center">
                      <div className="font-display text-[48px] font-semibold text-fg-4 opacity-40">{v.id}</div>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-3 p-4">
                  <span className="grid size-9 place-items-center rounded-xl bg-[color-mix(in_srgb,var(--purple)_15%,transparent)] font-display text-sm font-semibold text-purple">{v.id}</span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[14px] font-semibold">{v.name}</div>
                    <div className="text-[12px] text-fg-3">
                      {isAudited ? "аудит пройден" : isBuilt ? "аудит…" : job.variants.length ? "вёрстка…" : "в очереди"}
                    </div>
                  </div>
                  {isAudited ? <span className="text-ok"><Icon20CheckCircleOn /></span> : <Spinner size={16} className="text-fg-4" />}
                </div>
              </Panel>
            );
          })}
        </div>
      </div>
    </div>
  );
}

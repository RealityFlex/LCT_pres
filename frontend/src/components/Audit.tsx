import {
  Icon20CheckBoxOff,
  Icon20CheckBoxOn,
  Icon24CheckShieldOutline,
  Icon24MagicWandOutline,
  Icon24RobotOutline,
  Icon24ScanViewfinderOutline,
} from "@vkontakte/icons";
import { clsx } from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import type { AuditReport } from "../lib/api";
import { CATEGORY, SEVERITY } from "../lib/format";
import { Badge, Button, Segmented } from "./ui";

type Kind = "all" | "det" | "vlm";

export function AuditSummary({ report }: { report: AuditReport | null }) {
  const is = report?.issues ?? [];
  const e = is.filter((i) => i.severity === "error").length;
  const w = is.filter((i) => i.severity === "warning").length;
  const inf = is.filter((i) => i.severity === "info").length;
  const det = is.filter((i) => i.deterministic).length;
  const total = Math.max(1, is.length);
  const R = 30;
  const C = 2 * Math.PI * R;
  const segs = [
    { v: e, c: "var(--red)" },
    { v: w, c: "var(--orange)" },
    { v: inf, c: "var(--accent)" },
  ];
  let off = 0;
  return (
    <div className="flex items-center gap-4">
      <svg width="76" height="76" viewBox="0 0 76 76" className="-rotate-90 shrink-0">
        <circle cx="38" cy="38" r={R} fill="none" stroke="var(--line-2)" strokeWidth="8" />
        {is.length === 0 ? (
          <circle cx="38" cy="38" r={R} fill="none" stroke="var(--green)" strokeWidth="8" />
        ) : (
          segs.map((s, k) => {
            const len = (s.v / total) * C;
            const el = (
              <circle key={k} cx="38" cy="38" r={R} fill="none" stroke={s.c} strokeWidth="8"
                strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-off} strokeLinecap="butt" />
            );
            off += len;
            return el;
          })
        )}
      </svg>
      <div className="min-w-0">
        <div className="font-display text-[26px] font-semibold leading-none">{is.length}</div>
        <div className="mt-1 text-[12px] text-fg-3">замечаний · {det} детерм. · {is.length - det} VLM</div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Badge tone="bad" dot>{e}</Badge>
          <Badge tone="warn" dot>{w}</Badge>
          <Badge tone="accent" dot>{inf}</Badge>
        </div>
      </div>
    </div>
  );
}

export function AuditPanel({ report, onGoto, onHover, onFix, fixing, className }: {
  report: AuditReport | null;
  onGoto: (slide: number) => void;
  onHover: (id: string | null) => void;
  onFix: (ids: string[]) => void;
  fixing: boolean;
  className?: string;
}) {
  const [kind, setKind] = useState<Kind>("all");
  const [sev, setSev] = useState<string | null>(null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const issues = report?.issues ?? [];

  const shown = useMemo(() => issues.filter((i) =>
    (kind === "all" || (kind === "det" ? i.deterministic : !i.deterministic)) && (!sev || i.severity === sev),
  ).sort((a, b) => (a.slide || 999) - (b.slide || 999) || ["error", "warning", "info"].indexOf(a.severity) - ["error", "warning", "info"].indexOf(b.severity)),
  [issues, kind, sev]);
  const fixable = shown.filter((i) => i.fixable);
  const toggle = (id: string) => setSel((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  let lastSlide = -1;
  return (
    <div className={clsx("glass flex min-h-0 flex-col rounded-[22px]", className)}>
      <div className="border-b border-line p-5">
        <div className="mb-4 flex items-center gap-2">
          <Icon24CheckShieldOutline className="text-accent" />
          <div className="flex-1 text-[15px] font-semibold">Аудит слайдов</div>
          {report && <span className="font-mono text-[11px] text-fg-4">{report.checks_run.length} проверок · {report.seconds} с</span>}
        </div>
        <AuditSummary report={report} />
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Segmented<Kind> size="sm" value={kind} onChange={setKind} options={[
            { value: "all", label: "Все" },
            { value: "det", label: "Детерм.", icon: <Icon24ScanViewfinderOutline width={14} height={14} /> },
            { value: "vlm", label: "VLM", icon: <Icon24RobotOutline width={14} height={14} /> },
          ]} />
          {(["error", "warning", "info"] as const).map((s) => (
            <button key={s} className="chip !h-7 !px-2.5 !text-[12px]" data-on={sev === s} onClick={() => setSev(sev === s ? null : s)}>
              <span className="size-2 rounded-full" style={{ background: SEVERITY[s].color }} />{SEVERITY[s].label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin p-3">
        {shown.length === 0 && (
          <div className="px-4 py-10 text-center">
            <div className="mx-auto mb-3 grid size-12 place-items-center rounded-2xl bg-[color-mix(in_srgb,var(--green)_14%,transparent)] text-ok">
              <Icon24CheckShieldOutline />
            </div>
            <div className="text-[14px] font-semibold">{issues.length ? "По фильтру ничего нет" : "Замечаний нет"}</div>
            <div className="mt-1 text-[12px] text-fg-3">Все проверки пройдены</div>
          </div>
        )}
        <AnimatePresence initial={false}>
          {shown.map((i) => {
            const head = i.slide !== lastSlide;
            lastSlide = i.slide;
            const on = sel.has(i.id);
            return (
              <motion.div key={i.id} layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, height: 0 }}>
                {head && (
                  <button onClick={() => i.slide && onGoto(i.slide)}
                    className="mb-1 mt-3 flex w-full items-center gap-2 px-2 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-4 hover:text-accent first:mt-0">
                    {i.slide ? `Слайд ${i.slide}` : "Вся колода"}
                    <span className="h-px flex-1 bg-line" />
                  </button>
                )}
                <div
                  onMouseEnter={() => onHover(i.id)}
                  onMouseLeave={() => onHover(null)}
                  onClick={() => i.slide && onGoto(i.slide)}
                  className={clsx("group flex cursor-pointer gap-3 rounded-2xl p-3 transition-colors",
                    on ? "bg-[color-mix(in_srgb,var(--accent)_10%,transparent)]" : "hover:bg-[color-mix(in_srgb,var(--text)_5%,transparent)]")}
                >
                  <button
                    onClick={(e) => { e.stopPropagation(); if (i.fixable) toggle(i.id); }}
                    disabled={!i.fixable}
                    title={i.fixable ? "Выбрать для исправления" : "Автоисправление недоступно"}
                    className={clsx("mt-0.5 shrink-0", i.fixable ? (on ? "text-accent" : "text-fg-4 hover:text-fg-2") : "text-fg-4 opacity-30")}
                  >
                    {on ? <Icon20CheckBoxOn /> : <Icon20CheckBoxOff />}
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2">
                      <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: SEVERITY[i.severity]?.color }} />
                      <div className="min-w-0 flex-1 text-[13px] font-semibold leading-snug">{i.title}</div>
                    </div>
                    <div className="mt-1 line-clamp-3 pl-4 text-[12px] leading-relaxed text-fg-3">{i.message}</div>
                    <div className="mt-2 flex flex-wrap gap-1 pl-4">
                      <Badge className="!h-5 !text-[10px]" tone={i.deterministic ? "accent" : "purple"}>{i.deterministic ? "детерминированная" : "VLM"}</Badge>
                      <Badge className="!h-5 !text-[10px]">{CATEGORY[i.category] ?? i.category}</Badge>
                      {i.fixable && <Badge className="!h-5 !text-[10px]" tone="ok">исправимо</Badge>}
                    </div>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      <div className="border-t border-line p-4">
        <div className="mb-3 flex items-center justify-between text-[12px] text-fg-3">
          <span>Выбрано: <b className="text-fg">{sel.size}</b></span>
          <button className="font-semibold text-accent hover:underline disabled:opacity-40" disabled={!fixable.length}
            onClick={() => setSel(sel.size ? new Set() : new Set(fixable.map((i) => i.id)))}>
            {sel.size ? "Снять выбор" : `Выбрать исправимые (${fixable.length})`}
          </button>
        </div>
        <Button variant="primary" className="w-full" glow loading={fixing} disabled={!sel.size}
          onClick={() => { onFix([...sel]); setSel(new Set()); }} icon={<Icon24MagicWandOutline width={20} height={20} />}>
          Исправить выбранные
        </Button>
      </div>
    </div>
  );
}

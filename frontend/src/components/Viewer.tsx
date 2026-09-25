import { Icon24Cancel, Icon24ChevronLeft, Icon24ChevronRight, Icon24Fullscreen, Icon24HideOutline, Icon24ViewOutline } from "@vkontakte/icons";
import { clsx } from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { url, type Issue, type SlideItem } from "../lib/api";
import { RECIPES, SEVERITY } from "../lib/format";
import { Badge, Button, Kbd } from "./ui";

export function SlideViewer({
  slides, index, onIndex, issues, showIssues, onToggleIssues, hoverIssue, slideW, slideH, busy, onPresent,
}: {
  slides: SlideItem[];
  index: number;
  onIndex: (i: number) => void;
  issues: Issue[];
  showIssues: boolean;
  onToggleIssues: () => void;
  hoverIssue: string | null;
  slideW: number;
  slideH: number;
  busy?: boolean;
  onPresent: () => void;
}) {
  const s = slides[index - 1];
  const here = issues.filter((i) => i.slide === index && i.bbox);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [notes, setNotes] = useState(false);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") onIndex(Math.min(slides.length, index + 1));
      if (e.key === "ArrowLeft" || e.key === "PageUp") onIndex(Math.max(1, index - 1));
      if (e.key.toLowerCase() === "f" && !e.ctrlKey && !e.metaKey) onPresent();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [index, slides.length, onIndex, onPresent]);

  if (!s) return null;
  const src = url(s.image);
  return (
    <div className="min-w-0">
      <div className={clsx("group relative overflow-hidden rounded-[18px] bg-black shadow-[var(--shadow-2)] ring-1 ring-[var(--line)]", busy && "scan-wrap")}
        style={{ aspectRatio: `${slideW} / ${slideH}` }}>
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.img
            key={src}
            src={src}
            alt={s.title}
            onLoad={() => setLoaded(src)}
            initial={{ opacity: 0, scale: 1.01 }}
            animate={{ opacity: loaded === src ? 1 : 0.35, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.28 }}
            className="absolute inset-0 h-full w-full object-contain"
          />
        </AnimatePresence>
        {showIssues && here.map((iss, k) => {
          const [x, y, w, h] = iss.bbox!;
          const c = SEVERITY[iss.severity]?.color ?? "var(--accent)";
          const hot = hoverIssue === iss.id;
          return (
            <motion.div key={iss.id} initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: k * 0.04 }}
              className="pointer-events-none absolute rounded-md"
              style={{
                left: `${(x / slideW) * 100}%`, top: `${(y / slideH) * 100}%`,
                width: `${Math.max(1.2, (w / slideW) * 100)}%`, height: `${Math.max(2, (h / slideH) * 100)}%`,
                border: `2px solid ${c}`,
                background: hot ? `color-mix(in srgb, ${c} 22%, transparent)` : `color-mix(in srgb, ${c} 8%, transparent)`,
                boxShadow: hot ? `0 0 0 4px color-mix(in srgb, ${c} 30%, transparent)` : undefined,
              }}>
              <span className="absolute -left-[2px] -top-[22px] rounded-md px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white" style={{ background: c }}>
                {k + 1}
              </span>
            </motion.div>
          );
        })}
        <button onClick={() => onIndex(Math.max(1, index - 1))} disabled={index <= 1}
          className="absolute left-3 top-1/2 grid size-11 -translate-y-1/2 place-items-center rounded-full bg-black/45 text-white opacity-0 backdrop-blur transition-opacity group-hover:opacity-100 disabled:!opacity-0" aria-label="Назад">
          <Icon24ChevronLeft />
        </button>
        <button onClick={() => onIndex(Math.min(slides.length, index + 1))} disabled={index >= slides.length}
          className="absolute right-3 top-1/2 grid size-11 -translate-y-1/2 place-items-center rounded-full bg-black/45 text-white opacity-0 backdrop-blur transition-opacity group-hover:opacity-100 disabled:!opacity-0" aria-label="Вперёд">
          <Icon24ChevronRight />
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" onClick={() => onIndex(Math.max(1, index - 1))} disabled={index <= 1} icon={<Icon24ChevronLeft width={18} height={18} />} aria-label="Назад" />
          <span className="min-w-[76px] text-center font-mono text-[13px] font-semibold">{index} / {slides.length}</span>
          <Button size="sm" variant="ghost" onClick={() => onIndex(Math.min(slides.length, index + 1))} disabled={index >= slides.length} icon={<Icon24ChevronRight width={18} height={18} />} aria-label="Вперёд" />
        </div>
        <Badge tone="purple">{RECIPES[s.recipe] ?? s.recipe}</Badge>
        <Badge className="font-mono">холст {s.canvas}</Badge>
        <div className="flex-1" />
        <Button size="sm" variant={showIssues ? "soft" : "ghost"} onClick={onToggleIssues}
          icon={showIssues ? <Icon24ViewOutline width={18} height={18} /> : <Icon24HideOutline width={18} height={18} />}>
          <span className="hidden sm:inline">Замечания на слайде</span>
        </Button>
        {s.notes && (
          <Button size="sm" variant={notes ? "soft" : "ghost"} onClick={() => setNotes((v) => !v)}>Заметки</Button>
        )}
        <Button size="sm" variant="ghost" onClick={onPresent} icon={<Icon24Fullscreen width={18} height={18} />}>
          <span className="hidden sm:inline">Показ</span> <span className="hidden md:inline"><Kbd>F</Kbd></span>
        </Button>
      </div>
      <AnimatePresence>
        {notes && s.notes && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mt-3 rounded-2xl border border-line bg-[color-mix(in_srgb,var(--surface)_60%,transparent)] p-4 text-[14px] leading-relaxed text-fg-2">
              <div className="mb-1 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-4">Заметки спикера</div>
              {s.notes}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function Filmstrip({ slides, index, onIndex, issues, vertical, rev }: {
  slides: SlideItem[];
  index: number;
  onIndex: (i: number) => void;
  issues: Issue[];
  vertical?: boolean;
  rev?: number;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = box.current?.querySelector<HTMLElement>(`[data-i="${index}"]`);
    el?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [index]);
  return (
    <div ref={box} className={clsx("scroll-thin", vertical ? "flex max-h-[calc(100vh-220px)] flex-col gap-2.5 overflow-y-auto pr-1" : "flex gap-2.5 overflow-x-auto pb-2")}>
      {slides.map((s) => {
        const errs = issues.filter((i) => i.slide === s.index && i.severity === "error").length;
        const warns = issues.filter((i) => i.slide === s.index && i.severity !== "error").length;
        const on = s.index === index;
        return (
          <button key={`${s.index}-${rev}`} data-i={s.index} onClick={() => onIndex(s.index)}
            className={clsx("group relative shrink-0 overflow-hidden rounded-xl transition-all", vertical ? "w-full" : "w-40",
              on ? "ring-2 ring-accent ring-offset-2 ring-offset-[var(--bg)]" : "opacity-75 ring-1 ring-[var(--line)] hover:opacity-100")}>
            <img src={url(s.thumb)} alt="" loading="lazy" className="block w-full bg-surface-2" style={{ aspectRatio: "16/9", objectFit: "cover" }} />
            <span className="absolute left-1.5 top-1.5 rounded-md bg-black/60 px-1.5 font-mono text-[10px] font-semibold text-white">{s.index}</span>
            {(errs > 0 || warns > 0) && (
              <span className="absolute right-1.5 top-1.5 flex gap-0.5">
                {errs > 0 && <span className="size-2 rounded-full bg-bad ring-2 ring-black/40" />}
                {warns > 0 && <span className="size-2 rounded-full bg-orange ring-2 ring-black/40" />}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function PresentMode({ open, slides, start, onClose }: { open: boolean; slides: SlideItem[]; start: number; onClose: (at: number) => void }) {
  const [i, setIState] = useState(start);
  const iRef = useRef(start);
  const setI = (f: number | ((v: number) => number)) =>
    setIState((v) => {
      const n = typeof f === "function" ? f(v) : f;
      iRef.current = n;
      return n;
    });
  const root = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    setI(start);
    root.current?.requestFullscreen?.().catch(() => undefined);
    const on = (e: KeyboardEvent) => {
      if (["ArrowRight", "PageDown", " ", "Enter"].includes(e.key)) { e.preventDefault(); setI((v) => Math.min(slides.length, v + 1)); }
      if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); setI((v) => Math.max(1, v - 1)); }
      if (e.key === "Escape") close();
    };
    const onFs = () => { if (!document.fullscreenElement) onClose(iRef.current); };
    window.addEventListener("keydown", on);
    document.addEventListener("fullscreenchange", onFs);
    return () => { window.removeEventListener("keydown", on); document.removeEventListener("fullscreenchange", onFs); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const close = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    onClose(iRef.current);
  };
  if (!open) return null;
  const s = slides[i - 1];
  return createPortal(
    <div ref={root} className="fixed inset-0 z-[95] flex items-center justify-center bg-black" onClick={() => setI((v) => Math.min(slides.length, v + 1))}>
      <AnimatePresence mode="wait">
        <motion.img key={i} src={url(s.image)} alt={s.title} className="max-h-full max-w-full object-contain"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }} />
      </AnimatePresence>
      <div className="absolute right-4 top-4 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <span className="rounded-full bg-white/10 px-3 py-1.5 font-mono text-[13px] text-white/80 backdrop-blur">{i} / {slides.length}</span>
        <button className="grid size-10 place-items-center rounded-full bg-white/10 text-white backdrop-blur hover:bg-white/20" onClick={close} aria-label="Выйти">
          <Icon24Cancel />
        </button>
      </div>
      <div className="absolute inset-x-0 bottom-0 h-1 bg-white/10">
        <div className="h-full bg-[linear-gradient(90deg,#0077FF,#735CE6,#E03FAB)] transition-all duration-300" style={{ width: `${(i / slides.length) * 100}%` }} />
      </div>
    </div>,
    document.body,
  );
}

import { useQuery } from "@tanstack/react-query";
import {
  Icon24AddCircleOutline,
  Icon24ArticlesOutline,
  Icon24DocumentOutline,
  Icon24GearOutline,
  Icon24HomeOutline,
  Icon24PaletteOutline,
  Icon24SearchOutline,
  Icon24SunOutline,
} from "@vkontakte/icons";
import { clsx } from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useTheme } from "../lib/theme";
import { Kbd } from "./ui";

type Item = { id: string; group: string; label: string; hint?: string; icon: ReactNode; run: () => void };

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate();
  const { cycle } = useTheme();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement | null>(null);
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, enabled: open });
  const tpls = useQuery({ queryKey: ["templates"], queryFn: api.templates, enabled: open });

  const go = (to: string) => () => {
    nav(to);
    onClose();
  };
  const items: Item[] = useMemo(() => {
    const base: Item[] = [
      { id: "new", group: "Действия", label: "Новая презентация", hint: "бриф → 3 варианта", icon: <Icon24AddCircleOutline />, run: go("/new") },
      { id: "tpl-up", group: "Действия", label: "Загрузить шаблон", icon: <Icon24PaletteOutline />, run: go("/templates?upload=1") },
      { id: "theme", group: "Действия", label: "Сменить тему", hint: "авто · тёмная · светлая", icon: <Icon24SunOutline />, run: () => { cycle(); } },
      { id: "home", group: "Разделы", label: "Главная", icon: <Icon24HomeOutline />, run: go("/") },
      { id: "projects", group: "Разделы", label: "Проекты", icon: <Icon24ArticlesOutline />, run: go("/projects") },
      { id: "templates", group: "Разделы", label: "Шаблоны", icon: <Icon24PaletteOutline />, run: go("/templates") },
      { id: "system", group: "Разделы", label: "Система: модели, скиллы, аудит", icon: <Icon24GearOutline />, run: go("/system") },
    ];
    for (const j of (jobs.data ?? []).slice(0, 12)) {
      base.push({ id: `j-${j.id}`, group: "Проекты", label: j.title, hint: j.template_name, icon: <Icon24DocumentOutline />, run: go(`/project/${j.id}`) });
    }
    for (const t of tpls.data ?? []) {
      base.push({ id: `t-${t.id}`, group: "Шаблоны", label: t.name, hint: `${t.n_slides} слайдов`, icon: <Icon24PaletteOutline />, run: go(`/templates/${t.id}`) });
    }
    return base;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs.data, tpls.data]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? items.filter((x) => (x.label + " " + (x.hint ?? "")).toLowerCase().includes(s)) : items;
  }, [items, q]);

  useEffect(() => {
    if (open) {
      setQ("");
      setI(0);
      setTimeout(() => input.current?.focus(), 30);
    }
  }, [open]);
  useEffect(() => setI(0), [q]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setI((v) => Math.min(filtered.length - 1, v + 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setI((v) => Math.max(0, v - 1)); }
    if (e.key === "Enter") { e.preventDefault(); filtered[i]?.run(); }
    if (e.key === "Escape") onClose();
  };

  let lastGroup = "";
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[85] flex items-start justify-center px-4 pt-[12vh]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            className="glass-strong relative w-full max-w-xl overflow-hidden rounded-[22px]"
            initial={{ y: -12, scale: 0.98, opacity: 0 }}
            animate={{ y: 0, scale: 1, opacity: 1 }}
            exit={{ y: -8, scale: 0.98, opacity: 0 }}
            transition={{ type: "spring", stiffness: 460, damping: 36 }}
            onKeyDown={onKey}
          >
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Icon24SearchOutline className="text-fg-3" />
              <input
                ref={input}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Найти проект, шаблон или команду…"
                className="h-14 flex-1 bg-transparent text-[15px] outline-none placeholder:text-fg-4"
              />
              <Kbd>Esc</Kbd>
            </div>
            <div className="max-h-[52vh] overflow-auto scroll-thin p-2">
              {filtered.length === 0 && <div className="px-4 py-10 text-center text-sm text-fg-3">Ничего не найдено</div>}
              {filtered.map((x, k) => {
                const head = x.group !== lastGroup ? x.group : null;
                lastGroup = x.group;
                return (
                  <div key={x.id}>
                    {head && <div className="px-3 pb-1 pt-3 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-4">{head}</div>}
                    <button
                      onMouseEnter={() => setI(k)}
                      onClick={x.run}
                      className={clsx("flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                        k === i ? "bg-[color-mix(in_srgb,var(--accent)_14%,transparent)]" : "hover:bg-[color-mix(in_srgb,var(--text)_5%,transparent)]")}
                    >
                      <span className={clsx("shrink-0", k === i ? "text-accent" : "text-fg-3")}>{x.icon}</span>
                      <span className="min-w-0 flex-1 truncate text-[14px] font-medium">{x.label}</span>
                      {x.hint && <span className="truncate text-[12px] text-fg-3">{x.hint}</span>}
                    </button>
                  </div>
                );
              })}
            </div>
            <div className="flex items-center gap-4 border-t border-line px-4 py-2.5 text-[11px] text-fg-3">
              <span className="flex items-center gap-1.5"><Kbd>↑</Kbd><Kbd>↓</Kbd> выбор</span>
              <span className="flex items-center gap-1.5"><Kbd>Enter</Kbd> открыть</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

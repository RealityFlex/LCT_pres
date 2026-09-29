import { useQuery } from "@tanstack/react-query";
import {
  Icon20MoonOutline,
  Icon20SunOutline,
  Icon20MoonAutoOutline,
  Icon24AddCircleOutline,
  Icon24ArticlesOutline,
  Icon24HomeOutline,
  Icon24PaletteOutline,
  Icon24SearchOutline,
} from "@vkontakte/icons";
import { clsx } from "clsx";
import { motion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, withW } from "../lib/api";
import { inVK } from "../lib/bridge";
import { useTheme, type ThemeMode } from "../lib/theme";
import { CommandPalette } from "./CommandPalette";
import { Logo, LogoMark } from "./Logo";
import { Kbd, LiveDot, Segmented } from "./ui";

const NAV = [
  { to: "/", label: "Главная", icon: <Icon24HomeOutline />, end: true },
  { to: "/projects", label: "Проекты", icon: <Icon24ArticlesOutline /> },
  { to: "/templates", label: "Шаблоны", icon: <Icon24PaletteOutline /> },
];

export function Background() {
  return (
    <>
      <div className="aurora" aria-hidden>
        <span />
        <span />
        <span />
      </div>
      <div className="grid-bg" aria-hidden />
      <div className="noise" aria-hidden />
    </>
  );
}

function ThemeSwitch() {
  const { mode, setMode } = useTheme();
  return (
    <Segmented<ThemeMode>
      size="sm"
      value={mode}
      onChange={setMode}
      className="w-full justify-between"
      options={[
        { value: "auto", label: "Авто", icon: <Icon20MoonAutoOutline width={16} height={16} /> },
        { value: "light", label: "", icon: <Icon20SunOutline width={16} height={16} /> },
        { value: "dark", label: "", icon: <Icon20MoonOutline width={16} height={16} /> },
      ]}
    />
  );
}

function RecentMini() {
  const { data } = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 8000 });
  const items = (data ?? []).slice(0, 4);
  if (!items.length) return null;
  return (
    <div className="mt-6">
      <div className="mb-2 px-3 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-4">Недавние</div>
      <div className="space-y-0.5">
        {items.map((j) => (
          <NavLink
            key={j.id}
            to={`/project/${j.id}`}
            className={({ isActive }) =>
              clsx("group flex items-center gap-2.5 rounded-xl px-2.5 py-2 transition-colors hover:bg-[color-mix(in_srgb,var(--text)_6%,transparent)]",
                isActive && "bg-[color-mix(in_srgb,var(--text)_7%,transparent)]")
            }
          >
            <div className="h-7 w-11 shrink-0 overflow-hidden rounded-md bg-surface-2 ring-1 ring-[var(--line)]">
              {j.cover && <img src={withW(j.cover.replace(/\?w=\d+/, ""), 160)} alt="" className="h-full w-full object-cover" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-medium">{j.title}</div>
              <div className="truncate text-[11px] text-fg-3">
                {j.status === "running" || j.status === "queued" ? "генерируется…" : j.status === "error" ? "ошибка" : j.template_name}
              </div>
            </div>
            {(j.status === "running" || j.status === "queued") && <LiveDot color="var(--accent)" />}
          </NavLink>
        ))}
      </div>
    </div>
  );
}

function SideNav({ onSearch }: { onSearch: () => void }) {
  const nav = useNavigate();
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[256px] flex-col border-r border-line bg-[color-mix(in_srgb,var(--bg)_55%,transparent)] px-3 pb-4 pt-5 backdrop-blur-2xl lg:flex">
      <button className="mb-6 px-2 text-left" onClick={() => nav("/")} aria-label="На главную">
        <Logo />
      </button>
      <button onClick={() => nav("/new")} className="btn btn-primary btn-glow mb-3 w-full" style={{ height: 44 }}>
        <Icon24AddCircleOutline width={20} height={20} />
        Новая презентация
      </button>
      <button
        onClick={onSearch}
        className="mb-4 flex h-10 w-full items-center gap-2 rounded-xl border border-line bg-[color-mix(in_srgb,var(--surface)_50%,transparent)] px-3 text-[13px] text-fg-3 transition-colors hover:text-fg"
      >
        <Icon24SearchOutline width={18} height={18} />
        <span className="flex-1 text-left">Поиск и команды</span>
        <Kbd>Ctrl K</Kbd>
      </button>
      <nav className="space-y-0.5">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}
            className={({ isActive }) => clsx("relative flex h-11 items-center gap-3 rounded-xl px-3 text-[14px] font-medium transition-colors",
              isActive ? "text-fg" : "text-fg-2 hover:text-fg")}>
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-xl bg-[color-mix(in_srgb,var(--accent)_12%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--accent)_22%,transparent)]"
                    transition={{ type: "spring", stiffness: 500, damping: 40 }} />
                )}
                <span className={clsx("relative z-10", isActive && "text-accent")}>{n.icon}</span>
                <span className="relative z-10">{n.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="min-h-0 flex-1 overflow-auto no-scrollbar">
        <RecentMini />
      </div>
      <div className="space-y-3 pt-3">
        <ThemeSwitch />
      </div>
    </aside>
  );
}

function MobileBar({ onSearch }: { onSearch: () => void }) {
  const { cycle, mode } = useTheme();
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-[color-mix(in_srgb,var(--bg)_70%,transparent)] px-4 backdrop-blur-2xl lg:hidden">
      <NavLink to="/" className="flex items-center gap-2">
        <LogoMark size={28} />
        <span className="font-display text-[17px] font-semibold">Лекало</span>
      </NavLink>
      <div className="flex-1" />
      <button className="btn btn-ghost btn-sm btn-icon" onClick={onSearch} aria-label="Поиск">
        <Icon24SearchOutline width={20} height={20} />
      </button>
      <button className="btn btn-ghost btn-sm btn-icon" onClick={cycle} aria-label="Тема">
        {mode === "light" ? <Icon20SunOutline /> : mode === "dark" ? <Icon20MoonOutline /> : <Icon20MoonAutoOutline />}
      </button>
    </header>
  );
}

function BottomNav() {
  const items: { to: string; label: string; icon: ReactNode; end?: boolean; main?: boolean }[] = [
    { to: "/", label: "Главная", icon: <Icon24HomeOutline />, end: true },
    { to: "/templates", label: "Шаблоны", icon: <Icon24PaletteOutline /> },
    { to: "/new", label: "Создать", icon: <Icon24AddCircleOutline />, main: true },
    { to: "/projects", label: "Проекты", icon: <Icon24ArticlesOutline /> },
  ];
  return (
    <nav className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-line bg-[color-mix(in_srgb,var(--bg)_78%,transparent)] px-2 pt-1.5 backdrop-blur-2xl lg:hidden">
      <div className="mx-auto grid max-w-lg grid-cols-4">
        {items.map((it) => (
          <NavLink key={it.to} to={it.to} end={it.end}
            className={({ isActive }) => clsx("flex flex-col items-center gap-0.5 rounded-xl py-1 text-[10px] font-medium",
              isActive ? "text-accent" : "text-fg-3")}>
            {it.main ? (
              <span className="-mt-5 grid size-12 place-items-center rounded-2xl bg-brand text-white shadow-[0_10px_30px_-8px_var(--brand)]">{it.icon}</span>
            ) : (
              it.icon
            )}
            <span>{it.label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
}

export function AppShell() {
  const [palette, setPalette] = useState(false);
  const loc = useLocation();
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((v) => !v);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [loc.pathname]);
  return (
    <div className={clsx("relative min-h-full", inVK && "vk-embedded")}>
      <Background />
      <SideNav onSearch={() => setPalette(true)} />
      <MobileBar onSearch={() => setPalette(true)} />
      <main className="relative z-10 pb-24 lg:pb-10 lg:pl-[256px]">
        <Outlet />
      </main>
      <BottomNav />
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  );
}

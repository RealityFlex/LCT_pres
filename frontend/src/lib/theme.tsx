import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { initBridge } from "./bridge";

export type ThemeMode = "auto" | "light" | "dark";
type Ctx = { mode: ThemeMode; theme: "light" | "dark"; setMode: (m: ThemeMode) => void; cycle: () => void };

const ThemeCtx = createContext<Ctx | null>(null);
const KEY = "lekalo-theme";

function readMode(): ThemeMode {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "auto" ? v : "auto";
  } catch {
    return "auto";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readMode);
  const [system, setSystem] = useState<"light" | "dark">(() =>
    window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark",
  );
  const [vkScheme, setVkScheme] = useState<"light" | "dark" | null>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const on = () => setSystem(mq.matches ? "light" : "dark");
    mq.addEventListener("change", on);
    initBridge(setVkScheme);
    return () => mq.removeEventListener("change", on);
  }, []);

  const theme = mode === "auto" ? (vkScheme ?? system) : mode;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    meta?.setAttribute("content", theme === "dark" ? "#0A0A0A" : "#EBEDF0");
  }, [theme]);

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m);
    try {
      localStorage.setItem(KEY, m);
    } catch {
      /* приватный режим */
    }
  }, []);
  const cycle = useCallback(() => setMode(mode === "auto" ? "dark" : mode === "dark" ? "light" : "auto"), [mode, setMode]);

  const value = useMemo(() => ({ mode, theme, setMode, cycle }), [mode, theme, setMode, cycle]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export function useTheme(): Ctx {
  const c = useContext(ThemeCtx);
  if (!c) throw new Error("ThemeProvider missing");
  return c;
}

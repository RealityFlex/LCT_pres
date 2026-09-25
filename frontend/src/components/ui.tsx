import { clsx } from "clsx";
import { AnimatePresence, animate, motion, useInView } from "motion/react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Icon24Cancel, Icon24CheckCircleOn, Icon24ErrorCircleOutline, Icon24InfoCircleOutline } from "@vkontakte/icons";

// ------------------------------------------------------------------ кнопки
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "soft" | "ghost" | "outline" | "danger";
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  iconRight?: ReactNode;
  loading?: boolean;
  glow?: boolean;
};

export function Button({ variant = "outline", size = "md", icon, iconRight, loading, glow, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      className={clsx("btn", `btn-${variant}`, size !== "md" && `btn-${size}`, !children && "btn-icon", glow && "btn-glow", className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Spinner size={size === "lg" ? 20 : 16} /> : icon}
      {children}
      {iconRight}
    </button>
  );
}

export function Spinner({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg className={clsx("animate-spin", className)} width={size} height={size} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9.5" stroke="currentColor" strokeOpacity=".2" strokeWidth="3" />
      <path d="M21.5 12A9.5 9.5 0 0 0 12 2.5" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <span className="kbd">{children}</span>;
}

// ------------------------------------------------------------------ бейджи
export function Badge({ tone = "neutral", children, className, dot }: {
  tone?: "neutral" | "accent" | "ok" | "bad" | "warn" | "purple" | "lime";
  children: ReactNode;
  className?: string;
  dot?: boolean;
}) {
  const colors: Record<string, string> = {
    neutral: "text-fg-2 bg-[color-mix(in_srgb,var(--text)_7%,transparent)]",
    accent: "text-accent bg-[color-mix(in_srgb,var(--accent)_13%,transparent)]",
    ok: "text-ok bg-[color-mix(in_srgb,var(--green)_14%,transparent)]",
    bad: "text-bad bg-[color-mix(in_srgb,var(--red)_13%,transparent)]",
    warn: "text-orange bg-[color-mix(in_srgb,var(--orange)_15%,transparent)]",
    purple: "text-purple bg-[color-mix(in_srgb,var(--purple)_15%,transparent)]",
    lime: "text-[#3d5500] dark:text-lime bg-[color-mix(in_srgb,var(--lime)_28%,transparent)]",
  };
  return (
    <span className={clsx("badge", colors[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function LiveDot({ color = "var(--green)", className }: { color?: string; className?: string }) {
  return <span className={clsx("inline-block size-2 rounded-full animate-pulse-dot", className)} style={{ background: color, color }} />;
}

// ------------------------------------------------------------------ сегментированный переключатель
export function Segmented<T extends string>({ value, onChange, options, className, size = "md" }: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; icon?: ReactNode }[];
  className?: string;
  size?: "sm" | "md";
}) {
  const id = useId();
  return (
    <div className={clsx("seg", className)} role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          data-on={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(size === "sm" && "!h-7 !px-2.5 !text-xs")}
        >
          {o.value === value && (
            <motion.span
              layoutId={`seg-${id}`}
              className="absolute inset-0 rounded-[10px] bg-surface shadow-[var(--shadow-1)]"
              transition={{ type: "spring", stiffness: 500, damping: 38 }}
            />
          )}
          <span className="relative z-10 inline-flex items-center gap-1.5">
            {o.icon}
            {o.label}
          </span>
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ прожектор под курсором
export function useSpotlight<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const onMouseMove = useCallback((e: MouseEvent<T>) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  }, []);
  return { ref, onMouseMove };
}

export function Panel({ className, children, spotlight, ...rest }: HTMLAttributes<HTMLDivElement> & { spotlight?: boolean }) {
  const s = useSpotlight<HTMLDivElement>();
  return (
    <div
      ref={spotlight ? s.ref : undefined}
      onMouseMove={spotlight ? s.onMouseMove : undefined}
      className={clsx("glass rounded-[22px]", spotlight && "spotlight", className)}
      {...rest}
    >
      {children}
    </div>
  );
}

// ------------------------------------------------------------------ счётчик
export function CountUp({ to, decimals = 0, suffix = "", className }: { to: number; decimals?: number; suffix?: string; className?: string }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const inView = useInView(ref, { once: true });
  useEffect(() => {
    if (!inView || !ref.current) return;
    const ctrl = animate(0, to, {
      duration: 1.4,
      ease: [0.2, 0.8, 0.2, 1],
      onUpdate: (v) => {
        if (ref.current) ref.current.textContent = v.toFixed(decimals).replace(".", ",") + suffix;
      },
    });
    return () => ctrl.stop();
  }, [inView, to, decimals, suffix]);
  return (
    <span ref={ref} className={className}>
      0{suffix}
    </span>
  );
}

// ------------------------------------------------------------------ модальное окно и шторка
export function Modal({ open, onClose, children, className, wide }: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [open, onClose]);
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[80] flex items-end justify-center sm:items-center sm:p-6"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/55 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            role="dialog"
            aria-modal="true"
            className={clsx("glass-strong relative w-full max-h-[92vh] overflow-auto scroll-thin rounded-t-[26px] sm:rounded-[26px]",
              wide ? "sm:max-w-5xl" : "sm:max-w-lg", className)}
            initial={{ y: 40, opacity: 0, scale: 0.98 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 30, opacity: 0, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 34 }}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

export function ModalHeader({ title, subtitle, onClose }: { title: ReactNode; subtitle?: ReactNode; onClose: () => void }) {
  return (
    <div className="sticky top-0 z-10 flex items-start gap-4 border-b border-line bg-[var(--glass-2)] px-6 py-5 backdrop-blur-xl">
      <div className="min-w-0 flex-1">
        <div className="text-lg font-semibold">{title}</div>
        {subtitle && <div className="mt-1 text-sm text-fg-3">{subtitle}</div>}
      </div>
      <Button variant="ghost" size="sm" onClick={onClose} aria-label="Закрыть" icon={<Icon24Cancel width={20} height={20} />} />
    </div>
  );
}

// ------------------------------------------------------------------ тосты
type Toast = { id: number; tone: "ok" | "bad" | "info"; title: string; text?: string };
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs.slice(-3), { ...t, id }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[90] flex flex-col items-center gap-2 px-4 lg:bottom-6 lg:items-end lg:pr-6">
          <AnimatePresence>
            {items.map((t) => (
              <motion.div
                key={t.id}
                layout
                initial={{ opacity: 0, y: 16, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.96 }}
                className="glass-strong pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-2xl px-4 py-3"
              >
                <span className={clsx("mt-0.5", t.tone === "ok" ? "text-ok" : t.tone === "bad" ? "text-bad" : "text-accent")}>
                  {t.tone === "ok" ? <Icon24CheckCircleOn width={20} height={20} /> : t.tone === "bad" ? <Icon24ErrorCircleOutline width={20} height={20} /> : <Icon24InfoCircleOutline width={20} height={20} />}
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-semibold">{t.title}</div>
                  {t.text && <div className="mt-0.5 text-[13px] leading-snug text-fg-3">{t.text}</div>}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

// ------------------------------------------------------------------ прочее
export function Empty({ icon, title, text, action }: { icon: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 grid size-16 place-items-center rounded-2xl bg-[color-mix(in_srgb,var(--accent)_12%,transparent)] text-accent">{icon}</div>
      <div className="text-lg font-semibold">{title}</div>
      {text && <div className="mt-1.5 max-w-sm text-sm text-fg-3 text-pretty">{text}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function SectionHead({ eyebrow, title, action, className }: { eyebrow?: string; title: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={clsx("mb-5 flex items-end justify-between gap-4", className)}>
      <div>
        {eyebrow && <div className="mb-1.5 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">{eyebrow}</div>}
        <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h2>
      </div>
      {action}
    </div>
  );
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={clsx("h-1.5 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--text)_8%,transparent)]", className)}>
      <motion.div
        className="h-full rounded-full bg-[linear-gradient(90deg,var(--brand),var(--purple),var(--pink))]"
        initial={false}
        animate={{ width: `${Math.round(Math.max(0.02, Math.min(1, value)) * 100)}%` }}
        transition={{ type: "spring", stiffness: 120, damping: 20 }}
      />
    </div>
  );
}

export function Swatch({ color, size = 18, className, title }: { color: string; size?: number; className?: string; title?: string }) {
  return (
    <span
      title={title ?? color}
      className={clsx("inline-block shrink-0 rounded-full ring-1 ring-[var(--line)]", className)}
      style={{ width: size, height: size, background: color.startsWith("#") ? color : `#${color}` }}
    />
  );
}

export function Img({ src, alt, className, ratio }: { src: string; alt: string; className?: string; ratio?: number }) {
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState(false);
  return (
    <div className={clsx("relative overflow-hidden bg-surface-2", className)} style={ratio ? { aspectRatio: String(ratio) } : undefined}>
      {!ok && !err && <div className="skeleton absolute inset-0" />}
      {!err && (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          onLoad={() => setOk(true)}
          onError={() => setErr(true)}
          className={clsx("h-full w-full object-cover transition-opacity duration-500", ok ? "opacity-100" : "opacity-0")}
        />
      )}
    </div>
  );
}

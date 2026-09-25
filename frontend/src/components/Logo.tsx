import { clsx } from "clsx";

export function LogoMark({ size = 34, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={clsx("shrink-0", className)} aria-hidden>
      <defs>
        <linearGradient id="lk-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0077FF" />
          <stop offset="0.6" stopColor="#735CE6" />
          <stop offset="1" stopColor="#E03FAB" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="18" fill="url(#lk-g)" />
      <path d="M19 16v28a4 4 0 0 0 4 4h22" fill="none" stroke="#fff" strokeWidth="6" strokeLinecap="round" />
      <path d="M30 16h15M30 26h9M30 36h13" fill="none" stroke="#fff" strokeOpacity=".78" strokeWidth="5" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      {!compact && (
        <div className="leading-none">
          <div className="font-display text-[19px] font-semibold tracking-tight">Лекало</div>
          <div className="mt-1 text-[11px] font-medium text-fg-3">дизайнер презентаций</div>
        </div>
      )}
    </div>
  );
}

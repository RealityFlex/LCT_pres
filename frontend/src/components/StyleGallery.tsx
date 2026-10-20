import { useQuery } from "@tanstack/react-query";
import { Icon24MagicWandOutline, Icon24PaletteOutline } from "@vkontakte/icons";
import { clsx } from "clsx";
import { useMemo, useState } from "react";
import { api, type StyleColors, type StyleInfo, type StylePalette } from "../lib/api";

/** Палитра стиля с учётом «своих цветов» — та же логика, что StyleSpec.with_overrides на бэкенде (упрощённо). */
export function applyColors(p: StylePalette, c?: StyleColors | null): StylePalette {
  if (!c) return p;
  const strip = (v?: string) => (v ? v.replace("#", "").toUpperCase() : undefined);
  const bg = strip(c.background), pr = strip(c.primary), sec = strip(c.secondary), aux = strip(c.auxiliary);
  return { ...p, ...(bg ? { bg } : {}), ...(pr ? { primary: pr, dark_bg: pr } : {}), ...(sec ? { secondary: sec } : {}), ...(aux ? { accent: aux } : {}) };
}

/** Мгновенный эскиз обложки и контентного слайда стиля (SVG на клиенте, без рендера на сервере). */
export function StylePreview({ s, colors, className }: { s: StyleInfo; colors?: StyleColors | null; className?: string }) {
  const p0 = applyColors(s.palette, colors);
  const h = (x: string) => `#${x}`;
  // светлая обложка: фон и текст контентных слайдов; разделённая — тёмный блок слева
  const light = s.cover === "light";
  const p = light ? { ...p0, dark_bg: p0.bg, dark_text: p0.text } : p0;
  const motif = (() => {
    if (s.motif === "bars") return [0, 1, 2].map((i) => <rect key={i} x={120 + i * 11} y={18 + i * 8} width={7} height={46 - i * 8} fill={i ? h(p.dark_text) : h(p.accent)} opacity={i ? 0.12 : 1} />);
    if (s.motif === "circle") return [<circle key="a" cx={136} cy={38} r={20} fill={h(p.dark_text)} opacity={0.1} />, <circle key="b" cx={148} cy={52} r={8} fill={h(p.accent)} />];
    if (s.motif === "frame") return [<rect key="a" x={116} y={20} width={34} height={28} fill="none" stroke={h(p.accent)} strokeWidth={1.2} />, <rect key="b" x={124} y={28} width={34} height={28} fill={h(p.dark_text)} opacity={0.1} />];
    if (s.motif === "none") return [<rect key="a" x={150} y={16} width={1.5} height={50} fill={h(p.accent)} />];
    return [<rect key="a" x={118} y={18} width={30} height={30} fill={h(p.dark_text)} opacity={0.1} />, <rect key="b" x={128} y={28} width={30} height={30} fill={h(p.accent)} />];
  })();
  return (
    <svg viewBox="0 0 180 101" className={clsx("block w-full", className)} role="img" aria-label={s.name}>
      <rect width="180" height="101" fill={h(s.cover === "split" ? p.bg : p.dark_bg)} />
      {s.cover === "split" && <rect width="104" height="101" fill={h(p.dark_bg)} />}
      <rect x="12" y="14" width="34" height="2.4" rx="1" fill={h(p.accent)} />
      <rect x="12" y="36" width="78" height="7" rx="1.5" fill={h(p.dark_text)} />
      <rect x="12" y="47" width="58" height="7" rx="1.5" fill={h(p.dark_text)} />
      <rect x="12" y="60" width="11" height="1.8" fill={h(p.accent)} />
      <rect x="12" y="66" width="70" height="2.6" rx="1" fill={h(p.dark_text)} opacity={0.5} />
      {motif}
      {/* мини-контентный слайд */}
      <g transform="translate(96 62)">
        <rect width="76" height="34" rx="2" fill={h(p.bg)} stroke={h(p.rule)} strokeWidth={0.6} />
        <rect x="5" y="4" width="18" height="1.6" fill={h(p.primary)} />
        <rect x="5" y="8" width="42" height="3.2" rx="0.8" fill={h(p.text)} />
        <rect x="5" y="14" width="66" height="0.5" fill={h(p.rule)} />
        {[0, 1, 2].map((i) => (
          <g key={i} transform={`translate(${5 + i * 22.5} 17)`}>
            <rect width="20" height="13" rx="1" fill={h(p.surface)} stroke={h(p.rule)} strokeWidth={0.4} />
            <rect x="2.5" y="2.5" width="6" height="2.6" fill={i ? h(p.primary) : h(p.accent)} />
            <rect x="2.5" y="7" width="14" height="1.4" fill={h(p.muted)} />
          </g>
        ))}
      </g>
    </svg>
  );
}

const COLOR_FIELDS: { key: keyof StyleColors; label: string; from: keyof StylePalette }[] = [
  { key: "background", label: "Фон", from: "bg" },
  { key: "primary", label: "Основной", from: "primary" },
  { key: "secondary", label: "Вторичный", from: "secondary" },
  { key: "auxiliary", label: "Акцент", from: "accent" },
];

export function StyleGallery({ value, colors, onChange }: {
  value: string;
  colors: StyleColors | null;
  onChange: (styleId: string, colors: StyleColors | null) => void;
}) {
  const q = useQuery({ queryKey: ["styles"], queryFn: api.styles, staleTime: 60_000 });
  const [cat, setCat] = useState<string>("all");
  const [custom, setCustom] = useState(!!colors);
  const styles = q.data ?? [];
  const cats = useMemo(() => [...new Map(styles.map((s) => [s.category, s.category_ru])).entries()], [styles]);
  const shown = styles.filter((s) => cat === "all" || s.category === cat);
  const current = styles.find((s) => s.id === value);

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        <button className="chip" data-on={cat === "all"} onClick={() => setCat("all")}>Все</button>
        {cats.map(([id, ru]) => (
          <button key={id} className="chip" data-on={cat === id} onClick={() => setCat(id)}>{ru}</button>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <button onClick={() => { onChange("auto", null); setCustom(false); }}
          className={clsx("group overflow-hidden rounded-xl border text-left transition", value === "auto" ? "border-accent ring-2 ring-accent/40" : "border-line hover:border-fg-4")}>
          <div className="grid place-items-center bg-gradient-to-br from-[var(--brand)]/25 via-surface-2 to-[var(--accent)]/20 text-accent" style={{ aspectRatio: "180/101" }}>
            <Icon24MagicWandOutline width={36} height={36} />
          </div>
          <div className="px-3 py-2.5">
            <div className="text-[14px] font-semibold">Авто</div>
            <div className="text-[12px] text-fg-3">Подберу стиль по теме и назначению</div>
          </div>
        </button>
        {shown.map((s) => (
          <button key={s.id} onClick={() => onChange(s.id, custom ? colors : null)}
            className={clsx("group overflow-hidden rounded-xl border text-left transition", value === s.id ? "border-accent ring-2 ring-accent/40" : "border-line hover:border-fg-4")}>
            <StylePreview s={s} colors={value === s.id ? colors : null} />
            <div className="px-3 py-2.5">
              <div className="text-[14px] font-semibold leading-snug">{s.name}</div>
              <div className="line-clamp-1 text-[12px] text-fg-3">{s.category_ru} · {s.fonts.heading === s.fonts.body ? s.fonts.heading : `${s.fonts.heading} + ${s.fonts.body}`}</div>
            </div>
          </button>
        ))}
      </div>
      {current && (
        <div className="mt-4 rounded-xl border border-line p-4">
          <label className="flex cursor-pointer items-center gap-2 text-[13px] font-semibold text-fg-2">
            <input type="checkbox" checked={custom} className="accent-[var(--brand)]"
              onChange={(e) => { setCustom(e.target.checked); onChange(current.id, e.target.checked ? colors ?? {} : null); }} />
            <Icon24PaletteOutline width={18} height={18} /> Свои цвета для «{current.name}»
          </label>
          {custom && (
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {COLOR_FIELDS.map((f) => {
                const v = colors?.[f.key] ?? `#${current.palette[f.from]}`;
                return (
                  <label key={f.key} className="flex items-center gap-2 text-[12px] text-fg-3">
                    <input type="color" value={v.startsWith("#") ? v : `#${v}`} className="size-8 cursor-pointer rounded border border-line bg-transparent"
                      onChange={(e) => onChange(current.id, { ...(colors ?? {}), [f.key]: e.target.value })} />
                    {f.label}
                  </label>
                );
              })}
            </div>
          )}
        </div>
      )}
      {q.isError && <div className="mt-3 text-[13px] text-bad">Не удалось загрузить стили: {(q.error as Error).message}</div>}
    </div>
  );
}

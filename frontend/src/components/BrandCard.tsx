// Брендбук проекта: загрузка (.fig, токены JSON, PDF-гайдлайн, логотипы PNG/SVG/ZIP) и карточка того, что извлечено.
import { Icon24DocumentPlusOutline, Icon24CancelOutline } from "@vkontakte/icons";
import { clsx } from "clsx";
import { useRef, useState } from "react";
import { api, url, type BrandInfo } from "../lib/api";
import { Badge, Button } from "./ui";

const ACCEPT = ".fig,.json,.pdf,.png,.svg,.jpg,.jpeg,.webp,.zip";
const ROLE_RU: Record<string, string> = {
  primary: "основной", secondary: "второй", bg: "фон", bg_dark: "тёмный фон", text: "текст", muted: "приглушённый",
};

export function BrandBlock({ brand, onBrand, priority, onPriority, templateMode }: {
  brand: BrandInfo | null;
  onBrand: (b: BrandInfo | null) => void;
  priority: "brand" | "template";
  onPriority: (p: "brand" | "template") => void;
  templateMode: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(list: FileList | null) {
    if (!list || !list.length) return;
    setBusy(true);
    setError(null);
    try {
      onBrand(await api.brand(Array.from(list)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (ref.current) ref.current.value = "";
    }
  }

  return (
    <div className="mt-5 border-t border-line pt-5" data-testid="brand-block">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="text-[14px] font-semibold">Брендбук</div>
        <span className="text-[12px] text-fg-4">необязательно · Figma (.fig), токены JSON, PDF-гайдлайн, логотипы</span>
      </div>
      <input ref={ref} type="file" multiple accept={ACCEPT} className="hidden" data-testid="brand-input"
        onChange={(e) => upload(e.target.files)} />
      {!brand ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" variant="soft" loading={busy} onClick={() => ref.current?.click()}
            icon={<Icon24DocumentPlusOutline width={18} height={18} />}>
            {busy ? "Разбираю брендбук…" : "Загрузить брендбук"}
          </Button>
          <span className="text-[12px] text-fg-4">цвета, шрифты и логотип применятся к {templateMode ? "шаблону" : "стилю"}</span>
          {error && <div className="w-full text-[12px] text-bad">Не удалось разобрать: {error}</div>}
        </div>
      ) : (
        <div className="rounded-xl border border-line p-3" data-testid="brand-card">
          <div className="mb-2 flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold">{brand.name}</div>
              <div className="truncate text-[11px] text-fg-4">{brand.sources.join(" · ")}</div>
            </div>
            <button aria-label="Убрать брендбук" className="text-fg-3 hover:text-fg" onClick={() => onBrand(null)}>
              <Icon24CancelOutline width={18} height={18} />
            </button>
          </div>
          <div className="mb-2 flex flex-wrap gap-2">
            {Object.entries(brand.palette).filter(([k]) => ROLE_RU[k]).map(([k, v]) => (
              <div key={k} className="flex items-center gap-1.5 text-[11px] text-fg-3" title={`#${v}`}>
                <span className="inline-block size-5 rounded-md ring-1 ring-[var(--line)]" style={{ background: `#${v}` }} />
                {ROLE_RU[k]}
              </div>
            ))}
            {brand.accents.slice(0, 4).map((a) => (
              <span key={a} className="inline-block size-5 rounded-md ring-1 ring-[var(--line)]" title={`акцент #${a}`} style={{ background: `#${a}` }} />
            ))}
          </div>
          {Object.keys(brand.fonts).length > 0 && (
            <div className="mb-2 text-[12px] text-fg-2">
              Шрифты: {Object.entries(brand.fonts).map(([k, v]) => `${k === "heading" ? "заголовки" : k === "body" ? "текст" : "код"} — ${v}`).join("; ")}
            </div>
          )}
          {brand.logos.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {brand.logos.map((l) => (
                <div key={l.url} className={clsx("grid h-12 place-items-center rounded-lg px-3", l.dark_bg ? "bg-[#1c232b]" : "bg-white ring-1 ring-[var(--line)]")}>
                  <img src={url(l.url)} alt={l.name} className="max-h-8 max-w-40 object-contain" />
                </div>
              ))}
            </div>
          )}
          {brand.slides.length > 0 && <div className="mb-2 text-[11px] text-fg-4">Примеров слайдов 16:9: {brand.slides.length}</div>}
          {(brand.spacing && Object.keys(brand.spacing).length > 0 || brand.logo_min_h || brand.logo_clear) && (
            <div className="mb-2 text-[12px] text-fg-2">
              Сетка и логотип:{" "}
              {[brand.spacing?.margin && `поля ${brand.spacing.margin} px`, brand.spacing?.gap && `зазор ${brand.spacing.gap} px`,
                brand.spacing?.radius && `скругление ${brand.spacing.radius} px`, brand.logo_min_h && `логотип не меньше ${Math.round(brand.logo_min_h)} px`,
                brand.logo_clear && `охранное поле ${Math.round(brand.logo_clear * 100)}% высоты`].filter(Boolean).join(" · ")}
            </div>
          )}
          {brand.rules.length > 0 && (
            <details className="mb-2 text-[12px] text-fg-3">
              <summary className="cursor-pointer text-fg-2">Правила бренда: {brand.rules.length}</summary>
              {brand.rules.slice(0, 8).map((r) => <div key={r}>• {r}</div>)}
            </details>
          )}
          {brand.warnings.map((w) => <div key={w} className="text-[12px] text-orange">⚠ {w}</div>)}
          {templateMode && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-[12px] text-fg-3">Если брендбук и шаблон расходятся:</span>
              <button className="chip" data-on={priority === "brand"} onClick={() => onPriority("brand")}>важнее брендбук</button>
              <button className="chip" data-on={priority === "template"} onClick={() => onPriority("template")}>важнее шаблон (только логотип)</button>
            </div>
          )}
          <div className="mt-2"><Badge tone="ok">применится при генерации</Badge></div>
        </div>
      )}
    </div>
  );
}

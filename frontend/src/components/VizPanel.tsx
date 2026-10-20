// Панель «Визуализация» слайда с данными: задача, выбранный тип и почему, альтернативы — переключение по клику.
import { clsx } from "clsx";
import type { SlideData } from "../lib/api";
import { Badge, Button, Panel } from "./ui";

export function VizPanel({ data, busy, pending, onPick, className }: {
  data: SlideData;
  busy?: boolean;
  pending?: string | null;
  onPick: (type: string) => void;
  className?: string;
}) {
  const cur = data.options.find((o) => o.type === data.viz) ?? data.options[0];
  const rejected = data.options[0]?.rejected ?? [];
  return (
    <Panel className={clsx("p-4", className)} data-testid="viz-panel">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="text-[13px] font-semibold">Визуализация</div>
        <Badge tone="accent">задача: {data.task_ru}</Badge>
        {data.file && <Badge>{data.file}</Badge>}
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {data.options.map((o, i) => {
          const active = o.type === cur?.type;
          return (
            <div key={o.type}
              className={clsx("flex flex-col rounded-xl border p-3 transition-colors",
                active ? "border-accent bg-[color-mix(in_srgb,var(--accent)_8%,transparent)]" : "border-line")}>
              {/* метка — отдельной строкой: на узкой карточке длинное название переносится и налезало на неё */}
              {i === 0 && <div className="mb-1.5"><Badge tone="ok">рекомендовано</Badge></div>}
              <div className="mb-1 text-[13px] font-semibold leading-snug">{o.label}</div>
              <div className="mb-3 flex-1 text-[12px] leading-snug text-fg-2">{o.why}</div>
              {active ? (
                <div className="text-[12px] font-medium text-accent">На слайде сейчас</div>
              ) : (
                <Button size="sm" variant="soft" loading={busy && pending === o.type} disabled={busy}
                  onClick={() => onPick(o.type)}>
                  Показать так
                </Button>
              )}
            </div>
          );
        })}
      </div>
      {(rejected.length > 0 || data.profile) && (
        <div className="mt-3 space-y-1 text-[12px] leading-snug text-fg-3">
          {rejected.slice(0, 2).map((r) => <div key={r}>✕ {r}</div>)}
          {data.profile && <div>Профиль: {data.profile}</div>}
        </div>
      )}
    </Panel>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Icon20Add, Icon20DeleteOutline, Icon24MagicWandOutline, Icon24DragReorderOutline } from "@vkontakte/icons";
import { Reorder, useDragControls } from "motion/react";
import { useEffect, useState } from "react";
import { api, type Job, type Outline, type OutlineSlide } from "../lib/api";
import { Button, Panel, Spinner, useToast } from "./ui";

const INTENT_RU: Record<string, string> = {
  title: "Титул", agenda: "План", section: "Раздел", bullets: "Тезисы", cards: "Карточки", process: "Процесс",
  timeline: "Хронология", stats: "Цифры", chart: "Диаграмма", table: "Таблица", comparison: "Сравнение",
  quote: "Главная мысль", image: "Иллюстрация", closing: "Финал",
};

type Row = OutlineSlide & { key: string };
let seq = 0;
const key = () => `r${++seq}`;

function SlideRow({ row, n, onChange, onRemove, onAddAfter }: {
  row: Row; n: number; onChange: (r: Row) => void; onRemove: () => void; onAddAfter: () => void;
}) {
  const drag = useDragControls();
  const [wish, setWish] = useState(!!row.instruction);
  const structural = row.intent === "title" || row.intent === "section" || row.intent === "agenda";
  return (
    <Reorder.Item value={row} dragListener={false} dragControls={drag}
      className="group rounded-xl border border-line bg-[color-mix(in_srgb,var(--surface)_70%,transparent)] p-3 sm:p-4">
      <div className="flex items-start gap-3">
        <button type="button" className="mt-1.5 cursor-grab touch-none text-fg-4 hover:text-fg-2" onPointerDown={(e) => drag.start(e)}
          aria-label="Перетащить">
          <Icon24DragReorderOutline width={20} height={20} />
        </button>
        <span className="mt-1.5 w-6 shrink-0 font-mono text-[12px] font-semibold text-fg-4">{String(n).padStart(2, "0")}</span>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-col gap-2 sm:flex-row">
            <select value={row.intent} onChange={(e) => onChange({ ...row, intent: e.target.value })}
              className="field !h-9 !w-auto !py-0 text-[13px] sm:w-40">
              {Object.entries(INTENT_RU).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <input value={row.title} onChange={(e) => onChange({ ...row, title: e.target.value })}
              className="field !h-9 flex-1 font-semibold" placeholder="Заголовок — вывод слайда" />
          </div>
          {!structural && (
            <textarea value={row.points.join("\n")} rows={Math.min(5, Math.max(2, row.points.length))}
              onChange={(e) => onChange({ ...row, points: e.target.value.split("\n") })}
              className="field !min-h-0 text-[13px] leading-relaxed" placeholder="Тезисы — по одному в строке" />
          )}
          {wish ? (
            <input value={row.instruction ?? ""} onChange={(e) => onChange({ ...row, instruction: e.target.value })}
              className="field !h-9 text-[13px]" placeholder="Пожелание: «добавь пример», «сделай таблицей», «подробнее»…" autoFocus />
          ) : (
            <button type="button" className="text-[12px] font-medium text-accent hover:underline" onClick={() => setWish(true)}>
              + пожелание к слайду
            </button>
          )}
        </div>
        <div className="flex shrink-0 flex-col gap-1 opacity-60 transition group-hover:opacity-100">
          <button type="button" title="Добавить слайд после" onClick={onAddAfter} className="rounded-lg p-1.5 hover:bg-[color-mix(in_srgb,var(--text)_8%,transparent)]">
            <Icon20Add />
          </button>
          <button type="button" title="Удалить слайд" onClick={onRemove} className="rounded-lg p-1.5 text-bad hover:bg-[color-mix(in_srgb,var(--text)_8%,transparent)]">
            <Icon20DeleteOutline />
          </button>
        </div>
      </div>
    </Reorder.Item>
  );
}

/** Шаг «План»: человек правит структуру, сборка запускается по кнопке; изменённые слайды дописывает модель. */
export function OutlineEditor({ job }: { job: Job }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["outline", job.id], queryFn: () => api.outline(job.id) });
  const [title, setTitle] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => {
    if (q.data) {
      setTitle(q.data.title);
      setRows(q.data.slides.map((s) => ({ ...s, key: key() })));
    }
  }, [q.data]);
  const build = useMutation({
    mutationFn: () => {
      const outline: Outline = {
        title,
        slides: rows.map(({ key: _k, ...s }) => ({ ...s, points: s.points.map((p) => p.trim()).filter(Boolean) })),
      };
      return api.build(job.id, outline);
    },
    onSuccess: (r) => {
      toast({ tone: "ok", title: "Собираю презентацию", text: r.rewritten ? `Допишу изменённые слайды: ${r.rewritten}` : "План без изменений" });
      qc.invalidateQueries({ queryKey: ["job", job.id] });
    },
    onError: (e: Error) => toast({ tone: "bad", title: "Не удалось запустить сборку", text: e.message }),
  });

  if (q.isLoading) return <div className="grid min-h-[40vh] place-items-center"><Spinner size={28} className="text-accent" /></div>;
  if (q.isError) return <Panel className="p-6 text-bad">План не загрузился: {(q.error as Error).message}</Panel>;

  const set = (i: number, r: Row) => setRows((xs) => xs.map((x, k) => (k === i ? r : x)));
  const content = rows.filter((r) => !["title", "section", "agenda", "closing"].includes(r.intent)).length;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <Panel className="p-5 sm:p-7">
        <div className="mb-1 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">План презентации</div>
        <input value={title} onChange={(e) => setTitle(e.target.value)} className="mb-2 w-full bg-transparent font-display text-[24px] font-semibold tracking-tight outline-none" />
        <p className="mb-5 text-[13px] text-fg-3">
          Проверьте структуру: меняйте порядок перетаскиванием, переименовывайте, меняйте тип и тезисы, добавляйте и удаляйте слайды.
          Изменённые слайды я допишу, остальные оставлю как есть.
        </p>
        <Reorder.Group axis="y" values={rows} onReorder={setRows} className="space-y-2.5">
          {rows.map((r, i) => (
            <SlideRow key={r.key} row={r} n={i + 1} onChange={(x) => set(i, x)}
              onRemove={() => setRows((xs) => xs.filter((_, k) => k !== i))}
              onAddAfter={() => setRows((xs) => [...xs.slice(0, i + 1), { key: key(), id: null, intent: "cards", title: "", points: [], instruction: "" }, ...xs.slice(i + 1)])} />
          ))}
        </Reorder.Group>
      </Panel>
      <div className="lg:sticky lg:top-6 lg:self-start">
        <Panel className="space-y-4 p-5">
          <div className="space-y-2 text-[13px]">
            <div className="flex justify-between"><span className="text-fg-3">Слайдов</span><span className="font-semibold">{rows.length}</span></div>
            <div className="flex justify-between"><span className="text-fg-3">Содержательных</span><span className="font-semibold">{content}</span></div>
            <div className="flex justify-between"><span className="text-fg-3">Разделов</span><span className="font-semibold">{rows.filter((r) => r.intent === "section").length}</span></div>
          </div>
          <Button variant="primary" size="lg" glow className="w-full" loading={build.isPending}
            disabled={!rows.length || rows.some((r) => !r.title.trim())} onClick={() => build.mutate()}
            icon={<Icon24MagicWandOutline width={22} height={22} />}>
            Собрать презентацию
          </Button>
          {rows.some((r) => !r.title.trim()) && <div className="text-[12px] text-bad">У каждого слайда должен быть заголовок</div>}
        </Panel>
      </div>
    </div>
  );
}

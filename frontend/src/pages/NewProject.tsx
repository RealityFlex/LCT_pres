import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Icon20CheckCircleOn,
  Icon24BriefcaseOutline,
  Icon24EducationOutline,
  Icon24LightbulbOutline,
  Icon24MagicWandOutline,
  Icon24PaletteOutline,
  Icon24Rocket,
  Icon24StatisticsOutline,
  Icon24UsersOutline,
  Icon24WriteOutline,
} from "@vkontakte/icons";
import { clsx } from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Dropzone, TemplateCard } from "../components/Cards";
import { Button, Kbd, Panel, Segmented, Swatch, useToast } from "../components/ui";
import { api, withW, type Brief } from "../lib/api";
import { AUDIENCES, countNumbers, PURPOSES } from "../lib/format";

const DRAFT = "lekalo-draft";
const PURPOSE_ICON: Record<string, ReactNode> = {
  "проект": <Icon24BriefcaseOutline />,
  "продукт": <Icon24Rocket />,
  "фича": <Icon24MagicWandOutline />,
  "инициатива": <Icon24LightbulbOutline />,
  "обучение": <Icon24EducationOutline />,
  "другое": <Icon24WriteOutline />,
};

function loadDraft(): Brief {
  const empty: Brief = { topic: "", purpose: "проект", audience: "", details: "", slide_count: null, author: "", language: "ru", images: "auto" };
  try {
    const d = JSON.parse(localStorage.getItem(DRAFT) || "null");
    return d ? { ...empty, ...d } : empty;
  } catch {
    return empty;
  }
}

function Step({ n, title, done, children, right }: { n: number; title: string; done?: boolean; children: ReactNode; right?: ReactNode }) {
  return (
    <Panel className="p-5 sm:p-7">
      <div className="mb-5 flex items-center gap-3">
        <span className={clsx("grid size-8 place-items-center rounded-xl font-display text-sm font-semibold transition-colors",
          done ? "bg-ok text-white" : "bg-[color-mix(in_srgb,var(--accent)_14%,transparent)] text-accent")}>
          {done ? <Icon20CheckCircleOn width={18} height={18} /> : n}
        </span>
        <h2 className="flex-1 text-lg font-semibold tracking-tight">{title}</h2>
        {right}
      </div>
      {children}
    </Panel>
  );
}

function Label({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-3">
      <span className="text-[13px] font-semibold text-fg-2">{children}</span>
      {hint && <span className="text-[12px] text-fg-4">{hint}</span>}
    </div>
  );
}

export default function NewProject() {
  const nav = useNavigate();
  const toast = useToast();
  const [sp] = useSearchParams();
  const tpls = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const examples = useQuery({ queryKey: ["examples"], queryFn: api.examples });
  const [tid, setTid] = useState<string | null>(sp.get("template"));
  const [pickOpen, setPickOpen] = useState(!sp.get("template"));
  const [brief, setBrief] = useState<Brief>(loadDraft);
  const [manual, setManual] = useState(brief.slide_count != null);
  const topicRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!tid && tpls.data?.length) setTid(tpls.data[0].id);
  }, [tpls.data, tid]);
  useEffect(() => {
    try {
      localStorage.setItem(DRAFT, JSON.stringify(brief));
    } catch {
      /* ignore */
    }
  }, [brief]);

  const tpl = useMemo(() => tpls.data?.find((t) => t.id === tid) ?? null, [tpls.data, tid]);
  const nums = countNumbers(brief.details);
  const set = <K extends keyof Brief>(k: K, v: Brief[K]) => setBrief((b) => ({ ...b, [k]: v }));

  const create = useMutation({
    mutationFn: () => api.createJob(tid!, { ...brief, slide_count: manual ? brief.slide_count ?? 12 : null }),
    onSuccess: (r) => nav(`/project/${r.id}`),
    onError: (e: Error) => toast({ tone: "bad", title: "Не удалось запустить", text: e.message }),
  });
  const ready = !!tid && brief.topic.trim().length >= 3;
  const submit = () => {
    if (!tid) return toast({ tone: "bad", title: "Выберите шаблон" });
    if (brief.topic.trim().length < 3) {
      topicRef.current?.focus();
      return toast({ tone: "bad", title: "Опишите тему презентации" });
    }
    create.mutate();
  };
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submit();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });

  const estSlides = manual ? brief.slide_count ?? 12 : Math.max(11, Math.min(14, 11 + Math.floor((nums + brief.details.split("\n").filter(Boolean).length) / 6)));

  return (
    <div className="mx-auto max-w-[1360px] px-4 py-6 max-lg:pb-24 sm:px-6 lg:px-10 lg:py-10">
      <div className="mb-8">
        <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">Новая презентация</div>
        <h1 className="font-display text-[30px] font-semibold leading-tight tracking-tight sm:text-[40px]">
          Шаблон + бриф = <span className="gradient-text">три готовые колоды</span>
        </h1>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          {/* ---------------------------------------------- шаг 1 */}
          <Step n={1} title="Шаблон компании" done={!!tpl && !pickOpen}
            right={tpl && !pickOpen ? <Button size="sm" variant="soft" onClick={() => setPickOpen(true)}>Изменить</Button> : null}>
            <AnimatePresence initial={false} mode="wait">
              {tpl && !pickOpen ? (
                <motion.div key="sel" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  className="flex flex-col gap-4 sm:flex-row sm:items-center">
                  <img src={withW(tpl.cover, 480)} alt="" className="w-full rounded-xl ring-1 ring-[var(--line)] sm:w-56" style={{ aspectRatio: "16/9", objectFit: "cover" }} />
                  <div className="min-w-0">
                    <div className="text-[17px] font-semibold">{tpl.name}</div>
                    <div className="mt-1 text-[13px] text-fg-3">{tpl.fonts.filter((f, i, a) => a.indexOf(f) === i).join(" · ")} · {tpl.n_slides} слайдов в образце</div>
                    <div className="mt-3 flex -space-x-1">{tpl.colors.slice(0, 8).map((c) => <Swatch key={c} color={c} size={22} className="ring-2 !ring-[var(--surface)]" />)}</div>
                  </div>
                </motion.div>
              ) : (
                <motion.div key="grid" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {(tpls.data ?? []).map((t) => (
                    <TemplateCard key={t.id} t={t} selected={t.id === tid} onClick={() => { setTid(t.id); setPickOpen(false); }} />
                  ))}
                  <Dropzone compact onReady={(id) => { setTid(id); setPickOpen(false); toast({ tone: "ok", title: "Шаблон разобран", text: "Дизайн-система извлечена — можно генерировать." }); }} />
                </motion.div>
              )}
            </AnimatePresence>
          </Step>

          {/* ---------------------------------------------- шаг 2 */}
          <Step n={2} title="Бриф" done={ready}>
            {examples.data && examples.data.length > 0 && (
              <div className="mb-6 flex flex-wrap items-center gap-2">
                <span className="mr-1 text-[13px] text-fg-3">Заполнить примером:</span>
                {examples.data.map((ex) => (
                  <button key={ex.id} className="chip" onClick={() => {
                    setBrief((b) => ({ ...b, topic: ex.topic, purpose: ex.purpose, audience: ex.audience ?? "", details: (ex.details ?? "").trim() }));
                    toast({ tone: "info", title: "Пример подставлен", text: ex.topic });
                  }}>
                    {ex.title_hint ?? ex.purpose}
                  </button>
                ))}
              </div>
            )}

            <div className="space-y-6">
              <div>
                <Label hint={`${brief.topic.length}/140`}>О чём презентация</Label>
                <input ref={topicRef} value={brief.topic} maxLength={140} onChange={(e) => set("topic", e.target.value)}
                  placeholder="Например: запуск платформы «Умный склад» в розничной сети"
                  className="field !py-4 !text-[17px] font-medium" />
              </div>

              <div>
                <Label>Назначение</Label>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
                  {PURPOSES.map((p) => {
                    const on = brief.purpose === p.id;
                    return (
                      <button key={p.id} onClick={() => set("purpose", p.id)}
                        className={clsx("relative flex h-[74px] flex-col items-center justify-center gap-1.5 rounded-2xl border text-[13px] font-semibold transition-all",
                          on ? "border-transparent text-accent" : "border-line bg-[color-mix(in_srgb,var(--surface)_60%,transparent)] text-fg-2 hover:text-fg")}>
                        {on && <motion.span layoutId="purpose" className="absolute inset-0 rounded-2xl bg-[color-mix(in_srgb,var(--accent)_13%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--accent)_45%,transparent)]" />}
                        <span className="relative">{PURPOSE_ICON[p.id]}</span>
                        <span className="relative">{p.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <Label>Аудитория</Label>
                <input value={brief.audience} onChange={(e) => set("audience", e.target.value)} placeholder="Кто будет смотреть"
                  className="field" />
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {AUDIENCES.map((a) => (
                    <button key={a} className="chip" data-on={brief.audience === a} onClick={() => set("audience", a)}>
                      <Icon24UsersOutline width={14} height={14} /> {a}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <Label hint="единственный источник цифр и фактов">Данные и факты</Label>
                <textarea value={brief.details} onChange={(e) => set("details", e.target.value)} rows={7}
                  placeholder={"Цифры, результаты, сроки, риски…\nНапример: время сборки снизилось с 4,5 до 1,5 часа; бюджет 48 млн руб."}
                  className="field scroll-thin" />
                <div className={clsx("mt-2 flex items-center gap-2 rounded-xl px-3 py-2 text-[13px]",
                  nums >= 3 ? "bg-[color-mix(in_srgb,var(--green)_12%,transparent)] text-ok" : "bg-[color-mix(in_srgb,var(--text)_5%,transparent)] text-fg-3")}>
                  <Icon24StatisticsOutline width={18} height={18} />
                  {nums >= 3
                    ? `Найдено чисел: ${nums} — появятся диаграммы и крупные цифры`
                    : nums > 0
                      ? `Найдено чисел: ${nums} — добавьте ряд значений, и будет график`
                      : "Без цифр презентация будет качественной: карточки, процессы, сравнения"}
                </div>
              </div>

              <div>
                <Label hint="GigaChat · Kandinsky, в стиле шаблона">Иллюстрации</Label>
                <Segmented value={brief.images} onChange={(v) => set("images", v)} options={[
                  { value: "auto", label: "Где уместно" },
                  { value: "on", label: "Обязательно" },
                  { value: "off", label: "Без картинок" },
                ]} />
              </div>

              <div className="grid gap-6 sm:grid-cols-2">
                <div>
                  <Label hint={manual ? `${brief.slide_count ?? 12} слайдов` : "по объёму брифа"}>Количество слайдов</Label>
                  <Segmented value={manual ? "manual" : "auto"} onChange={(v) => { setManual(v === "manual"); if (v === "manual" && !brief.slide_count) set("slide_count", 12); }}
                    options={[{ value: "auto", label: "Автоматически" }, { value: "manual", label: "Задать" }]} />
                  {manual && (
                    <input type="range" min={6} max={16} value={brief.slide_count ?? 12} onChange={(e) => set("slide_count", Number(e.target.value))}
                      className="mt-4 w-full accent-[var(--brand)]" />
                  )}
                </div>
                <div>
                  <Label hint="необязательно">Автор</Label>
                  <input value={brief.author} onChange={(e) => set("author", e.target.value)} placeholder="Имя или команда" className="field" />
                </div>
              </div>
            </div>
          </Step>
        </div>

        {/* ---------------------------------------------- предпросмотр */}
        <div className="lg:sticky lg:top-6 lg:self-start">
          <Panel className="overflow-hidden">
            <div className="relative" style={{ aspectRatio: "16/9" }}>
              {tpl ? (
                <img src={withW(tpl.cover, 800)} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="grid h-full place-items-center bg-surface-2 text-fg-4"><Icon24PaletteOutline width={40} height={40} /></div>
              )}
              <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
              <div className="absolute inset-x-5 bottom-4 text-white">
                <div className="text-[12px] font-medium opacity-80">{tpl?.name ?? "Шаблон не выбран"}</div>
                <div className="mt-1 line-clamp-2 text-[17px] font-semibold leading-snug">{brief.topic || "Тема презентации"}</div>
              </div>
            </div>
            <div className="space-y-4 p-5">
              <div className="grid grid-cols-3 gap-2">
                {[["A", "Классика"], ["B", "Визуал"], ["C", "Компакт"]].map(([k, n]) => (
                  <div key={k} className="rounded-xl border border-line bg-[color-mix(in_srgb,var(--surface)_60%,transparent)] px-3 py-2.5 text-center">
                    <div className="font-display text-[17px] font-semibold text-accent">{k}</div>
                    <div className="text-[11px] text-fg-3">{n}</div>
                  </div>
                ))}
              </div>
              <div className="space-y-2 text-[13px]">
                <div className="flex justify-between"><span className="text-fg-3">Слайдов в варианте</span><span className="font-semibold">≈ {estSlides}</span></div>
                <div className="flex justify-between"><span className="text-fg-3">Назначение</span><span className="font-semibold">{PURPOSES.find((p) => p.id === brief.purpose)?.label}</span></div>
                <div className="flex justify-between"><span className="text-fg-3">Цифр в данных</span><span className="font-semibold">{nums}</span></div>
                <div className="flex justify-between"><span className="text-fg-3">Иллюстрации</span><span className="font-semibold">{brief.images === "off" ? "нет" : brief.images === "on" ? "2–3 слайда" : "по смыслу"}</span></div>
                <div className="flex justify-between"><span className="text-fg-3">Бюджет времени</span><span className="font-semibold">до 5 минут</span></div>
              </div>
              <Button variant="primary" size="lg" glow className="w-full" loading={create.isPending} disabled={!ready} onClick={submit}
                icon={<Icon24MagicWandOutline width={22} height={22} />}>
                Сгенерировать 3 варианта
              </Button>
              <div className="hidden items-center justify-center gap-1.5 text-[12px] text-fg-4 lg:flex">
                <Kbd>Ctrl</Kbd>+<Kbd>Enter</Kbd>
              </div>
            </div>
          </Panel>
        </div>
      </div>
      {/* телефон: кнопка запуска всегда под рукой над нижней навигацией, не нужно листать до конца */}
      {ready && (
        <div className="fixed inset-x-4 z-30 lg:hidden" style={{ bottom: "calc(80px + env(safe-area-inset-bottom))" }}>
          <Button variant="primary" size="lg" glow className="w-full" loading={create.isPending} onClick={submit}
            icon={<Icon24MagicWandOutline width={22} height={22} />}>
            Сгенерировать 3 варианта
          </Button>
        </div>
      )}
    </div>
  );
}

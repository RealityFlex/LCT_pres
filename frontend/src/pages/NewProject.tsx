import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Icon20CheckCircleOn,
  Icon24DocumentPlusOutline,
  Icon24BriefcaseOutline,
  Icon24CancelOutline,
  Icon24ClockOutline,
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
import { StyleGallery, StylePreview } from "../components/StyleGallery";
import { BrandBlock } from "../components/BrandCard";
import { Button, Kbd, Panel, Segmented, Swatch, useToast } from "../components/ui";
import { api, withW, type BrandInfo, type Brief, type ClarifyQuestion, type Material, type StyleColors } from "../lib/api";
import { AUDIENCES, countNumbers, PURPOSES } from "../lib/format";

const DRAFT = "lekalo-draft";
const DURATIONS: (number | null)[] = [null, 5, 7, 10, 15, 20];
const ACCEPT = ".txt,.md,.markdown,.pdf,.docx,.pptx,.csv,.tsv,.xlsx,.xls,.json,.yaml,.yml,.html";
const PURPOSE_ICON: Record<string, ReactNode> = {
  "проект": <Icon24BriefcaseOutline />,
  "продукт": <Icon24Rocket />,
  "фича": <Icon24MagicWandOutline />,
  "инициатива": <Icon24LightbulbOutline />,
  "обучение": <Icon24EducationOutline />,
  "другое": <Icon24WriteOutline />,
};

function loadDraft(): Brief {
  const empty: Brief = { topic: "", purpose: "проект", audience: "", details: "", slide_count: null, duration_min: null, author: "", language: "ru", images: "auto", web_search: true, image_source: "auto" };
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
  // оформление: шаблон компании (по умолчанию) или встроенный стиль Лекала
  const [mode, setMode] = useState<"style" | "template">(sp.get("style") && !sp.get("template") ? "style" : "template");
  const [styleId, setStyleId] = useState<string>(sp.get("style") ?? "auto");
  const [styleColors, setStyleColors] = useState<StyleColors | null>(() => {
    try { return sp.get("colors") ? (JSON.parse(sp.get("colors")!) as StyleColors) : null; } catch { return null; }
  });
  const styles = useQuery({ queryKey: ["styles"], queryFn: api.styles, staleTime: 60_000 });
  const styleInfo = styles.data?.find((x) => x.id === styleId) ?? null;
  // сначала план (outline) и уточняющие вопросы — как у Kimi/Gamma перед сборкой
  const [planFirst, setPlanFirst] = useState<boolean | null>(null);
  const [questions, setQuestions] = useState<ClarifyQuestion[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [asking, setAsking] = useState(false);
  const [only, setOnly] = useState<string | null>(null);   // null — все три варианта
  const [brief, setBrief] = useState<Brief>(loadDraft);
  const [manual, setManual] = useState(brief.slide_count != null);
  const topicRef = useRef<HTMLInputElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [files, setFiles] = useState<Material[]>([]);
  const [goals, setGoals] = useState<Record<string, string>>({});   // id датасета → цель анализа
  const [brand, setBrand] = useState<BrandInfo | null>(null);
  const [brandPriority, setBrandPriority] = useState<"brand" | "template">("brand");
  const [reading, setReading] = useState(false);
  const attach = async (list: FileList | null) => {
    if (!list?.length) return;
    setReading(true);
    try {
      const r = await api.materials(Array.from(list));
      setFiles((f) => [...f, ...r.files]);
      const bad = r.files.filter((x) => x.error);
      if (bad.length) toast({ tone: "bad", title: `Не прочитан: ${bad[0].name}`, text: bad[0].error });
    } catch (e) {
      toast({ tone: "bad", title: "Не удалось прочитать файлы", text: (e as Error).message });
    } finally {
      setReading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  useEffect(() => {
    if (mode === "template" && !tid && tpls.data?.length) setTid(tpls.data[0].id);
  }, [tpls.data, tid, mode]);
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
    mutationFn: (b?: Brief) => api.createJob(mode === "template" ? tid : null, {
      ...(b ?? baseBrief()),
      style_id: mode === "style" ? styleId : null, style_colors: mode === "style" ? styleColors : null,
      datasets: files.filter((f) => f.dataset).map((f) => f.dataset!.id),
      brand_id: brand?.id ?? null, brand_priority: brandPriority,
      dataset_goals: Object.fromEntries(Object.entries(goals).filter(([k, v]) => v.trim() && files.some((f) => f.dataset?.id === k))),
    }, files, plan, only ? [only] : undefined),
    onSuccess: (r) => nav(`/project/${r.id}`),
    onError: (e: Error) => toast({ tone: "bad", title: "Не удалось запустить", text: e.message }),
  });
  const ready = (mode === "style" || !!tid) && brief.topic.trim().length >= 3;
  // объём: заданный вручную или автоматический (null); ответы на уточнения его только переопределяют
  function baseBrief(): Brief {
    return { ...brief, slide_count: manual ? brief.slide_count ?? 12 : null };
  }
  const withAnswers = (): Brief => {
    let b: Brief = baseBrief();
    for (const q of questions ?? []) {
      const o = q.options[answers[q.id] ?? -1];
      if (!o) continue;
      const p = o.patch;
      if (p.slide_count) b = { ...b, slide_count: p.slide_count };
      if (p.audience) b = { ...b, audience: p.audience };
      if (p.depth) b = { ...b, details: `${b.details}
Подача: ${p.depth}`.trim() };
      if (p.emphasis) b = { ...b, details: `${b.details}
Акцент: ${p.emphasis}`.trim() };
    }
    return b;
  };
  const submit = async () => {
    if (mode === "template" && !tid) return toast({ tone: "bad", title: "Выберите шаблон" });
    if (brief.topic.trim().length < 3) {
      topicRef.current?.focus();
      return toast({ tone: "bad", title: "Опишите тему презентации" });
    }
    // уточнения — когда материал большой или бриф совсем короткий (как Kimi при полном документе)
    if (questions === null && (matChars > 15000 || brief.details.trim().length < 20)) {
      setAsking(true);
      try {
        const r = await api.clarify(baseBrief(), matChars);
        if (r.questions.length) {
          setQuestions(r.questions);
          return;
        }
      } catch {
        /* без вопросов */
      } finally {
        setAsking(false);
      }
    }
    create.mutate(questions ? withAnswers() : undefined);
  };
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submit();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });

  const estSlides = manual
    ? brief.slide_count ?? 12
    : brief.duration_min
      ? Math.max(10, Math.min(15, Math.round(brief.duration_min * 1.5)))
      : Math.max(11, Math.min(14, 11 + Math.floor((nums + brief.details.split("\n").filter(Boolean).length) / 6)));
  const matChars = files.reduce((a, f) => a + (f.chars ?? 0), 0);
  const plan = planFirst ?? matChars > 15000;   // длинный документ — по умолчанию сначала план

  return (
    <div className="mx-auto max-w-[1360px] px-4 py-6 max-lg:pb-24 sm:px-6 lg:px-10 lg:py-10">
      <div className="mb-8">
        <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">Новая презентация</div>
        <h1 className="font-display text-[30px] font-semibold leading-tight tracking-tight sm:text-[40px]">
          Тема + стиль = <span className="gradient-text">три готовые колоды</span>
        </h1>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          {/* ---------------------------------------------- шаг 1 */}
          <Step n={1} title="Оформление" done={mode === "style" ? true : !!tpl && !pickOpen}
            right={mode === "template" && tpl && !pickOpen ? <Button size="sm" variant="soft" onClick={() => setPickOpen(true)}>Изменить</Button> : null}>
            <Segmented className="mb-5" value={mode} onChange={(v) => setMode(v)}
              options={[{ value: "template", label: "Шаблон компании" }, { value: "style", label: "Стиль Лекала" }]} />
            {mode === "style" ? (
              <StyleGallery value={styleId} colors={styleColors} onChange={(id, c) => { setStyleId(id); setStyleColors(c); }} />
            ) : (
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
            )}
            <BrandBlock brand={brand} onBrand={setBrand} priority={brandPriority} onPriority={setBrandPriority}
              templateMode={mode === "template"} />
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
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
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
                <Label hint="README, документация, отчёты, старая презентация">Материалы</Label>
                <input ref={fileRef} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => attach(e.target.files)} />
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="soft" loading={reading} onClick={() => fileRef.current?.click()}
                    icon={<Icon24DocumentPlusOutline width={18} height={18} />}>
                    Приложить файлы
                  </Button>
                  {files.map((f, i) => (
                    <span key={f.name + i} className={clsx("chip max-w-full", f.error && "!text-bad")} title={f.error}>
                      <span className="truncate">{f.name}</span>
                      {f.dataset ? (
                        <span className="text-fg-4">{f.dataset.tables.map((t) => `${t.nature} · ${t.rows} строк`).join("; ")}</span>
                      ) : f.chars != null && <span className="text-fg-4">{Math.round(f.chars / 100) / 10} тыс. зн.</span>}
                      <button aria-label="Убрать" onClick={() => setFiles((x) => x.filter((_, j) => j !== i))}>
                        <Icon24CancelOutline width={14} height={14} />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="mt-2 text-[12px] text-fg-4">txt, md, pdf, docx, pptx — текст станет источником фактов; csv, xlsx, json и таблицы в тексте — датасеты: сервис определит их природу, построит диаграммы и сформулирует выводы</div>
                {files.some((f) => f.dataset) && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {files.filter((f) => f.dataset).map((f) => (
                      <DatasetCard key={f.dataset!.id} file={f} goal={goals[f.dataset!.id] ?? ""}
                        onGoal={(v) => setGoals((g) => ({ ...g, [f.dataset!.id]: v }))} />
                    ))}
                  </div>
                )}
              </div>

              <div>
                <Label hint="объём колоды и текст для спикера">Длительность выступления</Label>
                <div className="flex flex-wrap gap-1.5">
                  {DURATIONS.map((d) => (
                    <button key={String(d)} className="chip" data-on={brief.duration_min === d} onClick={() => set("duration_min", d)}>
                      {d == null ? "Не важно" : <><Icon24ClockOutline width={14} height={14} /> {d} мин</>}
                    </button>
                  ))}
                </div>
              </div>

              <div data-testid="quality">
                <Label hint={brief.quality === "extended" ? "без лимита времени" : "три колоды — до 5 минут"}>Режим генерации</Label>
                <Segmented value={brief.quality ?? "normal"} onChange={(v) => set("quality", v)} options={[
                  { value: "normal", label: "Обычный" },
                  { value: "extended", label: "Extended thinking" },
                ]} />
                <div className="mt-2 text-[12px] text-fg-4">
                  {brief.quality === "extended"
                    ? "больше попыток дизайнера, визуальная проверка каждого слайда и автоисправление всех замечаний оформления"
                    : "у каждого этапа свой лимит времени: три варианта с аудитом гарантированно за 5 минут"}
                </div>
              </div>

              <div>
                <Label hint="бесплатно, через API Википедии">Факты из интернета</Label>
                <label className="flex cursor-pointer items-start gap-2.5 text-[14px] text-fg-2">
                  <input type="checkbox" checked={brief.web_search ?? false} onChange={(e) => set("web_search", e.target.checked)}
                    className="mt-1 accent-[var(--brand)]" />
                  <span>Найти определения, даты и цифры по теме в Википедии
                    <span className="block text-[12px] text-fg-4">источник появится в подвале слайда и в заметках спикера</span></span>
                </label>
              </div>

              <div>
                <Label hint={brief.image_source === "generate" ? "в стиле шаблона" : "фото со свободной лицензией"}>Иллюстрации</Label>
                <Segmented value={brief.images} onChange={(v) => set("images", v)} options={[
                  { value: "auto", label: "Где уместно" },
                  { value: "on", label: "Обязательно" },
                  { value: "off", label: "Без картинок" },
                ]} />
                {brief.images !== "off" && (
                  <div className="mt-3">
                    <Segmented value={brief.image_source ?? "auto"} onChange={(v) => set("image_source", v)} options={[
                      { value: "auto", label: "Фото, иначе рисунок" },
                      { value: "web", label: "Только фото" },
                      { value: "generate", label: "Нарисовать" },
                    ]} />
                    <div className="mt-2 text-[12px] text-fg-4">
                      {brief.image_source === "generate" ? "Kandinsky нарисует иллюстрации в цветах стиля"
                        : "фото из Wikimedia Commons — модель отбирает подходящие, автор и лицензия указываются на слайде"}
                    </div>
                  </div>
                )}
              </div>

              <div className="grid gap-6 sm:grid-cols-2">
                <div>
                  <Label hint={manual ? `${brief.slide_count ?? 12} слайдов` : brief.duration_min ? "по длительности" : "10–15, по объёму брифа"}>Количество слайдов</Label>
                  <Segmented value={manual ? "manual" : "auto"} onChange={(v) => { setManual(v === "manual"); if (v === "manual" && !brief.slide_count) set("slide_count", 12); }}
                    options={[{ value: "auto", label: "Автоматически" }, { value: "manual", label: "Задать" }]} />
                  {manual && (
                    <input type="range" min={5} max={20} value={brief.slide_count ?? 12} onChange={(e) => set("slide_count", Number(e.target.value))}
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
              {mode === "style" ? (
                styleInfo ? <StylePreview s={styleInfo} colors={styleColors} className="h-full" /> : (
                  <div className="grid h-full place-items-center bg-gradient-to-br from-[var(--brand)]/25 via-surface-2 to-[var(--accent)]/20 text-accent">
                    <Icon24MagicWandOutline width={44} height={44} />
                  </div>)
              ) : tpl ? (
                <img src={withW(tpl.cover, 800)} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="grid h-full place-items-center bg-surface-2 text-fg-4"><Icon24PaletteOutline width={40} height={40} /></div>
              )}
              <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
              <div className="absolute inset-x-5 bottom-4 text-white">
                <div className="text-[12px] font-medium opacity-80">{mode === "style" ? (styleInfo ? `Стиль «${styleInfo.name}»${styleColors ? " · свои цвета" : ""}` : "Стиль подберу по теме") : tpl?.name ?? "Шаблон не выбран"}</div>
                <div className="mt-1 line-clamp-2 text-[17px] font-semibold leading-snug">{brief.topic || "Тема презентации"}</div>
              </div>
            </div>
            <div className="space-y-4 p-5">
              <div className="grid grid-cols-3 gap-2">
                {[["A", "Классика"], ["B", "Дизайнерский"], ["C", "Компакт"]].map(([k, n]) => {
                  const on = only === null || only === k;
                  return (
                    <button key={k} type="button" onClick={() => setOnly(only === k ? null : k)} title={only === k ? "Вернуть все три" : `Только вариант ${k}`}
                      className={clsx("rounded-xl border px-3 py-2.5 text-center transition",
                        only === k ? "border-accent ring-2 ring-accent/40" : "border-line", on ? "bg-[color-mix(in_srgb,var(--surface)_60%,transparent)]" : "opacity-40")}>
                      <div className="font-display text-[17px] font-semibold text-accent">{k}</div>
                      <div className="text-[11px] text-fg-3">{n}</div>
                    </button>
                  );
                })}
              </div>
              <div className="space-y-2 text-[13px]">
                <div className="flex justify-between"><span className="text-fg-3">Слайдов в варианте</span><span className="font-semibold">≈ {estSlides}</span></div>
                <div className="flex justify-between"><span className="text-fg-3">Назначение</span><span className="font-semibold">{PURPOSES.find((p) => p.id === brief.purpose)?.label}</span></div>
                <div className="flex justify-between"><span className="text-fg-3">Цифр в данных</span><span className="font-semibold">{nums}</span></div>
                {brief.duration_min != null && (
                  <div className="flex justify-between"><span className="text-fg-3">Выступление</span><span className="font-semibold">{brief.duration_min} мин + текст спикера</span></div>
                )}
                {files.length > 0 && (
                  <div className="flex justify-between"><span className="text-fg-3">Материалы</span><span className="font-semibold">{files.filter((f) => f.text).length} файл. · {Math.round(matChars / 1000)} тыс. зн.</span></div>
                )}
                <div className="flex justify-between"><span className="text-fg-3">Иллюстрации</span><span className="font-semibold">{brief.images === "off" ? "нет" : (brief.images === "on" ? "2–3 слайда" : "по смыслу") + (brief.image_source === "generate" ? " · рисунки" : " · фото")}</span></div>
                {brief.web_search && (
                  <div className="flex justify-between"><span className="text-fg-3">Факты</span><span className="font-semibold">+ Википедия</span></div>
                )}
                <div className="flex justify-between"><span className="text-fg-3">Режим</span><span className="font-semibold">{brief.quality === "extended" ? "Extended thinking" : "Обычный · до 5 минут"}</span></div>
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-[13px] text-fg-2">
                <input type="checkbox" checked={plan} onChange={(e) => setPlanFirst(e.target.checked)} className="accent-[var(--brand)]" />
                Сначала показать план — поправлю структуру перед сборкой
              </label>
              <Button variant="primary" size="lg" glow className="w-full" loading={create.isPending || asking} disabled={!ready} onClick={submit}
                icon={<Icon24MagicWandOutline width={22} height={22} />}>
                {plan ? "Составить план" : only ? `Сгенерировать вариант ${only}` : "Сгенерировать 3 варианта"}
              </Button>
              <div className="hidden items-center justify-center gap-1.5 text-[12px] text-fg-4 lg:flex">
                <Kbd>Enter</Kbd> в теме или <Kbd>Ctrl</Kbd>+<Kbd>Enter</Kbd>
              </div>
            </div>
          </Panel>
        </div>
      </div>
      {questions && questions.length > 0 && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" onClick={() => setQuestions(null)}>
          <Panel className="w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
            <div className="mb-1 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">Пара уточнений</div>
            <h3 className="mb-4 text-lg font-semibold">Чтобы колода получилась точнее</h3>
            <div className="space-y-5">
              {questions.map((q) => (
                <div key={q.id}>
                  <div className="mb-2 text-[14px] font-medium">{q.text}</div>
                  <div className="flex flex-wrap gap-2">
                    {q.options.map((o, i) => (
                      <button key={o.label} className="chip" data-on={answers[q.id] === i}
                        onClick={() => setAnswers((a) => ({ ...a, [q.id]: a[q.id] === i ? -1 : i }))}>{o.label}</button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="soft" onClick={() => { setQuestions([]); create.mutate(undefined); }}>Пропустить</Button>
              <Button variant="primary" loading={create.isPending} onClick={() => create.mutate(withAnswers())}>Продолжить</Button>
            </div>
          </Panel>
        </div>
      )}
      {/* телефон: кнопка запуска всегда под рукой над нижней навигацией, не нужно листать до конца */}
      {ready && (
        <div className="fixed inset-x-4 z-30 lg:hidden" style={{ bottom: "calc(80px + env(safe-area-inset-bottom))" }}>
          <Button variant="primary" size="lg" glow className="w-full" loading={create.isPending} onClick={submit}
            icon={<Icon24MagicWandOutline width={22} height={22} />}>
            {only ? `Сгенерировать вариант ${only}` : "Сгенерировать 3 варианта"}
          </Button>
        </div>
      )}
    </div>
  );
}


/** Карточка датасета: профиль, аналитическая задача и предлагаемая визуализация; цель уточняет выбор. */
function DatasetCard({ file, goal, onGoal }: { file: Material; goal: string; onGoal: (v: string) => void }) {
  const tables = file.dataset?.tables ?? [];
  return (
    <div className="rounded-xl border border-line p-3 text-[12px] leading-snug">
      <div className="mb-1.5 truncate text-[13px] font-semibold">{file.name}</div>
      {tables.map((t) => (
        <div key={t.name} className="mb-2">
          {t.status === "error" ? (
            <div className="text-orange">Не распознано: {t.reason}</div>
          ) : (
            <>
              <div className="flex flex-wrap gap-1">
                <span className="badge text-accent bg-[color-mix(in_srgb,var(--accent)_13%,transparent)]">{t.task ?? t.nature}</span>
                {t.viz && <span className="badge text-fg-2 bg-[color-mix(in_srgb,var(--text)_7%,transparent)]">{t.viz}</span>}
                <span className="text-fg-4">{t.rows} строк × {t.cols}</span>
              </div>
              {(t.dimensions?.length || t.metrics?.length) ? (
                <div className="mt-1 text-fg-3">
                  {t.time_axis && <>время: {t.time_axis}; </>}
                  {t.dimensions?.length ? <>измерения: {t.dimensions.join(", ")}; </> : null}
                  {t.metrics?.length ? <>метрики: {t.metrics.join(", ")}</> : null}
                  {t.missing ? <>; пропуски {Math.round(t.missing * 1000) / 10}%</> : null}
                </div>
              ) : null}
              {t.why && <div className="mt-1 text-fg-4">{t.why}</div>}
            </>
          )}
        </div>
      ))}
      <input value={goal} onChange={(e) => onGoal(e.target.value)} className="field !py-1.5 !text-[12px]"
        placeholder="Цель (необязательно): показать связь цены и продаж…" />
    </div>
  );
}

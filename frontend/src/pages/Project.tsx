import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Icon24ArrowLeftOutline,
  Icon24ClockOutline,
  Icon24DeleteOutline,
  Icon24DocumentOutline,
  Icon24DownloadOutline,
  Icon24ErrorCircleOutline,
  Icon24ExternalLinkOutline,
  Icon24Fullscreen,
  Icon24SquareGrid3x3,
  Icon24MoreHorizontal,
  Icon24PaletteOutline,
  Icon24RefreshOutline,
  Icon24ShareOutline,
} from "@vkontakte/icons";
import { clsx } from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AuditPanel } from "../components/Audit";
import { TemplateCard } from "../components/Cards";
import { GenerationView } from "../components/Generation";
import { Filmstrip, PresentMode, SlideViewer } from "../components/Viewer";
import { Badge, Button, Empty, Modal, ModalHeader, Panel, Spinner, useToast } from "../components/ui";
import { api, downloadUrl, url, type Job, type JobEvent, type VariantData } from "../lib/api";
import { downloadFile, haptic, shareLink } from "../lib/bridge";
import { slidesWord } from "../lib/format";

function useJobStream(id: string) {
  const qc = useQueryClient();
  const job = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.job(id),
    refetchInterval: (q) => (q.state.data && (q.state.data.status === "done" || q.state.data.status === "error") ? false : 2500),
  });
  const [events, setEvents] = useState<JobEvent[]>([]);
  useEffect(() => {
    if (job.data?.events) setEvents((prev) => (job.data!.events.length >= prev.length ? job.data!.events : prev));
  }, [job.data]);
  const running = job.data?.status === "running" || job.data?.status === "queued";
  useEffect(() => {
    if (!running) return;
    const es = new EventSource(url(`/api/jobs/${id}/events`));
    es.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data) as JobEvent;
        setEvents((xs) => (xs.some((x) => x.t === ev.t && x.message === ev.message) ? xs : [...xs, ev]));
        if (ev.stage === "done" || ev.stage === "error" || ev.variant) qc.invalidateQueries({ queryKey: ["job", id] });
        if (ev.stage === "done") {
          qc.invalidateQueries({ queryKey: ["jobs"] });
          qc.invalidateQueries({ queryKey: ["stats"] });
        }
      } catch {
        /* пинг */
      }
    };
    return () => es.close();
  }, [id, running, qc]);
  return { job, events };
}

export default function Project() {
  const { id = "" } = useParams();
  const { job, events } = useJobStream(id);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const nav = useNavigate();

  if (job.isLoading) {
    return <div className="grid min-h-[60vh] place-items-center"><Spinner size={32} className="text-accent" /></div>;
  }
  if (job.isError || !job.data) {
    return (
      <Empty icon={<Icon24ErrorCircleOutline width={32} height={32} />} title="Проект не найден"
        text="Возможно, он был удалён." action={<Button variant="primary" onClick={() => nav("/projects")}>К проектам</Button>} />
    );
  }
  const j = job.data;
  return (
    <div className="mx-auto max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <Header job={j} />
      <AnimatePresence mode="wait">
        {j.status === "done" ? (
          <motion.div key="res" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
            <ResultView job={j} />
          </motion.div>
        ) : j.status === "error" ? (
          <motion.div key="err" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <ErrorView job={j} />
          </motion.div>
        ) : (
          <motion.div key="gen" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, y: -8 }}>
            <GenerationView job={j} events={events} budget={health.data?.deadline_s ?? 300} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Header({ job }: { job: Job }) {
  const tpls = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const tpl = tpls.data?.find((t) => t.id === job.template_id);
  const secs = job.finished ? Math.round(job.finished - job.created) : null;
  return (
    <div className="mb-6">
      <Link to="/projects" className="mb-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-fg-3 hover:text-fg">
        <Icon24ArrowLeftOutline width={16} height={16} /> Проекты
      </Link>
      <h1 className="font-display text-[26px] font-semibold leading-tight tracking-tight text-balance sm:text-[34px]">
        {job.title || job.brief.topic}
      </h1>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-fg-3">
        {tpl && (
          <Link to={`/templates/${tpl.id}`} className="chip">
            <Icon24PaletteOutline width={14} height={14} /> {tpl.name}
          </Link>
        )}
        <span className="chip"><Icon24DocumentOutline width={14} height={14} /> {job.brief.purpose}</span>
        {secs != null && <span className="chip"><Icon24ClockOutline width={14} height={14} /> {secs} с на три колоды</span>}
        {job.status === "done" && job.llm_stats?.calls != null && (
          <span className="chip font-mono !text-[12px]">{job.llm_stats.calls} вызовов LLM</span>
        )}
      </div>
    </div>
  );
}

function ErrorView({ job }: { job: Job }) {
  const nav = useNavigate();
  const rerun = useMutation({ mutationFn: () => api.rerun(job.id, undefined, false), onSuccess: (r) => nav(`/project/${r.id}`) });
  return (
    <Panel className="mx-auto max-w-xl p-8 text-center">
      <div className="mx-auto mb-4 grid size-14 place-items-center rounded-2xl bg-[color-mix(in_srgb,var(--red)_14%,transparent)] text-bad">
        <Icon24ErrorCircleOutline width={30} height={30} />
      </div>
      <div className="text-lg font-semibold">Генерация прервалась</div>
      <div className="mt-2 break-words font-mono text-[12px] text-fg-3">{job.error}</div>
      <Button variant="primary" className="mt-6" loading={rerun.isPending} onClick={() => rerun.mutate()} icon={<Icon24RefreshOutline width={20} height={20} />}>
        Запустить снова
      </Button>
    </Panel>
  );
}

function ResultView({ job }: { job: Job }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const [vid, setVid] = useState(job.variants[0]?.id ?? "A");
  const [idx, setIdx] = useState(1);
  const [showIssues, setShowIssues] = useState(true);
  const [hover, setHover] = useState<string | null>(null);
  const [present, setPresent] = useState(false);
  const [compare, setCompare] = useState(false);
  const [other, setOther] = useState(false);
  const [menu, setMenu] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);

  const data = useQuery({ queryKey: ["variant", job.id, vid], queryFn: () => api.variant(job.id, vid) });
  const v = data.data;
  const slides = v?.slides ?? [];
  const issues = v?.audit?.issues ?? [];
  useEffect(() => {
    if (idx > slides.length && slides.length) setIdx(slides.length);
  }, [slides.length, idx]);

  const fix = useMutation({
    mutationFn: (ids: string[]) => api.fix(job.id, vid, ids),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["variant", job.id, vid] });
      qc.invalidateQueries({ queryKey: ["job", job.id] });
      haptic("medium");
      toast({ tone: "ok", title: `Исправлено, ревизия ${r.revision}`, text: r.log.slice(-2).join(" · ") || `изменено слайдов: ${r.changed.length}` });
    },
    onError: (e: Error) => toast({ tone: "bad", title: "Не удалось исправить", text: e.message }),
  });

  const del = useMutation({
    mutationFn: () => api.deleteJob(job.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); nav("/projects"); },
  });
  const rerun = useMutation({
    mutationFn: (p: { tid?: string; reuse: boolean }) => api.rerun(job.id, p.tid, p.reuse),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["jobs"] }); nav(`/project/${r.id}`); },
  });

  const cur = job.variants.find((x) => x.id === vid);
  const dl = async (fmt: "pptx" | "pdf") => {
    await downloadFile(downloadUrl(job.id, vid, fmt), `${(job.title || "presentation").slice(0, 60)} — ${vid}.${fmt}`);
    toast({ tone: "ok", title: `Скачивание ${fmt.toUpperCase()}`, text: `Вариант ${vid} · ${cur?.name ?? ""}` });
  };

  return (
    <>
      {/* ------------------------------------------ варианты и действия */}
      <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-stretch">
        <div className="grid flex-1 gap-3 sm:grid-cols-3">
          {job.variants.map((x) => {
            const on = x.id === vid;
            return (
              <button key={x.id} onClick={() => { setVid(x.id); setIdx(1); }}
                className={clsx("relative flex items-center gap-3 overflow-hidden rounded-[18px] border p-3.5 text-left transition-all",
                  on ? "border-transparent bg-surface shadow-[var(--shadow-2)] ring-grad" : "border-line bg-[color-mix(in_srgb,var(--surface)_55%,transparent)] hover:bg-surface")}>
                <span className={clsx("grid size-11 shrink-0 place-items-center rounded-2xl font-display text-lg font-semibold",
                  on ? "bg-[linear-gradient(135deg,var(--brand),var(--purple))] text-white" : "bg-[color-mix(in_srgb,var(--text)_7%,transparent)] text-fg-2")}>{x.id}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[15px] font-semibold">{x.name}</div>
                  <div className="truncate text-[12px] text-fg-3">{slidesWord(x.n_slides)} · {x.description.split(",")[0]}</div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  {(x.audit.error ?? 0) > 0 ? <Badge tone="bad" dot>{x.audit.error}</Badge> : <Badge tone="ok" dot>0</Badge>}
                  {(x.audit.warning ?? 0) > 0 && <Badge tone="warn" dot>{x.audit.warning}</Badge>}
                </div>
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2 xl:flex-nowrap">
          <Button variant="primary" glow onClick={() => dl("pptx")} icon={<Icon24DownloadOutline width={20} height={20} />}>PPTX</Button>
          <Button variant="outline" onClick={() => dl("pdf")}>PDF</Button>
          <Button variant="outline" onClick={() => window.open(downloadUrl(job.id, vid, "html", true), "_blank", "noopener")} iconRight={<Icon24ExternalLinkOutline width={16} height={16} />}>HTML</Button>
          <Button variant="ghost" onClick={() => setCompare(true)} icon={<Icon24SquareGrid3x3 width={20} height={20} />} title="Сравнить варианты" />
          <Button variant="ghost" onClick={() => setPresent(true)} icon={<Icon24Fullscreen width={20} height={20} />} title="Показ" />
          <div className="relative">
            <Button variant="ghost" onClick={() => setMenu((m) => !m)} icon={<Icon24MoreHorizontal width={20} height={20} />} title="Ещё" />
            <AnimatePresence>
              {menu && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setMenu(false)} />
                  <motion.div initial={{ opacity: 0, y: -6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4 }}
                    className="glass-strong absolute right-0 top-12 z-50 w-72 overflow-hidden rounded-2xl p-1.5">
                    {[
                      { icon: <Icon24PaletteOutline width={20} height={20} />, label: "Тот же контент на другом шаблоне", run: () => setOther(true) },
                      { icon: <Icon24RefreshOutline width={20} height={20} />, label: "Сгенерировать заново", run: () => rerun.mutate({ reuse: false }) },
                      { icon: <Icon24ShareOutline width={20} height={20} />, label: "Поделиться ссылкой", run: async () => { const ok = await shareLink(`#/project/${job.id}`); toast({ tone: ok ? "ok" : "bad", title: ok ? "Ссылка готова" : "Не удалось поделиться" }); } },
                      { icon: <Icon24DeleteOutline width={20} height={20} />, label: "Удалить проект", danger: true, run: () => del.mutate() },
                    ].map((m) => (
                      <button key={m.label} onClick={() => { setMenu(false); m.run(); }}
                        className={clsx("flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[14px] font-medium transition-colors hover:bg-[color-mix(in_srgb,var(--text)_6%,transparent)]",
                          m.danger && "text-bad")}>
                        {m.icon}{m.label}
                      </button>
                    ))}
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* ------------------------------------------ рабочая область */}
      {data.isLoading || !v ? (
        <div className="grid min-h-[50vh] place-items-center"><Spinner size={30} className="text-accent" /></div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[148px_minmax(0,1fr)_380px]">
          <div className="hidden xl:block">
            <Filmstrip slides={slides} index={idx} onIndex={setIdx} issues={issues} vertical rev={cur?.revision} />
          </div>
          <div className="min-w-0">
            <SlideViewer slides={slides} index={idx} onIndex={setIdx} issues={issues} showIssues={showIssues}
              onToggleIssues={() => setShowIssues((s) => !s)} hoverIssue={hover} slideW={v.slide_w} slideH={v.slide_h}
              busy={fix.isPending} onPresent={() => setPresent(true)} />
            <div className="mt-4 xl:hidden">
              <Filmstrip slides={slides} index={idx} onIndex={setIdx} issues={issues} rev={cur?.revision} />
            </div>
            <div className="mt-4 xl:hidden">
              <Button variant="soft" className="w-full" onClick={() => setAuditOpen(true)}>
                Аудит: {issues.length} замечаний
              </Button>
            </div>
          </div>
          <div className="hidden xl:block">
            <AuditPanel className="sticky top-6 h-[calc(100vh-150px)]" report={v.audit} onGoto={setIdx} onHover={setHover}
              onFix={(ids) => fix.mutate(ids)} fixing={fix.isPending} />
          </div>
        </div>
      )}

      <Modal open={auditOpen} onClose={() => setAuditOpen(false)}>
        <div className="h-[80vh]">
          <AuditPanel className="h-full !rounded-none !border-0 !bg-transparent !shadow-none" report={v?.audit ?? null}
            onGoto={(n) => { setIdx(n); setAuditOpen(false); }} onHover={setHover}
            onFix={(ids) => { fix.mutate(ids); setAuditOpen(false); }} fixing={fix.isPending} />
        </div>
      </Modal>

      <CompareModal open={compare} onClose={() => setCompare(false)} job={job}
        onPick={(x, n) => { setVid(x); setIdx(n); setCompare(false); }} />

      <Modal open={other} onClose={() => setOther(false)} wide>
        <ModalHeader title="Тот же контент на другом шаблоне" subtitle="Сценарий и тексты сохраняются — меняется только дизайн-система" onClose={() => setOther(false)} />
        <OtherTemplate current={job.template_id} busy={rerun.isPending} onPick={(tid) => rerun.mutate({ tid, reuse: true })} />
      </Modal>

      <PresentMode open={present} slides={slides} start={idx} onClose={(at) => { setPresent(false); setIdx(at); }} />
    </>
  );
}

function OtherTemplate({ current, onPick, busy }: { current: string; onPick: (id: string) => void; busy: boolean }) {
  const tpls = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  return (
    <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-3">
      {(tpls.data ?? []).filter((t) => t.id !== current).map((t) => (
        <div key={t.id} className={clsx(busy && "pointer-events-none opacity-60")}><TemplateCard t={t} onClick={() => onPick(t.id)} /></div>
      ))}
    </div>
  );
}

function CompareModal({ open, onClose, job, onPick }: { open: boolean; onClose: () => void; job: Job; onPick: (vid: string, n: number) => void }) {
  const qs = useQuery({
    queryKey: ["compare", job.id, job.variants.map((v) => v.revision).join(",")],
    queryFn: async () => Promise.all(job.variants.map((v) => api.variant(job.id, v.id))),
    enabled: open,
  });
  const cols = useMemo<VariantData[]>(() => qs.data ?? [], [qs.data]);
  const scroller = useRef<HTMLDivElement | null>(null);
  return (
    <Modal open={open} onClose={onClose} wide className="sm:!max-w-[1400px]">
      <ModalHeader title="Сравнение вариантов" subtitle="Один контент — три способа вёрстки. Нажмите на слайд, чтобы открыть его" onClose={onClose} />
      {!qs.data ? (
        <div className="grid h-64 place-items-center"><Spinner size={26} /></div>
      ) : (
        <div ref={scroller} className="grid gap-5 p-6 md:grid-cols-3">
          {cols.map((c) => (
            <div key={c.variant?.id} className="min-w-0">
              <div className="mb-3 flex items-center gap-2">
                <span className="grid size-8 place-items-center rounded-xl bg-[linear-gradient(135deg,var(--brand),var(--purple))] font-display text-sm font-semibold text-white">{c.variant?.id}</span>
                <div className="text-[15px] font-semibold">{c.variant?.name}</div>
                <span className="text-[12px] text-fg-3">{slidesWord(c.slides.length)}</span>
              </div>
              <div className="space-y-2.5">
                {c.slides.map((s) => (
                  <button key={s.index} onClick={() => onPick(c.variant!.id, s.index)}
                    className="block w-full overflow-hidden rounded-xl ring-1 ring-[var(--line)] transition-transform hover:scale-[1.015] hover:ring-accent">
                    <img src={url(s.thumb)} alt="" loading="lazy" className="block w-full" style={{ aspectRatio: "16/9", objectFit: "cover" }} />
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Icon20CheckCircleOn, Icon24UploadOutline } from "@vkontakte/icons";
import { clsx } from "clsx";
import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, url, withW, type JobCard, type TemplateSummary } from "../lib/api";
import { ago, slidesWord } from "../lib/format";
import { Badge, LiveDot, ProgressBar, Spinner, Swatch, useSpotlight } from "./ui";

export function TemplateCard({ t, selected, onClick, to }: { t: TemplateSummary; selected?: boolean; onClick?: () => void; to?: string }) {
  const s = useSpotlight<HTMLDivElement>();
  const body = (
    <div
      ref={s.ref}
      onMouseMove={s.onMouseMove}
      className={clsx(
        "spotlight group relative overflow-hidden rounded-[20px] border bg-surface transition-all duration-300",
        selected ? "ring-grad border-transparent shadow-[var(--shadow-2)]" : "border-line hover:-translate-y-0.5 hover:shadow-[var(--shadow-2)]",
      )}
    >
      <div className="relative overflow-hidden" style={{ aspectRatio: "16 / 9" }}>
        <img src={withW(t.cover, 640)} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-[1.04]" />
        <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/55 to-transparent" />
        <div className="absolute bottom-3 left-3 flex -space-x-1.5">
          {t.colors.slice(0, 6).map((c) => (
            <Swatch key={c} color={c} size={18} className="ring-2 !ring-white/70" />
          ))}
        </div>
        {selected && (
          <motion.div initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
            className="absolute right-3 top-3 grid size-8 place-items-center rounded-full bg-brand text-white shadow-lg">
            <Icon20CheckCircleOn />
          </motion.div>
        )}
      </div>
      <div className="p-4">
        <div className="truncate text-[15px] font-semibold">{t.name}</div>
        <div className="mt-1 flex items-center gap-2 text-[12px] text-fg-3">
          <span className="truncate">{t.fonts.filter((f, i, a) => a.indexOf(f) === i).join(" · ")}</span>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Badge>{slidesWord(t.n_slides)}</Badge>
          <Badge tone="accent">{t.content_canvases} холст.</Badge>
          <Badge tone="neutral">{t.aspect > 1.7 ? "16:9" : t.aspect > 1.5 ? "16:10" : "4:3"}</Badge>
        </div>
      </div>
    </div>
  );
  if (to) return <Link to={to}>{body}</Link>;
  return (
    <button type="button" onClick={onClick} className="block w-full text-left">
      {body}
    </button>
  );
}

export function ProjectCard({ j }: { j: JobCard }) {
  const s = useSpotlight<HTMLAnchorElement>();
  const running = j.status === "running" || j.status === "queued";
  const errs = j.variants.reduce((a, v) => a + (v.audit.error ?? 0), 0);
  const warns = j.variants.reduce((a, v) => a + (v.audit.warning ?? 0), 0);
  return (
    <Link
      ref={s.ref}
      onMouseMove={s.onMouseMove}
      to={`/project/${j.id}`}
      className="spotlight group block overflow-hidden rounded-[20px] border border-line bg-surface transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[var(--shadow-2)]"
    >
      <div className={clsx("relative overflow-hidden bg-surface-2", running && "scan-wrap")} style={{ aspectRatio: "16 / 9" }}>
        {j.cover ? (
          <img src={url(j.cover)} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-[1.04]" />
        ) : (
          <div className="grid h-full place-items-center text-fg-4">{running ? <Spinner size={26} /> : "нет превью"}</div>
        )}
        <div className="absolute left-3 top-3 flex gap-1.5">
          {running && <Badge tone="accent" className="!bg-black/55 !text-white backdrop-blur"><LiveDot color="#5A9EFF" /> {Math.round(j.progress * 100)}%</Badge>}
          {j.status === "error" && <Badge tone="bad" className="!bg-black/55 backdrop-blur">ошибка</Badge>}
        </div>
        {j.variants.length > 0 && (
          <div className="absolute bottom-3 right-3 flex gap-1">
            {j.variants.map((v) => (
              <span key={v.id} className="grid size-6 place-items-center rounded-md bg-black/55 font-mono text-[11px] font-semibold text-white backdrop-blur">{v.id}</span>
            ))}
          </div>
        )}
      </div>
      <div className="p-4">
        <div className="line-clamp-2 min-h-[2.6em] text-[15px] font-semibold leading-snug">{j.title}</div>
        <div className="mt-2 flex items-center gap-2 text-[12px] text-fg-3">
          <span className="truncate">{j.template_name}</span>
          <span>·</span>
          <span className="shrink-0">{ago(j.created)}</span>
          {j.seconds != null && <><span>·</span><span className="shrink-0 font-mono">{Math.round(j.seconds)} с</span></>}
        </div>
        {j.status === "done" && (
          <div className="mt-3 flex gap-1.5">
            {errs > 0 ? <Badge tone="bad" dot>{errs} ошиб.</Badge> : <Badge tone="ok" dot>без ошибок</Badge>}
            {warns > 0 && <Badge tone="warn" dot>{warns} замеч.</Badge>}
          </div>
        )}
        {running && <ProgressBar value={j.progress} className="mt-3" />}
      </div>
    </Link>
  );
}

const PARSE_STAGES = ["Шрифты шаблона", "Структура слайдов", "Рендер шаблона", "Дизайн-токены", "Холсты", "Разметка слайдов моделью", "Готово"];

export function Dropzone({ onReady, compact }: { onReady: (id: string) => void; compact?: boolean }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement | null>(null);
  const [drag, setDrag] = useState(false);
  const [tid, setTid] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const up = useMutation({
    mutationFn: (f: File) => api.uploadTemplate(f),
    onSuccess: (r) => {
      if (r.status === "ready") {
        qc.invalidateQueries({ queryKey: ["templates"] });
        onReady(r.id);
      } else setTid(r.id);
    },
    onError: (e: Error) => setErr(e.message),
  });
  const st = useQuery({
    queryKey: ["parse", tid],
    queryFn: () => api.templateStatus(tid!),
    enabled: !!tid,
    refetchInterval: (q) => (q.state.data?.status === "parsing" || !q.state.data ? 900 : false),
  });
  useEffect(() => {
    if (st.data?.status === "ready" && tid) {
      qc.invalidateQueries({ queryKey: ["templates"] });
      onReady(tid);
      setTid(null);
    }
    if (st.data?.status === "error") {
      setErr(st.data.message);
      setTid(null);
    }
  }, [st.data, tid, qc, onReady]);

  const pick = (f?: File | null) => {
    if (!f) return;
    if (!/\.(pptx|potx)$/i.test(f.name)) {
      setErr("Нужен файл PowerPoint (.pptx или .potx)");
      return;
    }
    setErr(null);
    setFileName(f.name);
    up.mutate(f);
  };

  const busy = up.isPending || !!tid;
  const stageIdx = st.data ? Math.max(0, PARSE_STAGES.indexOf(st.data.message)) : 0;

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
      onClick={() => !busy && input.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && !busy && input.current?.click()}
      className={clsx(
        "relative flex h-full cursor-pointer flex-col items-center justify-center overflow-hidden rounded-[20px] border-2 border-dashed text-center transition-all duration-300",
        compact ? "min-h-[220px] p-5" : "min-h-[260px] p-8",
        drag ? "border-brand bg-[color-mix(in_srgb,var(--brand)_10%,transparent)] scale-[1.01]" : "border-line-2 hover:border-accent bg-[color-mix(in_srgb,var(--surface)_45%,transparent)]",
        busy && "cursor-progress",
      )}
    >
      <input ref={input} type="file" accept=".pptx,.potx" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
      {busy ? (
        <div className="w-full max-w-xs">
          <div className="mx-auto mb-4 grid size-14 place-items-center rounded-2xl bg-[color-mix(in_srgb,var(--brand)_14%,transparent)] text-brand">
            <Spinner size={26} />
          </div>
          <div className="truncate text-[15px] font-semibold">{fileName}</div>
          <div className="mt-1 text-[13px] text-fg-3">{up.isPending ? "Загружаю…" : st.data?.message ?? "Разбираю шаблон…"}</div>
          <ProgressBar value={up.isPending ? 0.04 : st.data?.progress ?? 0.05} className="mt-4" />
          <div className="mt-4 space-y-1.5 text-left">
            {PARSE_STAGES.slice(0, -1).map((s, k) => (
              <div key={s} className={clsx("flex items-center gap-2 text-[12px] transition-colors", k < stageIdx ? "text-ok" : k === stageIdx ? "text-fg" : "text-fg-4")}>
                {k < stageIdx ? <Icon20CheckCircleOn width={14} height={14} /> : k === stageIdx ? <Spinner size={12} /> : <span className="inline-block size-3.5 rounded-full border border-current" />}
                {s}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <>
          <motion.div
            animate={drag ? { y: -6, scale: 1.08 } : { y: 0, scale: 1 }}
            className="mb-4 grid size-14 place-items-center rounded-2xl bg-[linear-gradient(135deg,var(--brand),var(--purple))] text-white shadow-[0_12px_30px_-10px_var(--brand)]"
          >
            <Icon24UploadOutline width={28} height={28} />
          </motion.div>
          <div className="text-[15px] font-semibold">Перетащите шаблон .pptx</div>
          <div className="mt-1 text-[13px] text-fg-3">или нажмите, чтобы выбрать файл</div>
          <div className="mt-3 text-[12px] text-fg-4">Разбор занимает 10–90 с и выполняется один раз</div>
          {err && <div className="mt-3 rounded-lg bg-[color-mix(in_srgb,var(--red)_12%,transparent)] px-3 py-1.5 text-[12px] text-bad">{err}</div>}
        </>
      )}
    </div>
  );
}

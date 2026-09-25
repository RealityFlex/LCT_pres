import { useQuery } from "@tanstack/react-query";
import { Icon24ComputerOutline, Icon24PictureOutline, Icon24RobotOutline, Icon24ScanViewfinderOutline } from "@vkontakte/icons";
import { clsx } from "clsx";
import { useMemo, useState, type ReactNode } from "react";
import { Pipeline } from "../components/Pipeline";
import { Badge, LiveDot, Panel, Segmented, SectionHead } from "../components/ui";
import { api } from "../lib/api";

function Stat({ icon, title, value, ok, sub }: { icon: ReactNode; title: string; value: string; ok: boolean | null; sub?: string }) {
  return (
    <Panel className="p-5">
      <div className="mb-3 flex items-center gap-2 text-fg-3">
        <span className="text-accent">{icon}</span>
        <span className="flex-1 text-[13px] font-semibold">{title}</span>
        <LiveDot color={ok == null ? "var(--text-4)" : ok ? "var(--green)" : "var(--red)"} />
      </div>
      <div className="truncate font-mono text-[14px] font-semibold" title={value}>{value}</div>
      {sub && <div className="mt-1 text-[12px] text-fg-3">{sub}</div>}
    </Panel>
  );
}

export default function System() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const skills = useQuery({ queryKey: ["skills"], queryFn: api.skills });
  const checks = useQuery({ queryKey: ["checks"], queryFn: api.checks });
  const [kind, setKind] = useState<"all" | "det" | "vlm">("all");
  const h = health.data;
  const groups = useMemo(() => {
    const cs = (checks.data?.checks ?? []).filter((c) => kind === "all" || (kind === "det" ? c.deterministic : !c.deterministic));
    const by: Record<string, typeof cs> = {};
    for (const c of cs) (by[c.category] ??= []).push(c);
    return by;
  }, [checks.data, kind]);
  const nDet = (checks.data?.checks ?? []).filter((c) => c.deterministic).length;
  const nVlm = (checks.data?.checks ?? []).length - nDet;

  return (
    <div className="mx-auto max-w-[1360px] px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
      <div className="mb-8 max-w-3xl">
        <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">Система</div>
        <h1 className="font-display text-[30px] font-semibold tracking-tight sm:text-[38px]">Как устроен Лекало</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-fg-2 text-pretty">
          Прозрачные слои, версионируемые скиллы и аудит, встроенный в пайплайн. Всё, что влияет на результат, задаётся в
          <span className="font-mono text-[13px]"> config.yaml</span> и файлах скиллов.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat icon={<Icon24RobotOutline />} title="Языковая модель" value={h?.llm.model.split("/").slice(-2).join("/") ?? "—"} ok={h ? h.llm.configured : null} sub="сценарий, сокращение, исправления" />
        <Stat icon={<Icon24ScanViewfinderOutline />} title="VLM для аудита" value={h?.llm.vision.split("/").slice(-2).join("/") ?? "—"} ok={h ? h.llm.configured : null} sub="смысловые проверки по картинке слайда" />
        <Stat icon={<Icon24PictureOutline />} title="Иллюстрации" value={h?.images.provider ?? "—"} ok={h ? h.images.enabled : null} sub={h?.images.enabled ? "генерация включена" : "нет ключа — слайды без картинок"} />
        <Stat icon={<Icon24ComputerOutline />} title="Рендер" value={h?.soffice.split(/[\\/]/).slice(-3).join("/") ?? "—"} ok={h ? !h.soffice.startsWith("not") : null} sub={`бюджет колоды: ${h?.deadline_s ?? 300} с`} />
      </div>

      <section className="mt-14">
        <SectionHead eyebrow="Архитектура" title="Пайплайн генерации" />
        <Panel className="px-5 py-8 sm:px-8"><Pipeline /></Panel>
      </section>

      <section className="mt-14 grid gap-6 lg:grid-cols-2">
        <div>
          <SectionHead eyebrow="Варианты" title="Три способа вёрстки" />
          <div className="space-y-3">
            {(h?.variants ?? []).map((v) => (
              <Panel key={v.id} className="flex gap-4 p-5">
                <span className="grid size-11 shrink-0 place-items-center rounded-2xl bg-[linear-gradient(135deg,var(--brand),var(--purple))] font-display text-lg font-semibold text-white">{v.id}</span>
                <div>
                  <div className="flex items-center gap-2"><span className="text-[15px] font-semibold">{v.name}</span><Badge className="font-mono !text-[10px]">{v.strategy}</Badge></div>
                  <div className="mt-1 text-[13px] leading-relaxed text-fg-3">{v.description}</div>
                </div>
              </Panel>
            ))}
          </div>
        </div>
        <div>
          <SectionHead eyebrow="Скиллы" title="Версионируемые агенты" />
          <Panel className="divide-y divide-[var(--line)]">
            {(skills.data ?? []).map((s) => (
              <div key={s.name} className="px-5 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[14px] font-semibold">{s.name}</span>
                  <Badge tone="ok">активна {s.active}</Badge>
                  {s.versions.filter((x) => x !== s.active).map((x) => <Badge key={x} className="font-mono">{x}</Badge>)}
                </div>
                {s.description && <div className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-fg-3">{s.description}</div>}
              </div>
            ))}
          </Panel>
        </div>
      </section>

      <section className="mt-14">
        <SectionHead eyebrow="Аудит" title={`${nDet} детерминированных и ${nVlm} контекстных проверок`}
          action={<Segmented size="sm" value={kind} onChange={setKind} options={[{ value: "all", label: "Все" }, { value: "det", label: "Детерм." }, { value: "vlm", label: "VLM" }]} />} />
        <div className="grid gap-4 lg:grid-cols-2">
          {Object.entries(groups).map(([cat, cs]) => (
            <Panel key={cat} className="p-5">
              <div className="mb-3 font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-fg-4">{checks.data?.categories[cat] ?? cat}</div>
              <div className="space-y-3">
                {cs.map((c) => (
                  <div key={c.code} className="flex gap-3">
                    <span className={clsx("mt-1.5 size-2 shrink-0 rounded-full", c.deterministic ? "bg-accent" : "bg-purple")} />
                    <div className="min-w-0">
                      <div className="text-[14px] font-semibold">{c.title}</div>
                      <div className="mt-0.5 text-[12px] leading-relaxed text-fg-3">{c.how}</div>
                      <div className="mt-1 font-mono text-[10px] text-fg-4">{c.code} · {c.deterministic ? "детерминированная" : "VLM / LLM"}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          ))}
        </div>
      </section>
    </div>
  );
}

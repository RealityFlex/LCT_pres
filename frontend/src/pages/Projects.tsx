import { useQuery } from "@tanstack/react-query";
import { Icon24AddCircleOutline, Icon24ArticlesOutline, Icon24SearchOutline } from "@vkontakte/icons";
import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ProjectCard } from "../components/Cards";
import { Button, Empty, Segmented } from "../components/ui";
import { api } from "../lib/api";

type F = "all" | "done" | "running" | "error";

export default function Projects() {
  const nav = useNavigate();
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 5000 });
  const [q, setQ] = useState("");
  const [f, setF] = useState<F>("all");
  const list = useMemo(() => (jobs.data ?? []).filter((j) => {
    const okF = f === "all" || (f === "running" ? j.status === "running" || j.status === "queued" : j.status === f);
    const s = q.trim().toLowerCase();
    return okF && (!s || (j.title + " " + j.topic + " " + j.template_name).toLowerCase().includes(s));
  }), [jobs.data, q, f]);

  return (
    <div className="mx-auto max-w-[1360px] px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">Проекты</div>
          <h1 className="font-display text-[30px] font-semibold tracking-tight sm:text-[38px]">Ваши презентации</h1>
        </div>
        <Button variant="primary" glow onClick={() => nav("/new")} icon={<Icon24AddCircleOutline width={20} height={20} />}>Новая презентация</Button>
      </div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Icon24SearchOutline className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-fg-4" width={20} height={20} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск по теме, названию или шаблону" className="field !pl-11" />
        </div>
        <Segmented<F> value={f} onChange={setF} options={[
          { value: "all", label: "Все" },
          { value: "done", label: "Готовые" },
          { value: "running", label: "В работе" },
          { value: "error", label: "Ошибки" },
        ]} />
      </div>
      {jobs.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, k) => <div key={k} className="skeleton aspect-[4/3.4] rounded-[20px]" />)}
        </div>
      ) : list.length === 0 ? (
        <Empty icon={<Icon24ArticlesOutline width={32} height={32} />} title={jobs.data?.length ? "Ничего не найдено" : "Пока нет презентаций"}
          text="Выберите шаблон, опишите тему — через полминуты здесь появятся три варианта колоды."
          action={<Button variant="primary" onClick={() => nav("/new")}>Создать первую</Button>} />
      ) : (
        <motion.div layout className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {list.map((j, k) => (
            <motion.div key={j.id} layout initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(k, 12) * 0.03 }}>
              <ProjectCard j={j} />
            </motion.div>
          ))}
        </motion.div>
      )}
    </div>
  );
}

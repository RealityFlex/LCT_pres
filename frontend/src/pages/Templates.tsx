import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { useNavigate } from "react-router-dom";
import { Dropzone, TemplateCard } from "../components/Cards";
import { useToast } from "../components/ui";
import { api } from "../lib/api";

export default function Templates() {
  const nav = useNavigate();
  const toast = useToast();
  const tpls = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  return (
    <div className="mx-auto max-w-[1360px] px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
      <div className="mb-8 max-w-3xl">
        <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">Шаблоны</div>
        <h1 className="font-display text-[30px] font-semibold tracking-tight sm:text-[38px]">Библиотека дизайн-систем</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-fg-2 text-pretty">
          Каждый загруженный PPTX разбирается один раз: палитра, типографика, сетка, холсты-основы и формат повествования.
          Откройте шаблон, чтобы увидеть, что именно извлекла система.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Dropzone onReady={(id) => { toast({ tone: "ok", title: "Шаблон разобран" }); nav(`/templates/${id}`); }} />
        {tpls.isLoading && Array.from({ length: 3 }).map((_, k) => <div key={k} className="skeleton aspect-[4/3.3] rounded-[20px]" />)}
        {(tpls.data ?? []).map((t, k) => (
          <motion.div key={t.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * 0.05 }}>
            <TemplateCard t={t} to={`/templates/${t.id}`} />
          </motion.div>
        ))}
      </div>
    </div>
  );
}

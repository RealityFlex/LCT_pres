import { useQuery } from "@tanstack/react-query";
import { Icon24ArrowRightOutline, Icon24LogoVk } from "@vkontakte/icons";
import { motion } from "motion/react";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Dropzone, ProjectCard, TemplateCard } from "../components/Cards";
import { SlideStack } from "../components/SlideStack";
import { Button, CountUp, SectionHead } from "../components/ui";
import { api, url } from "../lib/api";

const fade = { initial: { opacity: 0, y: 18 }, animate: { opacity: 1, y: 0 } };

export default function Home() {
  const nav = useNavigate();
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs });
  const tpls = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });

  const heroImages = useMemo(() => {
    const done = (jobs.data ?? []).filter((j) => j.status === "done" && j.variants.length);
    const out: string[] = [];
    const j = done[0];
    if (j) {
      const v = j.variants[0];
      const picks = [1, 4, 6, 3].filter((n) => n <= v.n_slides);
      for (const n of picks) out.push(url(`/api/jobs/${j.id}/variants/${v.id}/slide/${n}.png?w=960`));
    }
    if (out.length < 3) for (const t of tpls.data ?? []) out.push(url(`${t.cover}?w=960`));
    return out.slice(0, 4).reverse();
  }, [jobs.data, tpls.data]);


  return (
    <div className="mx-auto max-w-[1360px] px-4 sm:px-6 lg:px-10">
      {/* ------------------------------------------------ HERO */}
      <section className="relative grid items-center gap-8 pb-10 pt-8 lg:min-h-[640px] lg:grid-cols-[1.05fr_1fr] lg:pt-14">
        <div className="relative z-10">
          <motion.div {...fade} transition={{ duration: 0.5 }}
            className="glass mb-6 inline-flex items-center gap-2 rounded-full py-1.5 pl-2 pr-3.5 text-[13px] font-medium">
            <span className="grid size-6 place-items-center rounded-full bg-brand text-white"><Icon24LogoVk width={16} height={16} /></span>
            <span className="text-fg-2">Для экосистемы VK</span>
          </motion.div>
          <motion.h1 {...fade} transition={{ duration: 0.6, delay: 0.05 }}
            className="font-display text-[38px] font-semibold leading-[1.04] tracking-[-0.025em] text-balance sm:text-[50px] xl:text-[58px]">
            Презентации в&nbsp;фирменном стиле{" "}
            <span className="gradient-text">за&nbsp;30&nbsp;секунд</span>
          </motion.h1>
          <motion.p {...fade} transition={{ duration: 0.6, delay: 0.12 }}
            className="mt-6 max-w-xl text-[17px] leading-relaxed text-fg-2 text-pretty sm:text-lg">
            Загрузите шаблон компании и опишите тему — получите три готовых варианта презентации в его стиле.
            PPTX остаётся полностью редактируемым.
          </motion.p>
          <motion.div {...fade} transition={{ duration: 0.6, delay: 0.2 }} className="mt-8 flex flex-wrap gap-3">
            <Button variant="primary" size="lg" glow onClick={() => nav("/new")} iconRight={<Icon24ArrowRightOutline width={20} height={20} />}>
              Создать презентацию
            </Button>
            <Button variant="outline" size="lg" onClick={() => nav("/projects")}>
              Мои проекты
            </Button>
          </motion.div>
          <motion.div {...fade} transition={{ duration: 0.6, delay: 0.3 }} className="mt-10 grid max-w-xl grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
            {[
              { v: 3, s: "", l: "варианта вёрстки" },
              { v: stats.data?.avg_seconds ?? 30, s: " с", l: "на три колоды" },
              { v: 15, s: "", l: "слайдов максимум" },
              { v: 3, s: "", l: "формата экспорта" },
            ].map((x) => (
              <div key={x.l}>
                <div className="font-display text-[28px] font-semibold tracking-tight">
                  <CountUp to={Number(x.v)} suffix={x.s} />
                </div>
                <div className="mt-0.5 text-[12px] leading-tight text-fg-3">{x.l}</div>
              </div>
            ))}
          </motion.div>
        </div>
        <motion.div initial={{ opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.9, delay: 0.1 }}>
          <SlideStack images={heroImages} className="mx-auto aspect-[1.1/1] w-full max-w-[680px] lg:scale-[1.08]" />
        </motion.div>
      </section>

      {/* ------------------------------------------------ БЫСТРЫЙ СТАРТ */}
      <section className="mt-6">
        <SectionHead eyebrow="Быстрый старт" title="Выберите шаблон — дальше всё сделает Лекало"
          action={<Link to="/templates" className="btn btn-ghost btn-sm">Все шаблоны <Icon24ArrowRightOutline width={16} height={16} /></Link>} />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {(tpls.data ?? []).slice(0, 3).map((t) => (
            <TemplateCard key={t.id} t={t} onClick={() => nav(`/new?template=${t.id}`)} />
          ))}
          <Dropzone compact onReady={(id) => nav(`/new?template=${id}`)} />
        </div>
      </section>

      {/* ------------------------------------------------ НЕДАВНИЕ */}
      {(jobs.data?.length ?? 0) > 0 && (
        <section className="mt-14">
          <SectionHead eyebrow="Проекты" title="Недавние презентации"
            action={<Link to="/projects" className="btn btn-ghost btn-sm">Все проекты <Icon24ArrowRightOutline width={16} height={16} /></Link>} />
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {(jobs.data ?? []).slice(0, 4).map((j) => <ProjectCard key={j.id} j={j} />)}
          </div>
        </section>
      )}

      <footer className="mb-6 mt-20 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-6 text-[12px] text-fg-4">
        <span>Лекало · цифровой дизайнер презентаций · ЛЦТ 2026</span>
      </footer>
    </div>
  );
}

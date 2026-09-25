import {
  Icon24BrushOutline,
  Icon24DownloadOutline,
  Icon24PaletteOutline,
  Icon24RobotOutline,
  Icon24ScanViewfinderOutline,
} from "@vkontakte/icons";
import { clsx } from "clsx";
import { motion } from "motion/react";
import type { ReactNode } from "react";

export const STEPS: { key: string; title: string; text: string; tech: string; icon: ReactNode; color: string }[] = [
  { key: "parse", title: "Парсинг шаблона", text: "Палитра, шрифты, шкала кеглей, сетка, холсты и нарратив — прямо из PPTX.", tech: "python-pptx · LibreOffice · VLM", icon: <Icon24PaletteOutline />, color: "var(--brand)" },
  { key: "plan", title: "Сценарий", text: "Структура, заголовки-выводы и тексты по брифу. Цифры — только из ваших данных.", tech: "Qwen3.6-35B · скилл deck_planner", icon: <Icon24RobotOutline />, color: "var(--purple)" },
  { key: "layout", title: "Вёрстка", text: "Рецепты раскладки по сетке шаблона, три варианта: классика, визуал, компакт.", tech: "композер · метрики шрифтов", icon: <Icon24BrushOutline />, color: "var(--pink)" },
  { key: "audit", title: "Аудит", text: "Детерминированные проверки по файлу и VLM-ревью каждого слайда по картинке.", tech: "26 правил + 11 вопросов VLM", icon: <Icon24ScanViewfinderOutline />, color: "var(--orange)" },
  { key: "export", title: "Экспорт", text: "Нативный PPTX: тексты, таблицы и диаграммы редактируются. Плюс PDF и HTML.", tech: "PPTX · PDF · HTML", icon: <Icon24DownloadOutline />, color: "var(--green)" },
];

export function Pipeline({ active, className }: { active?: string; className?: string }) {
  return (
    <div className={clsx("relative", className)}>
      {/* соединительная линия (десктоп) */}
      <svg className="pointer-events-none absolute left-[10%] right-[10%] top-[38px] hidden h-2 w-[80%] overflow-visible md:block" preserveAspectRatio="none" viewBox="0 0 100 2">
        <line x1="0" y1="1" x2="100" y2="1" stroke="var(--line-2)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <line x1="0" y1="1" x2="100" y2="1" stroke="url(#pl-g)" strokeWidth="2" className="flow-line" vectorEffect="non-scaling-stroke" />
        <defs>
          <linearGradient id="pl-g" x1="0" x2="1">
            <stop offset="0" stopColor="#0077FF" />
            <stop offset=".5" stopColor="#735CE6" />
            <stop offset="1" stopColor="#4BB34B" />
          </linearGradient>
        </defs>
      </svg>
      <motion.div
        className="pointer-events-none absolute top-[33px] hidden size-3 rounded-full bg-white shadow-[0_0_18px_4px_var(--brand)] md:block"
        initial={{ left: "10%" }}
        animate={{ left: ["10%", "89%"] }}
        transition={{ duration: 4.5, repeat: Infinity, ease: "easeInOut" }}
      />
      <div className="relative grid gap-4 md:grid-cols-5">
        {STEPS.map((s, i) => {
          const on = active === s.key;
          return (
            <motion.div
              key={s.key}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ delay: i * 0.08, duration: 0.5 }}
              className="flex gap-4 md:flex-col md:items-center md:text-center"
            >
              <div
                className={clsx("relative grid size-[76px] shrink-0 place-items-center rounded-[22px] border border-line bg-surface shadow-[var(--shadow-1)] transition-transform",
                  on && "scale-105")}
                style={{ color: s.color, boxShadow: on ? `0 0 0 4px color-mix(in srgb, ${s.color} 20%, transparent), var(--shadow-2)` : undefined }}
              >
                <div className="absolute inset-0 rounded-[22px] opacity-[0.14]" style={{ background: s.color }} />
                <span className="relative [&_svg]:!h-9 [&_svg]:!w-9">{s.icon}</span>
                <span className="absolute -right-2 -top-2 grid size-6 place-items-center rounded-full bg-surface font-mono text-[11px] font-semibold text-fg-2 ring-1 ring-[var(--line-2)]">{i + 1}</span>
              </div>
              <div className="min-w-0 md:mt-4">
                <div className="text-[15px] font-semibold">{s.title}</div>
                <div className="mt-1 text-[13px] leading-relaxed text-fg-3 text-pretty">{s.text}</div>
                <div className="mt-2 font-mono text-[11px] text-fg-4">{s.tech}</div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

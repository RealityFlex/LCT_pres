// Форматирование и справочники для интерфейса.

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

export const slidesWord = (n: number) => `${n} ${plural(n, "слайд", "слайда", "слайдов")}`;

export function clock(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function ago(ts: number): string {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "только что";
  if (d < 3600) return `${Math.floor(d / 60)} мин назад`;
  if (d < 86400) return `${Math.floor(d / 3600)} ч назад`;
  const dt = new Date(ts * 1000);
  return dt.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

export const RECIPES: Record<string, string> = {
  title: "Титул",
  section: "Раздел",
  section_synth: "Раздел",
  closing: "Финал",
  agenda: "План",
  cards: "Карточки",
  rows: "Строки",
  bullets: "Тезисы с иконками",
  process: "Процесс",
  timeline: "Таймлайн",
  stats: "Крупные цифры",
  chart: "Диаграмма",
  table: "Таблица",
  comparison: "Сравнение",
  quote: "Ключевая мысль",
  image_text: "Картинка и текст",
};

/** Подпись рецепта; «pattern:cards» — композиция, взятая из самого шаблона. */
export const recipeLabel = (r: string) =>
  r.startsWith("pattern:") ? `Паттерн шаблона · ${(RECIPES[r.slice(8)] ?? r.slice(8)).toLowerCase()}` : RECIPES[r] ?? r;

export const INTENTS: Record<string, string> = {
  title: "Титул",
  agenda: "План",
  section: "Раздел",
  bullets: "Тезисы",
  cards: "Карточки",
  process: "Процесс",
  timeline: "Таймлайн",
  stats: "Цифры",
  chart: "График",
  table: "Таблица",
  comparison: "Сравнение",
  quote: "Мысль",
  image: "Иллюстрация",
  closing: "Финал",
};

export const CATEGORY: Record<string, string> = {
  layout: "Вёрстка",
  template: "Шаблон",
  density: "Плотность",
  integrity: "Целостность",
  content: "Смысл",
};

export const SEVERITY: Record<string, { label: string; color: string }> = {
  error: { label: "Ошибка", color: "var(--red)" },
  warning: { label: "Замечание", color: "var(--orange)" },
  info: { label: "Совет", color: "var(--accent)" },
};

export const CANVAS_KIND: Record<string, string> = {
  title: "Титул",
  section: "Раздел",
  closing: "Финал",
  agenda: "План",
  content: "Контент",
};

export const ROLE: Record<string, string> = {
  bg_light: "Фон",
  bg_dark: "Тёмный фон",
  text: "Текст",
  primary: "Основной",
  accent: "Акцент",
  other: "Доп.",
};

export const PURPOSES = [
  { id: "проект", label: "Проект" },
  { id: "продукт", label: "Продукт" },
  { id: "фича", label: "Фича" },
  { id: "инициатива", label: "Инициатива" },
  { id: "обучение", label: "Обучение" },
  { id: "другое", label: "Другое" },
];

export const AUDIENCES = ["Совет директоров", "Команда продукта", "Клиенты", "Инвесторы", "Новые сотрудники", "Студенты"];

export function countNumbers(text: string): number {
  return (text.match(/\d+(?:[.,]\d+)?/g) ?? []).length;
}

export function isDark(hex: string): boolean {
  const h = hex.replace("#", "");
  if (h.length < 6) return false;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 140;
}

export const hex = (c: string | null | undefined) => (c ? (c.startsWith("#") ? c : `#${c}`) : "transparent");

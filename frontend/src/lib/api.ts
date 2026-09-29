// Типизированный клиент API сервиса. База — VITE_API (для хостинга мини-приложения) или тот же origin.
export const API_BASE: string = (import.meta.env.VITE_API as string | undefined)?.replace(/\/$/, "") ?? "";

export const url = (path: string) => (path.startsWith("http") ? path : `${API_BASE}${path}`);

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url(path), {
    ...init,
    headers: init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* пустое тело */
    }
    throw new ApiError(r.status, msg);
  }
  return (await r.json()) as T;
}

// ------------------------------------------------------------------ типы
export type VariantDef = { id: string; name: string; strategy: string; description: string };

export type Health = {
  ok: boolean;
  llm: { configured: boolean; model: string; vision: string };
  images: { enabled: boolean; provider: string };
  soffice: string;
  variants: VariantDef[];
  deadline_s: number;
};

export type TemplateSummary = {
  id: string;
  name: string;
  n_slides: number;
  slide_w: number;
  slide_h: number;
  aspect: number;
  primary: string;
  colors: string[];
  fonts: string[];
  canvases: number;
  content_canvases: number;
  parse_seconds: number;
  cover: string;
};

export type TextStyle = { font: string; size: number; color: string; bold: boolean; caps: boolean; line_spacing?: number };
export type Box = { x: number; y: number; w: number; h: number };
export type PaletteColor = { hex: string; weight: number; role: string; sources?: Record<string, number> };
export type Palette = {
  colors: PaletteColor[];
  bg_light: string;
  bg_dark: string;
  text_dark: string;
  text_light: string;
  muted_dark: string;
  muted_light: string;
  primary: string;
  accents: string[];
  chart: string[];
  surface: string | null;
};
export type CanvasInfo = {
  id: string;
  kind: string;
  dark: boolean;
  clean: boolean;
  score: number;
  layout: string;
  slots: string[];
  dirty_reason: string | null;
  content_box: Box;
  preview: string;
};
export type TemplateSlide = {
  index: number;
  kind: string;
  service: boolean;
  service_reason: string | null;
  layout: string;
  title: string;
  groups: number[];
  preview: string;
};
export type Narrative = {
  has_agenda: boolean;
  has_sections: boolean;
  closing: string;
  title_caps: boolean;
  uses_kicker: boolean;
  kicker_example: string | null;
  numbering: boolean;
  avg_title_words: number;
  sequence: string[];
  tone: string;
};
export type TemplateDetail = TemplateSummary & {
  palette: Palette;
  typography: Record<string, TextStyle | null>;
  scale: number[];
  title_caps: boolean;
  margins: Box;
  gap: number;
  narrative: Narrative;
  style_summary: string;
  image_style: string;
  fonts_found: Record<string, boolean>;
  card_styles: { fill: string | null; line: string | null; accent: boolean; geom: string }[];
  canvas_list: CanvasInfo[];
  slides: TemplateSlide[];
};

export type ParseStatus = { status: "parsing" | "ready" | "error"; progress: number; message: string };

export type Brief = {
  topic: string;
  purpose: string;
  audience: string;
  details: string;
  slide_count: number | null;
  duration_min: number | null;
  author: string;
  language: string;
  images: "auto" | "on" | "off";
};

export type JobEvent = {
  t: number;
  stage: string;
  message: string;
  progress: number;
  variant?: string;
  slides?: { id: string; intent: string; title: string }[];
};

export type AuditSummary = { error?: number; warning?: number; info?: number };

export type VariantState = {
  id: string;
  name: string;
  strategy: string;
  description: string;
  status: string;
  n_slides: number;
  audit: AuditSummary;
  files: Record<string, string>;
  seconds: number;
  revision: number;
};

export type Job = {
  id: string;
  template_id: string;
  brief: Brief;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  progress: number;
  events: JobEvent[];
  error: string | null;
  created: number;
  finished: number | null;
  variants: VariantState[];
  skills: Record<string, string>;
  llm_stats: Record<string, number>;
  title: string;
};

export type JobCard = {
  id: string;
  title: string;
  topic: string;
  purpose: string;
  status: Job["status"];
  stage: string;
  progress: number;
  template_id: string;
  template_name: string;
  created: number;
  finished: number | null;
  seconds: number | null;
  variants: { id: string; name: string; n_slides: number; audit: AuditSummary }[];
  cover: string | null;
  error: string | null;
};

export type Issue = {
  id: string;
  check: string;
  title: string;
  category: string;
  severity: "error" | "warning" | "info";
  deterministic: boolean;
  slide: number;
  message: string;
  bbox: number[] | null;
  element: string | null;
  fix: Record<string, unknown> | null;
  fixable: boolean;
};

export type AuditReport = {
  variant: string;
  issues: Issue[];
  checks_run: string[];
  stats: Record<string, unknown>;
  seconds: number;
};

export type SlideItem = {
  index: number;
  title: string;
  recipe: string;
  intent: string;
  canvas: string;
  notes: string;
  image: string;
  thumb: string;
};

export type VariantData = {
  variant: VariantState | null;
  slides: SlideItem[];
  audit: AuditReport | null;
  slide_w: number;
  slide_h: number;
};

export type Skill = { name: string; versions: string[]; active: string; description: string };
export type Check = { code: string; title: string; category: string; deterministic: boolean; how: string };
export type Stats = { templates: number; projects: number; done: number; avg_seconds: number | null; slides: number };
export type Example = Brief & { id: string; title_hint?: string };

export type Material = { name: string; chars?: number; text?: string; error?: string };

export type FixResult = { revision: number; changed: number[]; log: string[]; audit: AuditReport };

// ------------------------------------------------------------------ методы
export const api = {
  health: () => req<Health>("/api/health"),
  stats: () => req<Stats>("/api/stats"),
  skills: () => req<Skill[]>("/api/skills"),
  checks: () => req<{ checks: Check[]; categories: Record<string, string> }>("/api/audit/checks"),
  examples: () => req<Example[]>("/api/examples"),

  templates: () => req<TemplateSummary[]>("/api/templates"),
  template: (id: string) => req<TemplateDetail>(`/api/templates/${id}`),
  templateStatus: (id: string) => req<ParseStatus>(`/api/templates/${id}/status`),
  uploadTemplate: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ id: string; status: string }>("/api/templates", { method: "POST", body: fd });
  },
  deleteTemplate: (id: string) => req<{ ok: boolean }>(`/api/templates/${id}`, { method: "DELETE" }),

  jobs: () => req<JobCard[]>("/api/jobs"),
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  createJob: (template_id: string, brief: Brief, materials: Material[] = []) =>
    req<{ id: string }>("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ template_id, brief, materials: materials.filter((m) => m.text).map((m) => ({ name: m.name, text: m.text })) }),
    }),
  materials: (files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return req<{ files: Material[]; limit: number }>("/api/materials", { method: "POST", body: fd });
  },
  deleteJob: (id: string) => req<{ ok: boolean }>(`/api/jobs/${id}`, { method: "DELETE" }),
  rerun: (id: string, template_id?: string, reuse_content = true) =>
    req<{ id: string }>(`/api/jobs/${id}/rerun`, { method: "POST", body: JSON.stringify({ template_id, reuse_content }) }),
  variant: (id: string, vid: string) => req<VariantData>(`/api/jobs/${id}/variants/${vid}`),
  fix: (id: string, vid: string, issue_ids: string[]) =>
    req<FixResult>(`/api/jobs/${id}/variants/${vid}/fix`, { method: "POST", body: JSON.stringify({ issue_ids }) }),
};

export const downloadUrl = (id: string, vid: string, fmt: "pptx" | "pdf" | "html", inline = false) =>
  url(`/api/jobs/${id}/variants/${vid}/download/${fmt}${inline ? "?inline=true" : ""}`);

export const withW = (path: string, w: number) => url(path + (path.includes("?") ? "&" : "?") + `w=${w}`);

// Client for the local Forte Vision service. No third-party calls.
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export type JobStatus = "processing" | "done" | "failed";
export type Verdict = "no_violation" | "violation";

export interface EventSource {
  title?: string;
  document?: string;
  section?: string;
  clause?: string;
  url?: string;
}

export interface JobEvent {
  type?: string;
  timestamp?: number | string;
  time?: number | string;
  description?: string;
  frames?: string[];
  source?: EventSource | null;
}

export interface JobResponse {
  job_id: string;
  status: JobStatus | string;
  stage?: string;
  progress?: number;
  verdict?: Verdict;
  events?: JobEvent[];
  error?: string;
}

export class ApiError extends Error {
  constructor(message: string, public kind: "network" | "http" | "timeout" | "format") {
    super(message);
  }
}

export const MAX_POLL_MS = 5 * 60 * 1000;
export const POLL_INTERVAL_MS = 2000;

export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!name.endsWith(".mov")) return "Неподдерживаемый формат. Загрузите один файл в формате .mov.";
  if (file.size === 0) return "Файл пустой. Выберите другое видео.";
  return null;
}

export const VERDICT_LABEL: Record<Verdict, string> = {
  no_violation: "Нарушение не обнаружено",
  violation: "Обнаружены признаки возможных нарушений",
};

export function parseSeconds(v: number | string | undefined): number | null {
  if (v === undefined || v === null || v === "") return null;
  if (typeof v === "number") return isFinite(v) ? v : null;
  if (/^\d+(\.\d+)?$/.test(v)) return Number(v);
  const parts = v.split(":").map(Number);
  if (parts.some((p) => isNaN(p))) return null;
  return parts.reduce((acc, p) => acc * 60 + p, 0);
}

export function formatTime(sec: number): string {
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(r).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function resolveAssetUrl(src: string): string {
  if (/^(https?:|data:|blob:)/i.test(src)) return src;
  return `${API_BASE}${src.startsWith("/") ? "" : "/"}${src}`;
}

export function isSafeHttpUrl(url?: string): boolean {
  if (!url) return false;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:";
  } catch {
    return false;
  }
}

const unreachable = () =>
  new ApiError(
    `Локальный сервис анализа недоступен по адресу «${API_BASE || window.location.origin}». Проверьте, что сервис запущен, и задайте адрес через переменную VITE_API_BASE_URL.`,
    "network",
  );

async function readError(res: Response): Promise<string> {
  try {
    const t = await res.text();
    try {
      const j = JSON.parse(t);
      return j.detail || j.error || j.message || t;
    } catch {
      return t;
    }
  } catch {
    return "";
  }
}

export function uploadVideo(
  file: File,
  onProgress: (pct: number) => void,
  signal: AbortSignal,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/ui/analyze`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onerror = () => reject(unreachable());
    xhr.onabort = () => reject(new DOMException("Aborted", "AbortError"));
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        let msg = xhr.responseText;
        try { const j = JSON.parse(msg); msg = j.detail || j.error || j.message || msg; } catch { /* text */ }
        return reject(new ApiError(`Сервис вернул ошибку ${xhr.status}${msg ? `: ${msg}` : ""}`, "http"));
      }
      try {
        const j = JSON.parse(xhr.responseText);
        if (!j.job_id) throw new Error();
        resolve(String(j.job_id));
      } catch {
        reject(new ApiError("Сервис ответил без job_id. Проверьте адрес сервиса.", "format"));
      }
    };
    signal.addEventListener("abort", () => xhr.abort());
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

export async function getJob(jobId: string, signal: AbortSignal): Promise<JobResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/ui/jobs/${encodeURIComponent(jobId)}`, { signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw unreachable();
  }
  if (!res.ok) {
    const msg = await readError(res);
    throw new ApiError(`Сервис вернул ошибку ${res.status}${msg ? `: ${msg}` : ""}`, "http");
  }
  try {
    return (await res.json()) as JobResponse;
  } catch {
    throw new ApiError("Ответ сервиса не является JSON. Проверьте адрес сервиса.", "format");
  }
}

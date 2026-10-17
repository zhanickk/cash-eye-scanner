// Client for the local Forte Vision service. No third-party calls.
export const API_BASE = (import.meta.env["VITE_API_BASE_URL"] ?? "").replace(/\/$/, "");

export type JobStatus = "processing" | "done" | "failed";
export type Verdict = "no_violation" | "violation";

export interface EvidenceFrame {
  timestamp_sec: number;
  image_base64: string;
}

export interface RuleReference {
  title: string | null;
  section: string | null;
  url: string | null;
  status: string;
}

export interface Violation {
  type: string;
  timecode_sec: number;
  description: string;
  evidence_frames: EvidenceFrame[];
  rule?: RuleReference;
}

export interface JobResponse {
  job_id: string;
  status: JobStatus;
  stage?: string;
  progress?: number;
  verdict?: Verdict;
  violations?: Violation[];
  error?: string;
  review_required?: boolean;
  limitations?: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseJobResponse(value: unknown): JobResponse {
  if (!isRecord(value) || typeof value.job_id !== "string" ||
      !["processing", "done", "failed"].includes(String(value.status))) throw new TypeError("Invalid job response");
  if (value.verdict !== undefined && value.verdict !== "no_violation" && value.verdict !== "violation") throw new TypeError("Invalid verdict");
  if (value.progress !== undefined && (typeof value.progress !== "number" || !Number.isFinite(value.progress))) throw new TypeError("Invalid progress");
  if (value.stage !== undefined && typeof value.stage !== "string") throw new TypeError("Invalid stage");
  if (value.error !== undefined && typeof value.error !== "string") throw new TypeError("Invalid error");
  let violations: Violation[] | undefined;
  if (value.violations !== undefined) {
    if (!Array.isArray(value.violations)) throw new TypeError("Invalid violations");
    violations = value.violations.map((item): Violation => {
      if (!isRecord(item) || typeof item.type !== "string" || typeof item.description !== "string" ||
          typeof item.timecode_sec !== "number" || !Number.isFinite(item.timecode_sec) || item.timecode_sec < 0 ||
          !Array.isArray(item.evidence_frames) || item.evidence_frames.length < 1 || item.evidence_frames.length > 3) throw new TypeError("Invalid violation");
      const evidence_frames = item.evidence_frames.map((frame): EvidenceFrame => {
        if (!isRecord(frame) || typeof frame.timestamp_sec !== "number" ||
            !Number.isFinite(frame.timestamp_sec) || frame.timestamp_sec < 0 ||
            typeof frame.image_base64 !== "string") throw new TypeError("Invalid evidence frame");
        return { timestamp_sec: frame.timestamp_sec, image_base64: frame.image_base64 };
      });
      let rule: RuleReference | undefined;
      if (isRecord(item.rule)) {
        const ref = item.rule;
        rule = { title: typeof ref.title === "string" ? ref.title : null,
          section: typeof ref.section === "string" ? ref.section : null,
          url: typeof ref.url === "string" && isSafeHttpUrl(ref.url) ? ref.url : null,
          status: typeof ref.status === "string" ? ref.status : "unverified" };
      }
      return { type: item.type, timecode_sec: item.timecode_sec, description: item.description, evidence_frames, ...(rule ? { rule } : {}) };
    });
  }
  if (value.status === "done" && (value.verdict === undefined || violations === undefined)) throw new TypeError("Completed jobs require verdict and violations");
  if (value.status === "done" && value.verdict !== (violations?.length ? "violation" : "no_violation")) throw new TypeError("Verdict disagrees with violations");
  return {
    job_id: value.job_id, status: value.status as JobStatus,
    ...(typeof value.stage === "string" ? { stage: value.stage } : {}),
    ...(typeof value.progress === "number" ? { progress: value.progress } : {}),
    ...(value.verdict ? { verdict: value.verdict as Verdict } : {}),
    ...(violations ? { violations } : {}),
    ...(typeof value.error === "string" ? { error: value.error } : {}),
    ...(typeof value.review_required === "boolean" ? { review_required: value.review_required } : {}),
    ...(Array.isArray(value.limitations) && value.limitations.every(x => typeof x === "string") ? { limitations: value.limitations as string[] } : {}),
  };
}

export function frameDataUrl(imageBase64: string): string {
  const header = imageBase64.slice(0, imageBase64.indexOf(",")).toLowerCase();
  return header.startsWith("data:image/") && header.endsWith(";base64")
    ? imageBase64
    : "data:image/jpeg;base64," + imageBase64;
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

export async function uploadVideo(
  file: File,
  onProgress: (pct: number) => void,
  signal: AbortSignal,
): Promise<string> {
  const session = await uiToken(signal);
  if (signal.aborted) throw new DOMException("Aborted", "AbortError");
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/ui/analyze`);
    xhr.setRequestHeader("X-UI-Session", session);
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
    res = await fetch(`${API_BASE}/ui/jobs/${encodeURIComponent(jobId)}`, { signal, headers: { "X-UI-Session": await uiToken(signal) } });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw unreachable();
  }
  if (!res.ok) {
    const msg = await readError(res);
    throw new ApiError(`Сервис вернул ошибку ${res.status}${msg ? `: ${msg}` : ""}`, "http");
  }
  let payload: unknown;
  try {
    payload = await res.json();
  } catch {
    throw new ApiError("Ответ сервиса не является JSON. Проверьте адрес сервиса.", "format");
  }
  try {
    return parseJobResponse(payload);
  } catch {
    throw new ApiError("Ответ сервиса не соответствует формату API. Проверьте схему ответа.", "format");
  }
}

// Browser sessions scope UI jobs without embedding the jury key in the bundle.
let sessionToken: string | null = null;
async function uiToken(signal: AbortSignal): Promise<string> {
  if (sessionToken) return sessionToken;
  let response: Response;
  try { response = await fetch(`${API_BASE}/ui/session`, { signal }); }
  catch (error) { if ((error as Error).name === "AbortError") throw error; throw unreachable(); }
  if (!response.ok) throw new ApiError("Не удалось создать сессию интерфейса", "http");
  const value: unknown = await response.json();
  if (!isRecord(value) || typeof value.session_token !== "string") throw new ApiError("Сервис не вернул сессию интерфейса", "format");
  sessionToken = value.session_token;
  return sessionToken;
}

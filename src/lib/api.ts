// Client for the local Forte Vision service. No third-party calls.
const DEFAULT_API_BASE = "https://pl9lv4603tade1-8000.proxy.runpod.net";
const API_BASE_STORAGE_KEY = "forte_api_base_url";

export function getApiBase(): string {
  let configured = "";
  try {
    configured = typeof window !== "undefined" ? window.localStorage.getItem(API_BASE_STORAGE_KEY)?.trim() ?? "" : "";
  } catch {
    // Storage may be disabled by browser privacy settings; keep the configured defaults usable.
  }
  return (configured || import.meta.env["VITE_API_BASE_URL"] || DEFAULT_API_BASE).replace(/\/$/, "");
}

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
  if (!isRecord(value)) throw new TypeError("Invalid job response");
  const job_id = value["job_id"];
  const status = value["status"];
  const verdict = value["verdict"];
  const progress = value["progress"];
  const stage = value["stage"];
  const error = value["error"];
  const review_required = value["review_required"];
  const limitations = value["limitations"];
  const raw_violations = value["violations"];
  if (typeof job_id !== "string" ||
      !["processing", "done", "failed"].includes(String(status))) throw new TypeError("Invalid job response");
  if (verdict !== undefined && verdict !== "no_violation" && verdict !== "violation") throw new TypeError("Invalid verdict");
  if (progress !== undefined && (typeof progress !== "number" || !Number.isFinite(progress))) throw new TypeError("Invalid progress");
  if (stage !== undefined && typeof stage !== "string") throw new TypeError("Invalid stage");
  if (error !== undefined && typeof error !== "string") throw new TypeError("Invalid error");
  let violations: Violation[] | undefined;
  if (raw_violations !== undefined) {
    if (!Array.isArray(raw_violations)) throw new TypeError("Invalid violations");
    violations = raw_violations.map((item): Violation => {
      if (!isRecord(item)) throw new TypeError("Invalid violation");
      const type = item["type"];
      const description = item["description"];
      const timecode_sec = item["timecode_sec"];
      const raw_frames = item["evidence_frames"];
      if (typeof type !== "string" || typeof description !== "string" ||
          typeof timecode_sec !== "number" || !Number.isFinite(timecode_sec) || timecode_sec < 0 ||
          !Array.isArray(raw_frames) || raw_frames.length < 1 || raw_frames.length > 3) throw new TypeError("Invalid violation");
      const evidence_frames = raw_frames.map((frame): EvidenceFrame => {
        if (!isRecord(frame)) throw new TypeError("Invalid evidence frame");
        const timestamp_sec = frame["timestamp_sec"];
        const image_base64 = frame["image_base64"];
        if (typeof timestamp_sec !== "number" ||
            !Number.isFinite(timestamp_sec) || timestamp_sec < 0 ||
            typeof image_base64 !== "string") throw new TypeError("Invalid evidence frame");
        return { timestamp_sec, image_base64 };
      });
      let rule: RuleReference | undefined;
      const raw_rule = item["rule"];
      if (isRecord(raw_rule)) {
        const title = raw_rule["title"];
        const section = raw_rule["section"];
        const url = raw_rule["url"];
        const rule_status = raw_rule["status"];
        rule = { title: typeof title === "string" ? title : null,
          section: typeof section === "string" ? section : null,
          url: typeof url === "string" && isSafeHttpUrl(url) ? url : null,
           status: typeof rule_status === "string" ? rule_status : "unverified" };
      }
      return { type, timecode_sec, description, evidence_frames, ...(rule ? { rule } : {}) };
    });
  }
  if (status === "done" && (verdict === undefined || violations === undefined)) throw new TypeError("Completed jobs require verdict and violations");
  if (status === "done" && verdict !== (violations?.length ? "violation" : "no_violation")) throw new TypeError("Verdict disagrees with violations");
  return {
    job_id, status: status as JobStatus,
    ...(typeof stage === "string" ? { stage } : {}),
    ...(typeof progress === "number" ? { progress } : {}),
    ...(verdict ? { verdict: verdict as Verdict } : {}),
    ...(violations ? { violations } : {}),
    ...(typeof error === "string" ? { error } : {}),
    ...(typeof review_required === "boolean" ? { review_required } : {}),
    ...(Array.isArray(limitations) && limitations.every(x => typeof x === "string") ? { limitations: limitations as string[] } : {}),
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
  return `${getApiBase()}${src.startsWith("/") ? "" : "/"}${src}`;
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
    `Локальный сервис анализа недоступен по адресу «${getApiBase() || window.location.origin}». Проверьте, что Pod запущен и адрес сервера указан в разделе «Обучение модели».`,
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
    xhr.open("POST", `${getApiBase()}/ui/analyze`);
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
    res = await fetch(`${getApiBase()}/ui/jobs/${encodeURIComponent(jobId)}`, { signal, headers: { "X-UI-Session": await uiToken(signal) } });
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
  try { response = await fetch(`${getApiBase()}/ui/session`, { signal }); }
  catch (error) { if ((error as Error).name === "AbortError") throw error; throw unreachable(); }
  if (!response.ok) throw new ApiError("Не удалось создать сессию интерфейса", "http");
  const value: unknown = await response.json();
  const token = isRecord(value) ? value["session_token"] : undefined;
  if (typeof token !== "string") throw new ApiError("Сервис не вернул сессию интерфейса", "format");
  sessionToken = token;
  return sessionToken;
}

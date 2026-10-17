import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import {
  ApiError, MAX_POLL_MS, POLL_INTERVAL_MS, VERDICT_LABEL, formatTime, frameDataUrl, getJob,
  parseSeconds, uploadVideo, validateFile, type Violation, type JobResponse,
} from "@/lib/api";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Forte Vision — проверка видео кассовых операций" },
      { name: "description", content: "Загрузите видео .mov кассовой операции и получите подсказку о возможных нарушениях для проверки сотрудником." },
      { property: "og:title", content: "Forte Vision — проверка видео кассовых операций" },
      { property: "og:description", content: "Операторский инструмент для анализа видео кассовых операций." },
    ],
  }),
  component: Index,
});

type Phase =
  | { kind: "idle" }
  | { kind: "uploading"; pct: number }
  | { kind: "queued"; jobId: string }
  | { kind: "analyzing"; jobId: string; progress?: number | undefined }
  | { kind: "done"; job: JobResponse }
  | { kind: "failed"; message: string; network?: boolean };

function Index() {
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [dragOver, setDragOver] = useState(false);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!file) { setVideoUrl(null); return; }
    const u = URL.createObjectURL(file);
    setVideoUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const pick = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (files.length > 1) { setFileError("Можно загрузить только один файл."); return; }
    const err = validateFile(files[0]!);
    setFileError(err);
    if (!err) { setFile(files[0]!); setPhase({ kind: "idle" }); }
  };

  const start = useCallback(async () => {
    if (!file) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      setPhase({ kind: "uploading", pct: 0 });
      const jobId = await uploadVideo(file, (pct) => setPhase({ kind: "uploading", pct }), ac.signal);
      setPhase({ kind: "queued", jobId });
      const started = Date.now();
      while (!ac.signal.aborted) {
        if (Date.now() - started > MAX_POLL_MS) throw new ApiError("Анализ занял больше 5 минут. Попробуйте ещё раз позже.", "timeout");
        const job = await getJob(jobId, ac.signal);
        if (job.status === "done") { setPhase({ kind: "done", job }); return; }
        if (job.status === "failed") { setPhase({ kind: "failed", message: job.error || "Сервис не смог обработать видео." }); return; }
        const queued = job.stage === "queued" || job.status === "queued";
        setPhase(queued ? { kind: "queued", jobId } : { kind: "analyzing", jobId, progress: job.progress });
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setPhase({ kind: "failed", message: (e as Error).message, network: e instanceof ApiError && e.kind === "network" });
    }
  }, [file]);

  const cancel = () => { abortRef.current?.abort(); setPhase({ kind: "idle" }); };
  const reset = () => { abortRef.current?.abort(); setPhase({ kind: "idle" }); setFile(null); setFileError(null); };
  const seek = (sec: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = sec;
    v.scrollIntoView({ behavior: "smooth", block: "center" });
    v.focus();
  };

  const busy = phase.kind === "uploading" || phase.kind === "queued" || phase.kind === "analyzing";

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="mx-auto max-w-5xl space-y-6 px-4 py-8 sm:px-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Проверка видео кассовой операции</h1>
          <p className="mt-1.5 text-muted-foreground">Загрузите запись — система подсветит моменты, которые стоит проверить.</p>
        </div>

        {!file && (
          <section className="card-surface p-4 sm:p-6" aria-label="Загрузка видео">
            <div
              role="button"
              tabIndex={0}
              aria-describedby="fmt-hint"
              onClick={() => inputRef.current?.click()}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), inputRef.current?.click())}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); pick(e.dataTransfer.files); }}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-14 text-center transition-colors focus-visible:outline-2 focus-visible:outline-ring ${dragOver ? "border-primary bg-accent" : "border-input hover:border-primary/60 hover:bg-muted"}`}
            >
              <svg aria-hidden width="40" height="40" viewBox="0 0 24 24" fill="none" className="text-primary" stroke="currentColor" strokeWidth="1.6"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" strokeLinejoin="round"/></svg>
              <p className="mt-4 font-semibold">Перетащите видео сюда или <span className="text-primary underline underline-offset-4">выберите файл</span></p>
              <p id="fmt-hint" className="mt-1 text-sm text-muted-foreground">Один файл в формате .mov</p>
            </div>
            <input ref={inputRef} type="file" accept=".mov,video/quicktime" className="sr-only" aria-label="Выбрать видео .mov" onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
            {fileError && <p role="alert" className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">{fileError}</p>}
          </section>
        )}

        {file && (
          <section className="card-surface overflow-hidden" aria-label="Выбранное видео">
            <div className="grid gap-0 md:grid-cols-[1.2fr_1fr]">
              {videoUrl && (
                <video ref={videoRef} src={videoUrl} controls tabIndex={-1} aria-label={`Видео ${file.name}`} className="aspect-video w-full bg-foreground" />
              )}
              <div className="flex flex-col gap-4 p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-semibold" title={file.name}>{file.name}</p>
                    <p className="text-sm text-muted-foreground">{(file.size / 1024 / 1024).toFixed(1)} МБ</p>
                  </div>
                  {!busy && (
                    <button onClick={reset} className="rounded-lg px-2.5 py-1.5 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-destructive focus-visible:outline-2 focus-visible:outline-ring" aria-label="Удалить выбранный файл">Удалить</button>
                  )}
                </div>
                <StatusBlock phase={phase} />
                <div className="mt-auto flex flex-wrap gap-2">
                  {phase.kind === "idle" && <PrimaryBtn onClick={start}>Начать проверку</PrimaryBtn>}
                  {busy && <SecondaryBtn onClick={cancel}>Отменить ожидание</SecondaryBtn>}
                  {phase.kind === "failed" && <PrimaryBtn onClick={start}>Повторить</PrimaryBtn>}
                  {(phase.kind === "done" || phase.kind === "failed" || busy) && <SecondaryBtn onClick={reset}>Новая проверка</SecondaryBtn>}
                </div>
              </div>
            </div>
          </section>
        )}

        {phase.kind === "done" && <Result job={phase.job} onSeek={seek} />}

        <details className="card-surface group p-5">
          <summary className="cursor-pointer list-none font-semibold focus-visible:outline-2 focus-visible:outline-ring">
            <span className="inline-block transition-transform group-open:rotate-90" aria-hidden>›</span> API для жюри
          </summary>
          <p className="mt-3 text-sm text-muted-foreground">
            <code>POST /api/v1/analyze</code> (поле <code>file</code>) и <code>GET /api/v1/jobs/{"{job_id}"}</code> с заголовком <code>X-API-Key</code>.{" "}
            <Link to="/api-docs" className="font-medium text-primary underline underline-offset-4">Подробнее и пример ответа</Link>
          </p>
        </details>
      </main>
    </div>
  );
}

function PrimaryBtn(p: { onClick: () => void; children: React.ReactNode }) {
  return <button onClick={p.onClick} className="rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">{p.children}</button>;
}
function SecondaryBtn(p: { onClick: () => void; children: React.ReactNode }) {
  return <button onClick={p.onClick} className="rounded-xl border border-input bg-card px-5 py-2.5 text-sm font-semibold hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">{p.children}</button>;
}

const STEPS = ["Загружаем", "Видео в очереди", "Идёт анализ", "Готово"];

function StatusBlock({ phase }: { phase: Phase }) {
  if (phase.kind === "idle") return <p className="text-sm text-muted-foreground">Файл готов к проверке.</p>;
  if (phase.kind === "failed")
    return (
      <div role="alert" className="rounded-xl bg-destructive/10 p-3 text-sm">
        <p className="font-semibold text-destructive">Не удалось обработать</p>
        <p className="mt-1 break-words text-foreground">{phase.message}</p>
        {phase.network && <p className="mt-1 text-muted-foreground">Текущий адрес сервиса: <code>{import.meta.env["VITE_API_BASE_URL"] || "относительный путь (тот же сервер)"}</code></p>}
      </div>
    );
  const idx = phase.kind === "uploading" ? 0 : phase.kind === "queued" ? 1 : phase.kind === "analyzing" ? 2 : 3;
  const pct = phase.kind === "uploading" ? phase.pct : phase.kind === "analyzing" ? phase.progress : undefined;
  return (
    <div aria-live="polite">
      <p className="font-semibold">{STEPS[idx]}{idx < 3 && "…"}</p>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={STEPS[idx]} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <div className={`h-full rounded-full bg-primary transition-all ${pct === undefined && idx < 3 ? "w-1/3 animate-pulse" : ""}`} style={pct !== undefined ? { width: `${pct}%` } : idx === 3 ? { width: "100%" } : undefined} />
      </div>
      <ol className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {STEPS.map((s, i) => <li key={s} className={i <= idx ? "font-semibold text-foreground" : "text-muted-foreground"}>{i < idx ? "✓ " : ""}{s}</li>)}
      </ol>
      {idx < 3 && <p className="mt-2 text-xs text-muted-foreground">Можно не ждать на этой странице — отмените ожидание в любой момент.</p>}
    </div>
  );
}

function Result({ job, onSeek }: { job: JobResponse; onSeek: (s: number) => void }) {
  const violations = job.violations ?? [];
  const violation = job.verdict === "violation";
  const label = job.verdict ? VERDICT_LABEL[job.verdict] : "Вердикт не получен от сервиса";
  return (
    <section aria-labelledby="res-title" className="space-y-4">
      <div className={`rounded-2xl border p-5 ${violation ? "border-warning/30 bg-warning-soft" : job.verdict ? "border-success/30 bg-success-soft" : "border-border bg-muted"}`}>
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Результат · {job.verdict ?? "—"}</p>
        <h2 id="res-title" className={`mt-1 text-xl font-bold ${violation ? "text-warning" : job.verdict ? "text-success" : ""}`}>{label}</h2>
        <p className="mt-2 text-sm text-foreground/80">Результат — подсказка для проверки человеком, а не окончательное решение.</p>
      </div>
      {violations.length > 0 && (
        <ol className="space-y-3">
          {violations.map((item, i) => <ViolationCard key={i} violation={item} n={i + 1} onSeek={onSeek} />)}
        </ol>
      )}
      {violation && violations.length === 0 && <p className="text-sm text-muted-foreground">Сервис не передал детали возможных нарушений.</p>}
    </section>
  );
}

function ViolationCard({ violation, n, onSeek }: { violation: Violation; n: number; onSeek: (s: number) => void }) {
  const [zoom, setZoom] = useState<string | null>(null);
  const dlg = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (zoom) dlg.current?.showModal(); }, [zoom]);
  const sec = parseSeconds(violation.timecode_sec);
  const frames = violation.evidence_frames.slice(0, 3);
  return (
    <li className="card-surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-muted-foreground">#{n}</span>
        <span className="rounded-lg bg-accent px-2.5 py-1 text-sm font-semibold text-accent-foreground">{violation.type || "Тип не указан"}</span>
        {sec !== null && <button onClick={() => onSeek(sec)} className="rounded-lg border border-input px-2.5 py-1 font-mono text-sm font-semibold hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring" aria-label={"Перейти к моменту " + formatTime(sec)}>▶ {formatTime(sec)}</button>}
      </div>
      {violation.description && <p className="mt-3">{violation.description}</p>}
      {frames.length > 0 && <div className="mt-3 flex flex-wrap gap-2">
        {frames.map((frame, i) => {
          const src = frameDataUrl(frame.image_base64);
          const frameTime = formatTime(frame.timestamp_sec);
          return <button key={i} onClick={() => setZoom(src)} className="overflow-hidden rounded-lg border border-border focus-visible:outline-2 focus-visible:outline-ring" aria-label={"Открыть кадр " + (i + 1) + " крупнее, " + frameTime}>
            <img src={src} alt={"Кадр-доказательство " + (i + 1) + " события " + n + ", " + frameTime} className="h-24 w-40 object-cover" loading="lazy" />
            <span className="block px-2 py-1 text-xs text-muted-foreground">{frameTime}</span>
          </button>;
        })}
      </div>}
      <div className="mt-3 border-t border-border pt-3 text-sm"><span className="text-muted-foreground">Правило / источник: </span><span className="font-medium">Источник не указан</span></div>
      <dialog ref={dlg} onClose={() => setZoom(null)} onClick={(e) => e.target === dlg.current && dlg.current?.close()} className="m-auto max-w-[95vw] rounded-2xl bg-card p-0 backdrop:bg-foreground/70" aria-label="Кадр крупно">
        {zoom && <img src={zoom} alt={"Кадр события " + n + " крупно"} className="max-h-[80vh] w-auto" />}
        <form method="dialog" className="flex justify-end p-3"><button className="rounded-lg px-4 py-2 text-sm font-semibold hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring" autoFocus>Закрыть</button></form>
      </dialog>
    </li>
  );
}

import { createFileRoute } from "@tanstack/react-router";
import { AppHeader } from "@/components/AppHeader";

export const Route = createFileRoute("/api-docs")({
  head: () => ({
    meta: [
      { title: "API для жюри — Forte Vision" },
      { name: "description", content: "Описание API Forte Vision: загрузка видео и получение результата анализа." },
      { property: "og:title", content: "API для жюри — Forte Vision" },
      { property: "og:description", content: "POST /api/v1/analyze и GET /api/v1/jobs/{job_id} с заголовком X-API-Key." },
    ],
  }),
  component: ApiDocs,
});

const example = `{
  "job_id": "3f2c9a1e-...",
  "status": "done",
  "verdict": "violation",
  "events": [
    {
      "type": "...",
      "timestamp": 42.5,
      "description": "...",
      "frames": ["/frames/3f2c9a1e/42.jpg"],
      "source": {
        "title": "...",
        "section": "...",
        "url": "https://..."
      }
    }
  ]
}`;

function Code({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-xl bg-secondary p-4 text-[13px] leading-relaxed text-secondary-foreground"><code>{children}</code></pre>
  );
}

function ApiDocs() {
  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-8 sm:px-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">API для жюри</h1>
          <p className="mt-2 text-muted-foreground">Каждый запрос требует заголовок <code className="font-semibold text-foreground">X-API-Key</code>. Ключ выдаётся организаторами и в интерфейсе не хранится.</p>
        </div>
        <section className="card-surface space-y-3 p-5" aria-labelledby="a1">
          <h2 id="a1" className="font-semibold"><span className="mr-2 rounded bg-primary px-2 py-0.5 text-xs text-primary-foreground">POST</span>/api/v1/analyze</h2>
          <p className="text-sm text-muted-foreground">multipart/form-data, поле <code>file</code> — один файл .mov. Возвращает <code>job_id</code>.</p>
          <Code>{`curl -X POST "$BASE/api/v1/analyze" \\
  -H "X-API-Key: <ВАШ_КЛЮЧ>" \\
  -F "file=@operation.mov"`}</Code>
        </section>
        <section className="card-surface space-y-3 p-5" aria-labelledby="a2">
          <h2 id="a2" className="font-semibold"><span className="mr-2 rounded bg-accent px-2 py-0.5 text-xs text-accent-foreground">GET</span>/api/v1/jobs/{"{job_id}"}</h2>
          <p className="text-sm text-muted-foreground">
            <code>status</code>: <code>processing</code> / <code>done</code> / <code>failed</code>. При <code>done</code> — <code>verdict</code>: <code>no_violation</code> / <code>violation</code>.
          </p>
          <Code>{`curl "$BASE/api/v1/jobs/<job_id>" -H "X-API-Key: <ВАШ_КЛЮЧ>"`}</Code>
          <h3 className="pt-2 text-sm font-semibold">Пример ответа (структура)</h3>
          <Code>{example}</Code>
          <p className="text-xs text-muted-foreground">Значения полей — иллюстрация структуры, а не реальный результат.</p>
        </section>
      </main>
    </div>
  );
}

import { createFileRoute } from "@tanstack/react-router";
import { useEffect } from "react";

export const Route = createFileRoute("/annotation")({
  component: AnnotationRedirect,
});

function AnnotationRedirect() {
  useEffect(() => {
    window.location.replace("/annotation/");
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 text-center">
      <div>
        <h1 className="text-xl font-semibold">Открываю страницу разметки…</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Если переход не сработал, откройте <a className="underline" href="/annotation/">разметчик по этой ссылке</a>.
        </p>
      </div>
    </main>
  );
}

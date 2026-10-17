import { Link } from "@tanstack/react-router";

export function AppHeader() {
  const nav = "rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring";
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3 sm:px-6">
        <Link to="/" className="flex items-center gap-2.5 rounded-lg focus-visible:outline-2 focus-visible:outline-ring">
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-sm font-extrabold text-primary-foreground">F</span>
          <span className="font-bold tracking-tight">Forte Vision</span>
        </Link>
        <nav aria-label="Основная навигация" className="flex gap-1">
          <Link to="/" className={nav} activeProps={{ className: "text-foreground bg-secondary" }} activeOptions={{ exact: true }}>Проверка</Link>
          <Link to="/api-docs" className={nav} activeProps={{ className: "text-foreground bg-secondary" }}>API</Link>
        </nav>
      </div>
    </header>
  );
}

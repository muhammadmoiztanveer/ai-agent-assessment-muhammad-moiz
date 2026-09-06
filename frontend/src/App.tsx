import { useEffect, useState } from "react";
import { getHealth, API_BASE_URL } from "./lib/api";

type Connection =
  | { state: "checking" }
  | { state: "online"; version: string }
  | { state: "offline" };

export default function App() {
  const [connection, setConnection] = useState<Connection>({ state: "checking" });

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((h) => {
        if (!cancelled) setConnection({ state: "online", version: h.version });
      })
      .catch(() => {
        if (!cancelled) setConnection({ state: "offline" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="min-h-full bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-6 px-6 text-center">
        <span className="rounded-full bg-indigo-100 px-3 py-1 text-sm font-medium text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">
          Beyond-spec dashboard
        </span>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Agentic Search Intelligence
        </h1>
        <p className="max-w-prose text-slate-600 dark:text-slate-400">
          Frontend foundation is ready. The full pipeline dashboard is built in
          Phase 11 once the graded backend is complete.
        </p>
        <ConnectionBadge connection={connection} />
      </div>
    </main>
  );
}

function ConnectionBadge({ connection }: { connection: Connection }) {
  const base =
    "inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium";

  if (connection.state === "checking") {
    return (
      <div className={`${base} border-slate-300 text-slate-500`} aria-live="polite">
        <Dot className="bg-slate-400" /> Checking backend…
      </div>
    );
  }

  if (connection.state === "online") {
    return (
      <div
        className={`${base} border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300`}
        aria-live="polite"
      >
        <Dot className="bg-emerald-500" /> Backend online · v{connection.version}
      </div>
    );
  }

  return (
    <div
      className={`${base} border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300`}
      aria-live="polite"
    >
      <Dot className="bg-rose-500" /> Backend offline · start it at {API_BASE_URL}
    </div>
  );
}

function Dot({ className }: { className: string }) {
  return <span className={`h-2 w-2 rounded-full ${className}`} aria-hidden="true" />;
}

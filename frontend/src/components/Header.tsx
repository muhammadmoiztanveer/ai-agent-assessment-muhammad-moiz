/** App header with title and a live backend connection badge. */

import { useEffect, useState } from "react";
import { API_BASE_URL, getHealth } from "../lib/api";

type Connection =
  | { state: "checking" }
  | { state: "online"; version: string }
  | { state: "offline" };

export function Header() {
  const [connection, setConnection] = useState<Connection>({ state: "checking" });

  useEffect(() => {
    let cancelled = false;
    const check = () => {
      getHealth()
        .then((h) => {
          if (!cancelled) setConnection({ state: "online", version: h.version });
        })
        .catch(() => {
          if (!cancelled) setConnection({ state: "offline" });
        });
    };
    check();
    const timer = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <header className="border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-6 py-4">
        <div className="flex items-center gap-3">
          <div
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 text-sm font-bold text-white"
            aria-hidden="true"
          >
            AS
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-slate-900 dark:text-slate-100">
              Agentic Search Intelligence
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              LangGraph DAG · Planner → Retrieval → Extraction → Analysis → Report
            </p>
          </div>
        </div>
        <ConnectionBadge connection={connection} />
      </div>
    </header>
  );
}

function ConnectionBadge({ connection }: { connection: Connection }) {
  const base =
    "inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium";
  if (connection.state === "checking") {
    return (
      <span className={`${base} border-slate-300 text-slate-500`} aria-live="polite">
        <Dot className="bg-slate-400" /> Checking backend…
      </span>
    );
  }
  if (connection.state === "online") {
    return (
      <span
        className={`${base} border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300`}
        aria-live="polite"
      >
        <Dot className="bg-emerald-500" /> API online · v{connection.version}
      </span>
    );
  }
  return (
    <span
      className={`${base} border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300`}
      aria-live="polite"
      title={`Start the backend, then it should be reachable at ${API_BASE_URL}`}
    >
      <Dot className="bg-rose-500" /> API offline
    </span>
  );
}

function Dot({ className }: { className: string }) {
  return <span className={`h-2 w-2 rounded-full ${className}`} aria-hidden="true" />;
}

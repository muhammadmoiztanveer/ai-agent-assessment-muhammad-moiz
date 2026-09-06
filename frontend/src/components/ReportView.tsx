/** Final report: human-readable summary + collapsible raw JSON, and run trace. */

import { useState } from "react";
import type { RunResponse } from "../lib/types";
import { formatDate } from "../lib/format";
import { Card } from "./ui";

export function ReportView({ run }: { run: RunResponse }) {
  const [showJson, setShowJson] = useState(false);

  return (
    <Card
      title="6 · Report"
      description="The final deliverable: a human-readable summary plus the structured JSON."
    >
      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
            Summary
          </h3>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-600 dark:text-slate-300">
            {run.report.report_summary}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-500 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-400">
          <p className="font-semibold uppercase tracking-wide text-slate-400">
            Run trace
          </p>
          <dl className="mt-2 grid gap-1 sm:grid-cols-2">
            <TraceLine label="Run UUID" value={run.run_uuid} mono />
            <TraceLine label="Correlation ID" value={run.correlation_id} mono />
            <TraceLine label="Started" value={formatDate(run.started_at)} />
            <TraceLine
              label="Finished"
              value={run.finished_at ? formatDate(run.finished_at) : "—"}
            />
          </dl>
        </div>

        <div>
          <button
            type="button"
            onClick={() => setShowJson((v) => !v)}
            aria-expanded={showJson}
            className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-300"
          >
            {showJson ? "▾ Hide raw JSON" : "▸ Show raw JSON"}
          </button>
          {showJson && (
            <pre className="mt-2 max-h-96 overflow-auto rounded-xl bg-slate-900 p-4 text-xs leading-relaxed text-slate-100">
              {JSON.stringify(run.report.report_json, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </Card>
  );
}

function TraceLine({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 font-medium text-slate-400">{label}:</dt>
      <dd
        className={`truncate text-slate-600 dark:text-slate-300 ${mono ? "font-mono" : ""}`}
      >
        {value}
      </dd>
    </div>
  );
}

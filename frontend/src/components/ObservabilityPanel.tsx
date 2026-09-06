/**
 * Observability panel — makes the backend's per-run tracing + metrics visible.
 *
 * Surfaces exactly what the structured `run.metrics` log line carries: the DAG
 * execution path, total latency, success rate, API-call and retry totals, token
 * usage, and a node-by-node trace table keyed to the run's correlation ID.
 */

import type { RunResponse } from "../lib/types";
import { formatInt } from "../lib/format";
import { Badge, Card, EmptyState, Stat } from "./ui";
import { GraphView } from "./GraphView";

export function ObservabilityPanel({ run }: { run: RunResponse }) {
  const obs = run.observability;

  return (
    <Card
      title="3 · Observability & DAG trace"
      description="Per-node latency, success/failure, API calls, and retries for this run — the same metrics the backend logs, keyed to the correlation ID."
    >
      {!obs ? (
        <EmptyState title="No trace available" hint="This run has no recorded metrics yet." />
      ) : (
        <div className="space-y-5">
          <GraphView observability={obs} />

          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Total time" value={`${obs.total_duration_ms.toFixed(1)} ms`} />
            <Stat label="Success rate" value={`${Math.round(obs.success_rate * 100)}%`} />
            <Stat label="Nodes" value={formatInt(obs.node_count)} />
            <Stat label="API calls" value={formatInt(obs.total_api_calls)} />
            <Stat label="Retries" value={formatInt(obs.total_retries)} />
            <Stat label="Tokens" value={formatInt(obs.total_tokens)} />
          </dl>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">
                <tr>
                  <th className="py-2 pr-4 font-medium">Node</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Duration</th>
                  <th className="py-2 pr-4 font-medium">API calls</th>
                  <th className="py-2 pr-4 font-medium">Retries</th>
                  <th className="py-2 font-medium">Error</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {obs.nodes.map((n, i) => (
                  <tr key={`${n.node}-${i}`}>
                    <td className="py-2 pr-4 font-mono text-xs text-slate-700 dark:text-slate-300">
                      {n.node}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge tone={n.success ? "green" : "red"}>
                        {n.success ? "ok" : "failed"}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4 text-slate-600 dark:text-slate-300">
                      {n.duration_ms.toFixed(2)} ms
                    </td>
                    <td className="py-2 pr-4 text-slate-600 dark:text-slate-300">{n.api_calls}</td>
                    <td className="py-2 pr-4 text-slate-600 dark:text-slate-300">
                      {n.retry_count}
                    </td>
                    <td className="py-2 text-slate-500 dark:text-slate-400">
                      {n.error_code ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-slate-400 dark:text-slate-500">
            correlation <code>{obs.correlation_id}</code>
          </p>
        </div>
      )}
    </Card>
  );
}

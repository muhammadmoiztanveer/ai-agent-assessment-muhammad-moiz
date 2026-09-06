/**
 * Live DAG visualization.
 *
 * Renders the LangGraph pipeline as its named nodes and shows which path a run
 * actually took: the happy path (Planner → Retrieval → Extraction → Analysis →
 * Report) or the degraded path through `fallback`. Each executed node shows its
 * measured latency, success/failure, API-call count, and retry count — the same
 * per-node observability the backend logs, made visible to a reviewer.
 */

import type { NodeMetric, Observability } from "../lib/types";
import { Badge, EmptyState } from "./ui";

const NODE_LABELS: Record<string, string> = {
  plan_queries: "Planner",
  retrieve_data: "Retrieval",
  normalize_data: "Extraction",
  analyze_data: "Analysis",
  build_report: "Report",
  fallback: "Fallback",
};

// The linear happy path, in execution order.
const HAPPY_PATH = [
  "plan_queries",
  "retrieve_data",
  "normalize_data",
  "analyze_data",
  "build_report",
] as const;

export function GraphView({ observability }: { observability: Observability | null }) {
  if (!observability) {
    return <EmptyState title="No trace yet" hint="Run the pipeline to see the DAG execution path." />;
  }

  const byNode = new Map<string, NodeMetric>();
  for (const n of observability.nodes) byNode.set(n.node, n);

  const fallbackRan = byNode.has("fallback");
  // build_report is reached from either analyze_data or fallback.
  const sequence: string[] = fallbackRan
    ? ["plan_queries", "retrieve_data", "fallback", "build_report"]
    : [...HAPPY_PATH];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-stretch gap-2">
        {sequence.map((name, index) => (
          <div key={name} className="flex items-stretch gap-2">
            <NodeCard name={name} metric={byNode.get(name)} />
            {index < sequence.length - 1 && <Arrow />}
          </div>
        ))}
      </div>

      {fallbackRan ? (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          Conditional routing took the <strong>fallback</strong> path — Extraction and Analysis were
          skipped, and the run still produced a report (graceful degradation).
        </p>
      ) : (
        <p className="text-xs text-slate-400 dark:text-slate-500">
          Happy path — all five agents executed in order with conditional routing between them.
        </p>
      )}
    </div>
  );
}

function NodeCard({ name, metric }: { name: string; metric: NodeMetric | undefined }) {
  const label = NODE_LABELS[name] ?? name;
  const ran = metric != null;
  const failed = ran && !metric.success;
  const isFallback = name === "fallback";

  const border = failed
    ? "border-rose-300 dark:border-rose-500/40"
    : isFallback
      ? "border-amber-300 dark:border-amber-500/40"
      : ran
        ? "border-emerald-300 dark:border-emerald-500/40"
        : "border-dashed border-slate-300 dark:border-slate-700";

  const bg = failed
    ? "bg-rose-50 dark:bg-rose-500/10"
    : isFallback
      ? "bg-amber-50 dark:bg-amber-500/10"
      : ran
        ? "bg-white dark:bg-slate-900"
        : "bg-slate-50 opacity-60 dark:bg-slate-800/40";

  return (
    <div className={`min-w-[8.5rem] rounded-xl border px-3 py-2 ${border} ${bg}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{label}</span>
        <span
          aria-hidden
          className={`h-2 w-2 rounded-full ${
            failed ? "bg-rose-500" : ran ? "bg-emerald-500" : "bg-slate-300"
          }`}
        />
      </div>
      <code className="text-[10px] text-slate-400">{name}</code>
      {ran ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          <Badge tone="slate">{metric.duration_ms.toFixed(1)} ms</Badge>
          {metric.api_calls > 0 && <Badge tone="blue">{metric.api_calls} API</Badge>}
          {metric.retry_count > 0 && <Badge tone="amber">{metric.retry_count} retries</Badge>}
        </div>
      ) : (
        <p className="mt-1.5 text-[11px] text-slate-400">skipped</p>
      )}
    </div>
  );
}

function Arrow() {
  return (
    <span className="flex items-center text-slate-300 dark:text-slate-600" aria-hidden>
      →
    </span>
  );
}

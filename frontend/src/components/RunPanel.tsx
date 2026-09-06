/** Active profile header, pipeline run trigger, live status, and run summary. */

import type {
  Insight,
  ProfileCreatedResponse,
  RunResponse,
} from "../lib/types";
import {
  formatInt,
  formatScore,
  runStatusLabel,
  runStatusTone,
  visibilityLabel,
  visibilityTone,
} from "../lib/format";
import { Badge, Banner, Button, Card, EmptyState, Spinner, Stat } from "./ui";

export function RunPanel({
  profile,
  run,
  running,
  error,
  asyncMode,
  onAsyncModeChange,
  onRun,
  onReset,
}: {
  profile: ProfileCreatedResponse;
  run: RunResponse | null;
  running: boolean;
  error: string | null;
  asyncMode: boolean;
  onAsyncModeChange: (value: boolean) => void;
  onRun: () => void;
  onReset: () => void;
}) {
  return (
    <Card
      title="2 · Run the pipeline"
      description="Executes the full LangGraph DAG: Planner → Retrieval → Extraction → Analysis → Report."
      actions={
        <div className="flex items-center gap-3">
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500 dark:border-slate-600 dark:bg-slate-800"
              checked={asyncMode}
              disabled={running}
              onChange={(event) => onAsyncModeChange(event.target.checked)}
            />
            Background (async)
          </label>
          <Button variant="ghost" onClick={onReset}>
            New profile
          </Button>
          <Button onClick={onRun} busy={running}>
            {running
              ? asyncMode
                ? "Working…"
                : "Running…"
              : run
                ? "Run again"
                : "Run pipeline"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="font-semibold text-slate-900 dark:text-slate-100">
            {profile.name}
          </span>
          <span className="text-slate-500 dark:text-slate-400">
            {profile.domain}
          </span>
          {profile.industry && <Badge tone="violet">{profile.industry}</Badge>}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            {profile.profile_uuid.slice(0, 8)}…
          </code>
        </div>

        {running && (
          <div
            className="flex items-center gap-3 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-200"
            aria-live="polite"
          >
            <Spinner label="Running pipeline" />
            <span>
              {asyncMode
                ? `Background run ${run?.status === "queued" ? "queued" : "in progress"} — polling for completion…`
                : "Running the agentic pipeline — this usually takes a few seconds."}
            </span>
          </div>
        )}

        {error && !running && (
          <Banner tone="error" title="Run failed">
            {error}
          </Banner>
        )}

        {run && !running && (
          <>
            {run.error_flag && (
              <Banner tone="warning" title={`Degraded run (${run.status})`}>
                {run.degraded_reason ??
                  "The pipeline returned partial results."}
              </Banner>
            )}

            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-800/40">
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Status
                </dt>
                <dd className="mt-1">
                  <Badge tone={runStatusTone(run.status)}>
                    {runStatusLabel(run.status)}
                  </Badge>
                </dd>
              </div>
              <Stat
                label="Planned calls"
                value={formatInt(run.planned_retrieval_calls)}
              />
              <Stat
                label="Extracted"
                value={formatInt(run.extracted_records)}
              />
              <Stat label="Total tokens" value={formatInt(run.total_tokens)} />
              <Stat
                label="Insights"
                value={formatInt(run.top_insights.length)}
              />
            </dl>

            <p className="text-xs text-slate-400 dark:text-slate-500">
              run <code>{run.run_uuid.slice(0, 12)}…</code> · correlation{" "}
              <code>{run.correlation_id.slice(0, 12)}…</code>
            </p>

            <TopInsights insights={run.top_insights} />
          </>
        )}

        {!run && !running && !error && (
          <EmptyState
            title="No run yet"
            hint="Click “Run pipeline” to execute the DAG and generate insights."
          />
        )}
      </div>
    </Card>
  );
}

function TopInsights({ insights }: { insights: Insight[] }) {
  if (insights.length === 0) {
    return <EmptyState title="No insights produced" />;
  }
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
        Top insights
      </h3>
      <ul className="space-y-2">
        {insights.map((insight, index) => (
          <li
            key={`${insight.query_text}-${index}`}
            className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-slate-900 dark:text-slate-100">
                {insight.query_text}
              </span>
              <div className="flex items-center gap-2">
                <Badge tone={visibilityTone(insight.visibility_status)}>
                  {visibilityLabel(insight.visibility_status)}
                  {insight.visibility_position != null &&
                    ` · #${insight.visibility_position}`}
                </Badge>
                <Badge tone="blue">
                  score {formatScore(insight.opportunity_score)}
                </Badge>
              </div>
            </div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {insight.rationale}
            </p>
            <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
              volume {formatInt(insight.estimated_search_volume)} · difficulty{" "}
              {insight.competitive_difficulty}/100
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

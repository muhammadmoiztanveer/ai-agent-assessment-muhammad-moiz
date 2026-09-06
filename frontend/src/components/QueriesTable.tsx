/** Discovered queries: sortable-by-score list with filters, pagination, recheck. */

import { useCallback, useEffect, useState } from "react";
import { ApiError, listQueries, recheckQuery } from "../lib/api";
import type { QueryRow, VisibilityStatus } from "../lib/types";
import {
  formatDate,
  formatInt,
  formatScore,
  visibilityLabel,
  visibilityTone,
} from "../lib/format";
import { Badge, Banner, Button, Card, EmptyState, Spinner } from "./ui";

const PER_PAGE = 10;

const SELECT =
  "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100";

export function QueriesTable({
  profileUuid,
  refreshKey,
}: {
  profileUuid: string;
  refreshKey: number;
}) {
  const [rows, setRows] = useState<QueryRow[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [minScore, setMinScore] = useState<number | null>(null);
  const [status, setStatus] = useState<VisibilityStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rechecking, setRechecking] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listQueries(profileUuid, {
        min_score: minScore,
        status,
        page,
        per_page: PER_PAGE,
      });
      setRows(data.items);
      setTotalPages(data.total_pages);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load queries.");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [profileUuid, minScore, status, page]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // Reset to page 1 whenever the filters change.
  useEffect(() => {
    setPage(1);
  }, [minScore, status]);

  async function handleRecheck(queryUuid: string) {
    setRechecking(queryUuid);
    setNotice(null);
    try {
      const result = await recheckQuery(queryUuid);
      setRows((prev) =>
        prev.map((row) => (row.query_uuid === queryUuid ? result.query : row)),
      );
      setNotice(`Rechecked “${result.query.query_text}” — data refreshed.`);
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : "Recheck failed.");
    } finally {
      setRechecking(null);
    }
  }

  return (
    <Card
      title="3 · Discovered queries"
      description="Sorted by opportunity score (highest first). Filter, paginate, and recheck any row."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="q-min">
            Minimum opportunity score
          </label>
          <select
            id="q-min"
            className={SELECT}
            value={minScore ?? ""}
            onChange={(e) => setMinScore(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Any score</option>
            <option value="0.3">≥ 0.30</option>
            <option value="0.5">≥ 0.50</option>
            <option value="0.7">≥ 0.70</option>
          </select>
          <label className="sr-only" htmlFor="q-status">
            Visibility status
          </label>
          <select
            id="q-status"
            className={SELECT}
            value={status ?? ""}
            onChange={(e) =>
              setStatus(e.target.value ? (e.target.value as VisibilityStatus) : null)
            }
          >
            <option value="">All statuses</option>
            <option value="visible">Visible</option>
            <option value="not_visible">Not visible</option>
            <option value="unknown">Unknown</option>
          </select>
        </div>
      }
    >
      {notice && (
        <div className="mb-3">
          <Banner tone="info" title="Recheck">
            {notice}
          </Banner>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
          <Spinner /> Loading queries…
        </div>
      ) : error ? (
        <Banner tone="error" title="Could not load queries">
          {error}
        </Banner>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No queries match"
          hint="Try clearing the filters, or run the pipeline first."
        />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  <th scope="col" className="py-2 pr-3 font-medium">
                    Query
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Score
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Volume
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Difficulty
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Visibility
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.query_uuid}
                    className="border-b border-slate-100 last:border-0 dark:border-slate-800"
                  >
                    <td className="max-w-xs py-2.5 pr-3">
                      <span className="block truncate font-medium text-slate-900 dark:text-slate-100">
                        {row.query_text}
                      </span>
                      <span className="text-xs text-slate-400">{formatDate(row.discovered_at)}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right font-semibold text-slate-900 dark:text-slate-100">
                      {formatScore(row.opportunity_score)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-slate-600 dark:text-slate-300">
                      {formatInt(row.estimated_search_volume)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-slate-600 dark:text-slate-300">
                      {row.competitive_difficulty}/100
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge tone={visibilityTone(row.visibility_status)}>
                        {visibilityLabel(row.visibility_status)}
                        {row.visibility_position != null && ` · #${row.visibility_position}`}
                      </Badge>
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <Button
                        variant="secondary"
                        busy={rechecking === row.query_uuid}
                        onClick={() => handleRecheck(row.query_uuid)}
                      >
                        Recheck
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex items-center justify-between text-sm text-slate-500 dark:text-slate-400">
            <span>
              {total} quer{total === 1 ? "y" : "ies"} · page {page} of {totalPages}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

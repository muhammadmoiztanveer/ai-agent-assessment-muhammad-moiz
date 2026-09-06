/** Content recommendations from the profile's most recent run. */

import { useCallback, useEffect, useState } from "react";
import { ApiError, listRecommendations } from "../lib/api";
import type { Recommendation } from "../lib/types";
import { contentTypeLabel, priorityTone } from "../lib/format";
import { Badge, Banner, Card, EmptyState, Spinner } from "./ui";

export function Recommendations({
  profileUuid,
  refreshKey,
}: {
  profileUuid: string;
  refreshKey: number;
}) {
  const [items, setItems] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listRecommendations(profileUuid);
      setItems(data.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load recommendations.");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [profileUuid]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  return (
    <Card
      title="4 · Content recommendations"
      description="Prioritized content ideas targeting the highest-opportunity queries."
    >
      {loading ? (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
          <Spinner /> Loading recommendations…
        </div>
      ) : error ? (
        <Banner tone="error" title="Could not load recommendations">
          {error}
        </Banner>
      ) : items.length === 0 ? (
        <EmptyState title="No recommendations yet" hint="Run the pipeline to generate them." />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {items.map((rec) => (
            <li
              key={rec.recommendation_uuid}
              className="flex flex-col gap-2 rounded-xl border border-slate-200 p-4 dark:border-slate-800"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-medium text-slate-900 dark:text-slate-100">{rec.title}</h3>
                <Badge tone={priorityTone(rec.priority)}>{rec.priority}</Badge>
              </div>
              <Badge tone="violet">{contentTypeLabel(rec.content_type)}</Badge>
              <p className="text-sm text-slate-500 dark:text-slate-400">{rec.rationale}</p>
              {rec.target_keywords.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {rec.target_keywords.map((kw) => (
                    <span
                      key={kw}
                      className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                    >
                      {kw}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Small presentation helpers shared across dashboard components. */

import type { Priority, RunStatus, VisibilityStatus } from "./types";

type Tone = "green" | "amber" | "red" | "blue" | "slate" | "violet";

/** Map a run status to a badge tone. */
export function runStatusTone(status: string): Tone {
  switch (status) {
    case "completed":
      return "green";
    case "partial":
      return "amber";
    case "failed":
      return "red";
    case "running":
      return "blue";
    case "queued":
      return "violet";
    default:
      return "slate";
  }
}

/** Map a visibility status to a badge tone. */
export function visibilityTone(status: VisibilityStatus): Tone {
  switch (status) {
    case "visible":
      return "green";
    case "not_visible":
      return "amber";
    default:
      return "slate";
  }
}

/** Map a recommendation priority to a badge tone. */
export function priorityTone(priority: Priority): Tone {
  switch (priority) {
    case "high":
      return "red";
    case "medium":
      return "amber";
    default:
      return "slate";
  }
}

/** Human label for a visibility status. */
export function visibilityLabel(status: VisibilityStatus): string {
  return status.replace("_", " ");
}

/** Human label for a run status. */
export function runStatusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

/** Format an opportunity score in [0,1] as a percentage-like 2dp value. */
export function formatScore(score: number): string {
  return score.toFixed(2);
}

/** Format an integer with thousands separators. */
export function formatInt(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US");
}

/** Format an ISO timestamp into a readable local string. */
export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

/** A stable palette label for a content type. */
export function contentTypeLabel(contentType: string): string {
  return contentType.replace("_", " ");
}

export type { RunStatus };

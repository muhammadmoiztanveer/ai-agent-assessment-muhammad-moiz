/**
 * Typed API client for the Agentic Search Intelligence backend.
 *
 * The base URL is configurable via `VITE_API_BASE_URL` (see `.env.example`),
 * defaulting to the local backend. Every failure is surfaced as an `ApiError`
 * carrying the HTTP status and the backend's uniform error envelope message,
 * so the UI can render precise, human-readable failures.
 */

import type {
  HealthResponse,
  ProfileCreatePayload,
  ProfileCreatedResponse,
  ProfileDetailResponse,
  QueryFilters,
  QueryListResponse,
  RecheckResponse,
  RecommendationListResponse,
  RunResponse,
} from "./types";

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** An error raised for any non-2xx API response. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ErrorEnvelope {
  error?: { code?: string; message?: string; details?: unknown };
}

/** Perform a JSON request against the backend API. */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json", ...init?.headers },
      ...init,
    });
  } catch {
    // Network-level failure (backend down, CORS, DNS, ...).
    throw new ApiError(
      0,
      `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`,
    );
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    let code: string | undefined;
    try {
      const body = (await response.json()) as ErrorEnvelope;
      if (body.error?.message) message = body.error.message;
      code = body.error?.code;
    } catch {
      // Non-JSON error body — keep the default message.
    }
    throw new ApiError(response.status, message, code);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** Liveness probe against the backend. */
export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

/** Register a new brand/keyword profile. */
export function createProfile(
  payload: ProfileCreatePayload,
): Promise<ProfileCreatedResponse> {
  return apiFetch<ProfileCreatedResponse>("/api/v1/profiles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Fetch a profile plus its summary statistics. */
export function getProfile(
  profileUuid: string,
): Promise<ProfileDetailResponse> {
  return apiFetch<ProfileDetailResponse>(`/api/v1/profiles/${profileUuid}`);
}

/** Run the full agentic pipeline for a profile (synchronous, 10-30s). */
export function runPipeline(profileUuid: string): Promise<RunResponse> {
  return apiFetch<RunResponse>(`/api/v1/profiles/${profileUuid}/run`, {
    method: "POST",
  });
}

/** List discovered queries for a profile's most recent run. */
export function listQueries(
  profileUuid: string,
  filters: QueryFilters = {},
): Promise<QueryListResponse> {
  const params = new URLSearchParams();
  if (filters.min_score != null)
    params.set("min_score", String(filters.min_score));
  if (filters.status) params.set("status", filters.status);
  params.set("page", String(filters.page ?? 1));
  params.set("per_page", String(filters.per_page ?? 20));
  const qs = params.toString();
  return apiFetch<QueryListResponse>(
    `/api/v1/profiles/${profileUuid}/queries?${qs}`,
  );
}

/** List content recommendations for a profile's most recent run. */
export function listRecommendations(
  profileUuid: string,
): Promise<RecommendationListResponse> {
  return apiFetch<RecommendationListResponse>(
    `/api/v1/profiles/${profileUuid}/recommendations`,
  );
}

/** Re-run retrieval + extraction + analysis for a single query. */
export function recheckQuery(queryUuid: string): Promise<RecheckResponse> {
  return apiFetch<RecheckResponse>(`/api/v1/queries/${queryUuid}/recheck`, {
    method: "POST",
  });
}

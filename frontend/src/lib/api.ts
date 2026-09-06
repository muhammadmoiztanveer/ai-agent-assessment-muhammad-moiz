/**
 * Minimal typed API client foundation.
 *
 * The base URL is configurable via `VITE_API_BASE_URL` (see `.env.example`),
 * defaulting to the local backend. Feature-specific calls are added in the
 * Phase 11 dashboard build.
 */

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Perform a JSON request against the backend API. */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });

  if (!response.ok) {
    throw new ApiError(response.status, `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

/** Liveness probe against the backend. */
export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

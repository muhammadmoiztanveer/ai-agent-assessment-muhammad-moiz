/**
 * TypeScript mirrors of the backend API contracts (app/schemas/*).
 *
 * These are kept intentionally close to the Pydantic response models so the
 * dashboard consumes exactly what the API returns — nothing more, nothing less.
 */

export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "partial"
  | "failed";
export type VisibilityStatus = "visible" | "not_visible" | "unknown";
export type ContentType = "blog_post" | "landing_page" | "faq";
export type Priority = "high" | "medium" | "low";

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export interface ProfileCreatePayload {
  name: string;
  domain: string;
  industry?: string | null;
  description?: string | null;
  competitors: string[];
}

export interface ProfileCreatedResponse {
  profile_uuid: string;
  name: string;
  domain: string;
  industry: string | null;
  description: string | null;
  competitors: string[];
  status: string;
  created_at: string;
}

export interface ProfileSummary {
  total_runs: number;
  latest_run_status: string | null;
  average_opportunity_score: number | null;
}

export interface ProfileDetailResponse {
  profile_uuid: string;
  name: string;
  domain: string;
  industry: string | null;
  description: string | null;
  competitors: string[];
  created_at: string;
  summary: ProfileSummary;
}

export interface Insight {
  query_text: string;
  opportunity_score: number;
  estimated_search_volume: number;
  competitive_difficulty: number;
  domain_visible: boolean;
  visibility_position: number | null;
  visibility_status: VisibilityStatus;
  rationale: string;
}

export interface Report {
  report_json: Record<string, unknown>;
  report_summary: string;
}

export type NodeName =
  | "plan_queries"
  | "retrieve_data"
  | "normalize_data"
  | "analyze_data"
  | "build_report"
  | "fallback";

export interface NodeMetric {
  node: NodeName | string;
  duration_ms: number;
  success: boolean;
  retry_count: number;
  api_calls: number;
  error_code: string | null;
}

export interface Observability {
  correlation_id: string;
  total_duration_ms: number;
  node_count: number;
  success_count: number;
  failure_count: number;
  success_rate: number;
  total_api_calls: number;
  total_retries: number;
  total_tokens: number;
  nodes: NodeMetric[];
}

export type SimulateMode = "outage" | "degraded";

export interface RunResponse {
  run_uuid: string;
  profile_uuid: string;
  status: RunStatus;
  planned_retrieval_calls: number;
  extracted_records: number;
  top_insights: Insight[];
  report: Report;
  total_tokens: number | null;
  error_flag: boolean;
  degraded_reason: string | null;
  correlation_id: string;
  started_at: string;
  finished_at: string | null;
  observability: Observability | null;
}

export interface QueryRow {
  query_uuid: string;
  query_text: string;
  estimated_search_volume: number;
  competitive_difficulty: number;
  opportunity_score: number;
  domain_visible: boolean;
  visibility_position: number | null;
  visibility_status: VisibilityStatus;
  discovered_at: string;
}

export interface QueryListResponse {
  items: QueryRow[];
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
}

export interface Recommendation {
  recommendation_uuid: string;
  target_query_uuid: string;
  content_type: ContentType;
  title: string;
  rationale: string;
  target_keywords: string[];
  priority: Priority;
}

export interface RecommendationListResponse {
  items: Recommendation[];
  count: number;
}

export interface RecheckResponse {
  query: QueryRow;
  recommendations: Recommendation[];
  status: string;
  correlation_id: string;
}

export interface QueryFilters {
  min_score?: number | null;
  status?: VisibilityStatus | null;
  page?: number;
  per_page?: number;
}

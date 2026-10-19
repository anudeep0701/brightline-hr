export type Status = "healthy" | "degraded" | "unhealthy" | "unknown";
export type Metrics = {
  request_count: number;
  error_count: number;
  success_count: number | null;
  timeout_count: number | null;
  timeout_rate: number | null;
  p50_ms: number | null;
  p99_ms: number | null;
  error_rate: number | null;
  p95_ms: number | null;
  baseline?: {
    request_count: number;
    p95_ms: number | null;
    error_rate: number | null;
  };
  last_request_at: string | null;
  daily_request_count: number;
  daily_error_rate: number | null;
  error_categories: Record<string, number>;
  top_error_categories?: { category: string; count: number }[];
};
export type Snapshot = {
  id: string;
  bucket: string;
  evaluated_at: string;
  status: Status;
  observed_status: string;
  evidence_sufficient: boolean;
  confidence: number;
  reason_code: string;
  reason_text: string;
  score?: number;
  bad_window_streak: number;
  degraded_window_streak: number;
  healthy_window_streak: number;
  evidence: {
    policy_version: string;
    thresholds: Record<string, number>;
    metrics: Metrics;
    reasons: string[];
    signal_reason_codes?: string[];
    window_end: string;
  };
};
export type Integration = {
  id: string;
  name: string;
  category: string;
  owner: string;
  latency_target_ms: number;
  max_gap_minutes: number;
  evaluation_window_minutes: number;
  refresh_minutes: number;
  min_requests: number;
};
export type Incident = {
  id: string;
  integration_id: string;
  opened_at: string;
  resolved_at?: string;
  recovery_streak: number;
  opening_reason_text?: string | null;
  opening_reason_code?: string | null;
  recovery_began_at?: string | null;
  recovery_condition?: string | null;
  healthy_windows_required?: number | null;
  healthy_windows_observed?: number;
  opening_snapshot_id: string;
};
export type Workspace = {
  tenant_id: string;
  tenant_name: string;
  role: "reader" | "operator";
  mode: "demo" | "test" | "production";
  can_switch_tenants: boolean;
  tenants: { id: string; name: string }[];
};
export type Freshness = {
  status: "RECENT_TRAFFIC" | "STALE_TELEMETRY" | "NO_TELEMETRY";
  current_evidence_status: string;
  last_event_at: string | null;
  last_event_received_at: string | null;
  last_evaluated_at: string | null;
  evaluation_overdue: boolean;
  max_gap_minutes: number;
};
export type IntegrationRow = {
  freshness?: Freshness;
  integration: Integration;
  snapshot: Snapshot | null;
  previous_snapshot: Snapshot | null;
  stale: boolean;
};
export type OperationalImpact = {
  period_start: string;
  period_end: string;
  integrations_requiring_attention: number;
  healthy_percentage: number | null;
  unknown_integrations: number;
  stale_or_absent_integrations: number;
  incidents_detected: number;
  recovered_incidents: number;
  mean_confirmed_incident_duration_seconds: number | null;
};
export type Dashboard = {
  operational_impact: OperationalImpact;
  tenant: string;
  mode: string;
  server_time: string;
  refresh_seconds: number;
  integrations: IntegrationRow[];
  incidents: Incident[];
};
export type Log = {
  event_id: string;
  occurred_at: string;
  status_code: number;
  latency_ms: number;
  error_category: string;
  timed_out: boolean;
};
export type Detail = {
  freshness?: Freshness;
  enrichment: Explanation | null;
  integration: Integration;
  snapshot: Snapshot | null;
  history: Snapshot[];
  logs: Log[];
  incidents: Incident[];
};
export type EnrichmentReport = {
  summary: string;
  likely_issue_category: string;
  suggested_checks: string[];
  confidence: number;
  what_changed: string;
};
export type AIAudit = {
  tenant_id: string;
  integration_id: string;
  incident_id: string | null;
  snapshot_id: string;
  health_state: string;
  current_evidence_status: string;
  freshness_status: string;
  evidence_at: string;
  generated_at: string;
  model: string | null;
  fallback_used: boolean;
  failure_category?: string | null;
  requested_model?: string | null;
  duration_ms?: number | null;
  evidence_digest: string;
  topic: string;
  selected_fact_ids: string[];
  selected_check_ids: string[];
};
export type Investigation = {
  report: EnrichmentReport;
  source: string;
  fallback_code: string | null;
  audit: AIAudit;
};
export type Explanation = {
  audit?: AIAudit | null;
  report: EnrichmentReport | null;
  prompt_version: string;
  fallback_code: string | null;
  evidence_payload: Record<string, unknown> | null;
  source: string;
  explanation: string;
  snapshot_id: string;
  evidence_digest: string;
  generated_at: string;
};

export type UploadPreview = {
  total_records: number;
  valid_records: number;
  duplicates: number;
  rejected_records: number;
  unknown_integrations: number;
  validation_errors: { index: number; code: string; fields: string[] }[];
  can_import: boolean;
  file_digest: string;
};
export type ImportResult = {
  demo_import_batch_id?: string;
  accepted: number;
  rejected: number;
  duplicates: number;
  validation_errors: UploadPreview["validation_errors"];
};
export type DataSources = {
  tenant_id: string;
  items: {
    integration_id: string;
    integration_name: string;
    sources: { source_type: string; last_received_at: string }[];
    freshness: Freshness;
  }[];
};

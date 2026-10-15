export type Status = "healthy" | "degraded" | "unhealthy" | "unknown";
export type Metrics = {
  request_count: number;
  error_count: number;
  error_rate: number | null;
  p95_ms: number | null;
  last_request_at: string | null;
  daily_request_count: number;
  daily_error_rate: number | null;
  error_categories: Record<string, number>;
};
export type Snapshot = {
  id: string;
  bucket: string;
  evaluated_at: string;
  status: Status;
  score?: number;
  evidence: {
    policy_version: string;
    thresholds: Record<string, number>;
    metrics: Metrics;
    reasons: string[];
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
};
export type Incident = {
  id: string;
  integration_id: string;
  opened_at: string;
  resolved_at?: string;
  recovery_streak: number;
  opening_snapshot_id: string;
};
export type Dashboard = {
  tenant: string;
  mode: string;
  server_time: string;
  refresh_seconds: number;
  integrations: {
    integration: Integration;
    snapshot: Snapshot | null;
    stale: boolean;
  }[];
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
  integration: Integration;
  snapshot: Snapshot | null;
  history: Snapshot[];
  logs: Log[];
  incidents: Incident[];
};
export type Explanation = {
  source: string;
  explanation: string;
  snapshot_id: string;
  evidence_digest: string;
  generated_at: string;
};

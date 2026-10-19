import type { IntegrationRow, Snapshot, Status } from "@/types";

const priority: Record<Status, number> = {
  unhealthy: 0,
  degraded: 1,
  unknown: 2,
  healthy: 3,
};
export function isStale(row: IntegrationRow, now: number) {
  return (
    row.stale ||
    !row.snapshot ||
    now - new Date(row.snapshot.bucket).getTime() >
      row.integration.refresh_minutes * 120000
  );
}
export function needsAttention(row: IntegrationRow, now: number) {
  return currentEvidenceState(row, now) !== "healthy";
}
export function comparePriority(a: IntegrationRow, b: IntegrationRow) {
  return (
    priority[a.snapshot?.status ?? "unknown"] -
      priority[b.snapshot?.status ?? "unknown"] ||
    a.integration.name.localeCompare(b.integration.name)
  );
}
export function direction(
  current: Snapshot | null,
  previous?: Snapshot | null,
) {
  if (!current || !previous)
    return {
      kind: "none",
      text: "No prior window",
      title: "An earlier evaluation is needed for comparison.",
    };
  const a = current.evidence.metrics,
    b = previous.evidence.metrics;
  const delta =
    a.error_rate != null && b.error_rate != null
      ? (a.error_rate - b.error_rate) * 100
      : null;
  if (current.status !== previous.status) {
    return {
      kind:
        priority[current.status] < priority[previous.status] ? "up" : "down",
      text: `${previous.status} → ${current.status}`,
      title: "Persisted health-state change since the previous evaluation.",
    };
  }
  if (
    current.evidence_sufficient === false ||
    previous.evidence_sufficient === false
  ) {
    return {
      kind: "none",
      text: "Limited evidence",
      title: "Traffic is insufficient for a confident metric comparison.",
    };
  }
  if (delta != null && Math.abs(delta) >= 0.1)
    return {
      kind: delta > 0 ? "up" : "down",
      text: `Errors ${delta > 0 ? "+" : ""}${delta.toFixed(1)} pp`,
      title:
        "Error-rate change in percentage points. Rolling windows can overlap.",
    };
  if (a.p95_ms != null && b.p95_ms != null && b.p95_ms > 0) {
    const change = (a.p95_ms / b.p95_ms - 1) * 100;
    if (Math.abs(change) >= 10)
      return {
        kind: change > 0 ? "up" : "down",
        text: `P95 ${change > 0 ? "+" : ""}${Math.round(change)}%`,
        title:
          "Relative P95 change since the previous evaluation; windows may overlap.",
      };
  }
  if (delta === null && (a.p95_ms == null || b.p95_ms == null))
    return {
      kind: "none",
      text: "Limited evidence",
      title: "No comparable error rate or latency measurements.",
    };
  return {
    kind: "flat",
    text: "Little change",
    title:
      "Same state, error-rate change below 0.1 percentage point and P95 change below 10% where available.",
  };
}
export function transitions(history: Snapshot[]) {
  const ordered = [...history].sort((a, b) => a.bucket.localeCompare(b.bucket));
  return ordered
    .flatMap((snapshot, index) =>
      index > 0 && snapshot.status !== ordered[index - 1].status
        ? [{ snapshot, previous: ordered[index - 1].status }]
        : [],
    )
    .reverse();
}

export function currentEvidenceState(row: IntegrationRow, now: number): Status {
  if (
    isStale(row, now) ||
    (row.freshness && row.freshness.current_evidence_status === "UNKNOWN")
  )
    return "unknown";
  return row.snapshot?.status ?? "unknown";
}

export function advisoryConfidence(value: number) {
  return value >= 0.8 ? "High" : value >= 0.5 ? "Medium" : "Low";
}

export function investigationGuidance(row: IntegrationRow, now: number) {
  if (currentEvidenceState(row, now) === "unknown")
    return "Check telemetry delivery and evaluation freshness first.";
  const code = row.snapshot?.reason_code ?? "";
  const signals = row.snapshot?.evidence.signal_reason_codes ?? [];
  if (
    code === "RECOVERY_PENDING" ||
    (["RECOVERY_MARGIN_NOT_MET", "UNHEALTHY_RECOVERY_REQUIRED"].includes(
      code,
    ) &&
      !signals.length)
  )
    return `Verify recovery: ${row.snapshot?.healthy_window_streak ?? 0} of ${row.snapshot?.evidence.thresholds?.healthy_recovery_windows ?? "the required"} healthy windows confirmed. Check the stored recovery margins.`;
  const signal = /^(LATENCY|ERROR|TIMEOUT)/.test(code)
    ? code
    : (signals.find((value) => value.endsWith("CRITICAL")) ?? signals[0] ?? "");
  if (signal.startsWith("LATENCY"))
    return "Compare upstream response times, timeout settings and recent traffic volume.";
  const categories = row.snapshot?.evidence.metrics.top_error_categories ?? [];
  if (categories[0]?.category === "auth")
    return "Check credential validity, permissions and recent authentication changes.";
  return "Inspect the leading error category and provider responses in the incident detail.";
}

/** Presentation priority only: freshness takes precedence over historical state. */
export function compareCurrentPriority(
  a: IntegrationRow,
  b: IntegrationRow,
  now: number,
) {
  return (
    priority[currentEvidenceState(a, now)] -
      priority[currentEvidenceState(b, now)] ||
    (currentEvidenceState(a, now) === "unknown"
      ? isStale(a, now) || a.freshness?.status !== "RECENT_TRAFFIC"
        ? 0
        : 1
      : priority[
          (a.snapshot?.observed_status?.toLowerCase() as Status) ??
            a.snapshot?.status ??
            "unknown"
        ]) -
      (currentEvidenceState(b, now) === "unknown"
        ? isStale(b, now) || b.freshness?.status !== "RECENT_TRAFFIC"
          ? 0
          : 1
        : priority[
            (b.snapshot?.observed_status?.toLowerCase() as Status) ??
              b.snapshot?.status ??
              "unknown"
          ]) ||
    (b.snapshot?.evidence.metrics.error_rate ?? -1) -
      (a.snapshot?.evidence.metrics.error_rate ?? -1) ||
    a.integration.name.localeCompare(b.integration.name)
  );
}

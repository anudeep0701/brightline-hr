"use client";
import { use, useCallback, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, RefreshCw, Clock3 } from "lucide-react";
import { Shell } from "@/components/shell";
import { StatusBadge, History } from "@/components/status";
import { ErrorNotice, LoadingState } from "@/components/async-state";
import {
  IncidentAssistant,
  RecoverySummary,
} from "@/components/incident-assistant";
import { incidentDuration } from "@/components/incident-list";
import { MetricHistory } from "@/components/metric-history";
import { Trend } from "@/components/trend";
import { api, percent, ms, time, typeName } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { isStale, transitions, investigationGuidance } from "@/lib/health-view";
import type { Detail, Workspace } from "@/types";

export default function DetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [scope, setScope] = useState(0);
  const loader = useCallback(
    async (signal: AbortSignal) => {
      void scope;
      const [detail, workspace] = await Promise.all([
        api<Detail>(
          `/api/integrations/${encodeURIComponent(id)}`,
          "GET",
          signal,
        ),
        api<Workspace>("/api/workspace", "GET", signal),
      ]);
      return { detail, workspace };
    },
    [id, scope],
  );
  const {
    data: resource,
    error,
    fetching,
    checkedAt,
    reload,
  } = useResource(loader);
  const data = resource?.detail,
    workspace = resource?.workspace;
  const s = data?.snapshot,
    m = s?.evidence.metrics;
  const stale =
    !data ||
    isStale(
      {
        integration: data.integration,
        snapshot: data.snapshot,
        previous_snapshot: null,
        stale: data.freshness?.evaluation_overdue ?? false,
        freshness: data.freshness,
      },
      checkedAt,
    );
  const changes = transitions(data?.history ?? []);
  const categories = Object.entries(m?.error_categories ?? {}).sort(
    (a, b) => b[1] - a[1],
  );
  const windowMinutes = data?.integration.evaluation_window_minutes ?? 15;
  return (
    <Shell
      tenantName={workspace?.tenant_name}
      onAuth={() => {
        setScope((value) => value + 1);
      }}
    >
      <Link
        href="/integrations"
        className="mb-6 inline-flex items-center gap-2 text-xs font-medium text-teal"
      >
        <ArrowLeft size={14} />
        All integrations
      </Link>
      {error && (
        <ErrorNotice
          message={error}
          retained={!!data}
          retry={() => void reload()}
        />
      )}
      {!data && !error && (
        <LoadingState label="Loading integration evidence…" />
      )}
      {data && (
        <>
          <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow mb-2">
                {typeName(data.integration.category)} / {workspace?.tenant_name}
              </p>
              <h1 className="text-3xl font-semibold tracking-tight">
                {data.integration.name}
              </h1>
              <p className="muted mt-2">
                {data.integration.owner} · Evaluated {time(s?.evaluated_at)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-right">
                <p className="mb-1 text-[12px] uppercase text-slate-500">
                  Current evidence
                </p>
                <StatusBadge
                  status={
                    data.freshness?.current_evidence_status === "UNKNOWN" ||
                    stale
                      ? "unknown"
                      : (s?.status ?? "unknown")
                  }
                />
              </div>
              <button
                className="button-secondary"
                disabled={fetching}
                onClick={() => void reload()}
              >
                <RefreshCw
                  size={14}
                  className={fetching ? "animate-spin" : ""}
                />
                Reload evidence
              </button>
            </div>
          </div>
          <nav
            aria-label="Investigation sections"
            className="mb-6 flex flex-wrap gap-4 text-xs font-semibold text-teal"
          >
            <a href="#health-decision">Decision & evidence</a>
            <a href="#ai-investigation">AI incident brief</a>
            <a href="#incident-timeline">Timeline & recovery</a>
          </nav>
          {stale && (
            <div className="mb-6 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
              <Clock3 size={17} className="mt-1 shrink-0" />
              <p>
                {s
                  ? "Evaluation overdue. The recorded decision and measurements below are historical; verify fresh evidence before acting."
                  : "No evaluation is available. Receive request logs, then evaluate this integration from the dashboard."}
              </p>
            </div>
          )}
          <section
            id="health-decision"
            className="card mb-6 scroll-mt-6 p-5 md:p-6"
          >
            <p className="eyebrow">
              Health decision · Deterministic health policy
            </p>
            <h2 className="mb-3 mt-2 text-lg font-semibold">
              Why this needs attention
            </h2>
            <p className="text-base leading-7">
              {data.freshness?.current_evidence_status === "UNKNOWN" || stale
                ? "Current evidence is insufficient or out of date. Check telemetry delivery before relying on the recorded decision below."
                : (s?.reason_text ??
                  "No health decision has been calculated yet.")}
            </p>
            <div className="my-4">
              <Trend
                current={s ?? null}
                previous={data.history.find(
                  (point) => s && point.bucket < s.bucket,
                )}
              />
            </div>
            <div className="grid grid-cols-2 gap-4 border-t border-slate-100 pt-4 text-xs md:grid-cols-4">
              <div>
                <p className="text-slate-500">Evidence</p>
                <p className="mt-1 font-medium">
                  {s
                    ? s.evidence_sufficient
                      ? "Sufficient traffic"
                      : "Insufficient evidence"
                    : "Not evaluated"}
                </p>
              </div>
              <div>
                <p className="text-slate-500">Window ended</p>
                <p className="mt-1 font-medium">{time(s?.bucket)}</p>
              </div>
              <div>
                <p className="text-slate-500">Consecutive bad windows</p>
                <p className="mt-1 font-medium">
                  {s?.bad_window_streak ?? "—"}
                </p>
              </div>
              <div>
                <p className="text-slate-500">Healthy recovery windows</p>
                <p className="mt-1 font-medium">
                  {s?.healthy_window_streak ?? "—"}
                </p>
              </div>
            </div>
            {s && (
              <details className="mt-5 border-t border-slate-100 pt-4">
                <summary className="cursor-pointer text-xs font-medium text-teal">
                  Policy and audit evidence
                </summary>
                <div className="mt-3 space-y-2 text-xs leading-6 text-slate-600">
                  <p>
                    Error warning ≥{" "}
                    {percent(s.evidence.thresholds.error_warning)} · Critical ≥{" "}
                    {percent(s.evidence.thresholds.error_critical)}
                  </p>
                  <p>
                    Latency warning ≥{" "}
                    {s.evidence.thresholds.latency_warning_multiplier}× ·
                    Critical ≥{" "}
                    {s.evidence.thresholds.latency_critical_multiplier}×
                  </p>
                  <p>
                    P50 {ms(m?.p50_ms)} · P99 {ms(m?.p99_ms)} · Baseline P95{" "}
                    {s.evidence.baseline_used
                      ? ms(m?.baseline?.p95_ms)
                      : "No eligible healthy baseline"}
                  </p>
                  <p>
                    Last request {time(m?.last_request_at)} · Expected freshness{" "}
                    {data.integration.max_gap_minutes}m
                  </p>
                  <p>
                    Observed {s.observed_status} · Reason {s.reason_code}
                  </p>
                  <p>Policy {s.evidence.policy_version}</p>
                  <p className="break-all font-mono text-[12px]">
                    Snapshot {s.id}
                  </p>
                </div>
              </details>
            )}
          </section>
          <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4 text-xs leading-6 text-slate-600">
            <p>
              Freshness:{" "}
              {data.freshness?.status.replaceAll("_", " ") ??
                "Awaiting telemetry"}{" "}
              · Last event observed{" "}
              {data.freshness?.last_event_at
                ? time(data.freshness.last_event_at)
                : "No observed events"}{" "}
              · Last event received{" "}
              {data.freshness?.last_event_received_at
                ? time(data.freshness.last_event_received_at)
                : "No events received"}
            </p>
            <p>
              Last evaluated {time(s?.evaluated_at)} · Recorded health{" "}
              {s?.status ?? "unknown"} · Telemetry activity interval{" "}
              {data.integration.max_gap_minutes}m
            </p>
            <p>
              No observed errors means only that no failures were recorded;
              fresh traffic and sufficient evidence are required for HEALTHY.
            </p>
          </div>
          <div className="mb-6">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3 rounded-xl border border-teal/20 bg-teal/5 p-5">
              <div className="max-w-3xl">
                <h2 className="text-sm font-semibold">
                  Investigation guidance
                </h2>
                <p className="mt-2 text-sm leading-6">
                  {investigationGuidance(
                    {
                      integration: data.integration,
                      snapshot: data.snapshot,
                      previous_snapshot: null,
                      stale,
                      freshness: data.freshness,
                    },
                    checkedAt,
                  )}
                </p>
                <p className="mt-2 text-xs text-slate-600">
                  Scope: {workspace?.tenant_name} / {data.integration.name} ·
                  Owner: {data.integration.owner}. Customer or employee impact
                  is not measured by these request logs.
                </p>
              </div>
              <a href="#ai-investigation" className="button-secondary">
                AI-assisted investigation ↓
              </a>
            </div>
          </div>
          <h2 className="mb-3 text-sm font-semibold">Current evidence</h2>
          <div className="mb-6 grid grid-cols-2 gap-3 xl:grid-cols-4">
            {[
              {
                label: "Error rate",
                value: percent(m?.error_rate),
                hint: s
                  ? `${m?.error_count ?? 0} failed / ${m?.request_count ?? 0} attempts`
                  : "No measured requests",
              },
              {
                label: "P95 latency",
                value: ms(m?.p95_ms),
                hint: `Configured target ${ms(data.integration.latency_target_ms)}`,
              },
              {
                label: "Request volume",
                value: m?.request_count.toLocaleString() ?? "—",
                hint: `${data.integration.min_requests} requests for sufficient evidence`,
              },
              {
                label: "Timeout rate",
                value: percent(m?.timeout_rate),
                hint: `${windowMinutes}m rolling window · All outcomes included`,
              },
            ].map((card) => (
              <div key={card.label} className="card p-4 md:p-5">
                <p className="text-xs font-medium text-slate-500">
                  {card.label}
                </p>
                <p className="my-4 text-2xl font-semibold tabular-nums">
                  {card.value}
                </p>
                <p className="text-xs leading-5 text-slate-500">{card.hint}</p>
              </div>
            ))}
          </div>
          <MetricHistory history={data.history} />
          <div className="mb-6 grid gap-5 xl:grid-cols-[1.5fr_1fr]">
            <section className="card min-w-0 p-5 md:p-6">
              <div className="mb-4 flex flex-wrap justify-between gap-2">
                <h2 className="font-semibold">Health-state transitions</h2>
                <span className="text-xs text-slate-500">
                  Last 24h · Up to 288 evaluations
                </span>
              </div>
              <History snapshots={data.history} />
              <p className="mt-2 text-[13px] text-slate-500">
                Oldest → newest · Green healthy / Amber degraded / Red unhealthy
                / Gray unknown
              </p>
              <div className="mt-4 max-h-72 overflow-y-auto">
                {changes.map(({ snapshot, previous }) => (
                  <div
                    key={snapshot.id}
                    className="border-t border-slate-100 py-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={previous} />
                      <ArrowRight size={13} className="text-slate-500" />
                      <StatusBadge status={snapshot.status} />
                      <span className="ml-auto text-xs text-slate-500">
                        {time(snapshot.bucket)}
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-slate-600">
                      {snapshot.reason_text}
                    </p>
                  </div>
                ))}
                {!changes.length && (
                  <p className="muted py-3">
                    {data.history.length
                      ? "No state changes in the available history."
                      : "No health evaluations yet."}
                  </p>
                )}
              </div>
            </section>
            <section className="card p-5 md:p-6">
              <h2 className="font-semibold">Top error categories</h2>
              <p className="muted mt-1">
                Current {windowMinutes}m evaluation window
              </p>
              <div className="mt-5 space-y-4">
                {categories.slice(0, 5).map(([category, count]) => (
                  <div key={category}>
                    <div className="flex justify-between text-xs">
                      <span className="font-medium capitalize">
                        {category.replaceAll("_", " ")}
                      </span>
                      <span className="text-slate-500">
                        {count} ·{" "}
                        {percent(m?.error_count ? count / m.error_count : 0)} of
                        errors
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-100">
                      <div
                        className="h-full rounded bg-rose-500"
                        style={{
                          width: `${m?.error_count ? (count / m.error_count) * 100 : 0}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              {!categories.length && (
                <p className="muted mt-5">
                  {m?.request_count
                    ? "No failures observed in this window."
                    : "No request evidence available."}
                </p>
              )}
            </section>
          </div>
          <section
            id="incident-timeline"
            className="card mb-6 scroll-mt-6 p-5 md:p-6"
          >
            <div className="mb-4 flex flex-wrap justify-between gap-2">
              <h2 className="font-semibold">Incident timeline & recovery</h2>
              <span className="text-xs text-slate-500">
                Latest 20 · Confirmed by deterministic policy
              </span>
            </div>
            {data.incidents.map((incident) => (
              <div
                key={incident.id}
                id={`incident-${incident.id}`}
                className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 py-4"
              >
                <div>
                  <span
                    className={`rounded border px-2 py-1 text-[13px] font-semibold ${incident.resolved_at ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-rose-200 bg-rose-50 text-rose-800"}`}
                  >
                    {incident.resolved_at ? "Resolved" : "Open"}
                  </span>
                  <p className="mt-3 text-sm">
                    Detected / opened {time(incident.opened_at)}
                  </p>
                </div>
                <div className="w-full text-xs leading-6 text-slate-600">
                  <p className="mb-2 font-medium">
                    {incident.resolved_at ? "Confirmed duration" : "Open for"}:{" "}
                    {incidentDuration(incident, checkedAt)}
                  </p>
                  <p>
                    Deterministic trigger:{" "}
                    {incident.opening_reason_text ??
                      "See original snapshot evidence."}
                  </p>
                  <p>
                    Recovery began{" "}
                    {incident.recovery_began_at
                      ? time(incident.recovery_began_at)
                      : "Not yet confirmed"}{" "}
                    · Healthy windows {incident.healthy_windows_observed ?? 0}/
                    {incident.healthy_windows_required ?? "unknown"}
                  </p>
                  <p>{incident.recovery_condition}</p>
                  <p className="text-xs text-slate-600">
                    {incident.resolved_at
                      ? `Resolved ${time(incident.resolved_at)} after sustained recovery`
                      : `${incident.recovery_streak} consecutive healthy recovery windows`}
                  </p>
                  {incident.resolved_at && (
                    <RecoverySummary
                      key={`${incident.id}:${scope}`}
                      incident={incident}
                      integrationId={id}
                      operator={workspace?.role === "operator"}
                    />
                  )}
                </div>
              </div>
            ))}
            {!!data.incidents.length && (
              <p className="mt-3 text-xs text-slate-500">
                Timeline records detection and recovery. Operator investigations
                and customer-impact times are not recorded.
              </p>
            )}
            {!data.incidents.length && (
              <p className="muted">
                No incidents have been confirmed for this integration.
              </p>
            )}
          </section>
          <IncidentAssistant
            key={`${id}:${scope}:${s?.id}`}
            detail={data}
            operator={workspace?.role === "operator"}
          />
          <details className="card overflow-hidden">
            <summary className="cursor-pointer p-5 text-sm font-semibold">
              Recent request logs{" "}
              <span className="ml-2 text-xs font-normal text-slate-500">
                Latest 50 · Sanitized metadata
              </span>
            </summary>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[650px] text-left text-xs">
                <caption className="sr-only">
                  Recent sanitized request logs, newest first
                </caption>
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    {[
                      "Occurred at",
                      "HTTP status",
                      "Duration",
                      "Error category",
                      "Request ID",
                    ].map((h) => (
                      <th scope="col" key={h} className="p-4 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.logs.map((log) => (
                    <tr key={log.event_id}>
                      <td className="p-4">{time(log.occurred_at)}</td>
                      <td
                        className={`p-4 font-medium ${log.status_code >= 400 || log.timed_out ? "text-rose-700" : "text-emerald-700"}`}
                      >
                        {log.timed_out ? "Timeout" : log.status_code}
                      </td>
                      <td className="p-4 font-mono">{ms(log.latency_ms)}</td>
                      <td className="p-4">{log.error_category}</td>
                      <td
                        className="max-w-48 truncate p-4 font-mono text-slate-500"
                        title={log.event_id}
                      >
                        {log.event_id}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.logs.length && (
              <p className="muted p-5">
                No request telemetry has been received.
              </p>
            )}
          </details>
        </>
      )}
    </Shell>
  );
}

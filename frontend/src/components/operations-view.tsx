"use client";
import { useCallback, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  RefreshCw,
  Search,
  CheckCircle2,
  AlertTriangle,
  CircleHelp,
  OctagonAlert,
  ArrowUpRight,
  Clock3,
} from "lucide-react";
import { Shell } from "@/components/shell";
import { StatusBadge } from "@/components/status";
import { ErrorNotice, LoadingState } from "@/components/async-state";
import { DemoGuide } from "@/components/demo-guide";
import { IncidentList } from "@/components/incident-list";
import { OperationsAssistant } from "@/components/operations-assistant";
import { MorningSummary } from "@/components/morning-summary";
import { OperationalImpact } from "@/components/operational-impact";
import { Trend } from "@/components/trend";
import { api, percent, ms, time, typeName, setTenant } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { useDemoAccess } from "@/lib/demo-context";
import {
  compareCurrentPriority,
  currentEvidenceState,
  isStale,
  needsAttention,
  investigationGuidance,
} from "@/lib/health-view";
import type { Dashboard, Status, Workspace, Incident } from "@/types";

export function OperationsView({
  view = "overview",
}: {
  view?: "overview" | "integrations" | "incidents" | "assistant";
}) {
  const demo = useDemoAccess();
  const [scope, setScope] = useState(0);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [actionError, setActionError] = useState("");
  const [actionSuccess, setActionSuccess] = useState("");
  const loader = useCallback(
    async (signal: AbortSignal) => {
      void scope;
      const [dashboard, workspace, incidentFeed] = await Promise.all([
        api<Dashboard>("/api/v1/dashboard", "GET", signal),
        api<Workspace>("/api/workspace", "GET", signal),
        api<{ items: Incident[]; total: number }>(
          "/api/incidents?limit=100",
          "GET",
          signal,
        ),
      ]);
      return { dashboard, workspace, incidentFeed };
    },
    [scope],
  );
  const { data, error, fetching, loadedAt, checkedAt, reload } =
    useResource(loader);
  const dashboard = data?.dashboard,
    workspace = data?.workspace;
  const items = [...(dashboard?.integrations ?? [])].sort((a, b) =>
    compareCurrentPriority(a, b, checkedAt),
  );
  const counts: Record<Status, number> = {
    healthy: 0,
    degraded: 0,
    unhealthy: 0,
    unknown: 0,
  };
  items.forEach((row) => counts[currentEvidenceState(row, checkedAt)]++);
  const types = [
    ...new Set(items.map((row) => row.integration.category)),
  ].sort();
  const filtered = items.filter(
    (row) =>
      (statusFilter === "all" ||
        currentEvidenceState(row, checkedAt) === statusFilter) &&
      (typeFilter === "all" || row.integration.category === typeFilter) &&
      `${row.integration.name} ${row.integration.category} ${row.integration.owner}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const attention = filtered.filter((row) => needsAttention(row, checkedAt));
  const visible = attentionOnly ? attention : filtered;
  const overdue = items.filter((row) => isStale(row, checkedAt)).length;
  const lowVolume = items.filter(
    (row) =>
      currentEvidenceState(row, checkedAt) === "unknown" &&
      row.snapshot?.reason_code === "INSUFFICIENT_REQUESTS",
  ).length;
  const staleTelemetry = items.filter(
    (row) =>
      row.freshness?.status === "STALE_TELEMETRY" ||
      row.freshness?.status === "NO_TELEMETRY",
  ).length;
  function resetFilters() {
    setQuery("");
    setStatusFilter("all");
    setTypeFilter("all");
    setAttentionOnly(false);
  }
  function changeScope(tenant?: string) {
    if (tenant !== undefined) setTenant(tenant);
    setActionError("");
    setScope((value) => value + 1);
  }
  async function evaluate() {
    setEvaluating(true);
    setActionError("");
    setActionSuccess("");
    try {
      await api("/api/evaluate", "POST");
      await reload();
      setActionSuccess("Health evaluated. Current evidence is shown below.");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Evaluation failed.");
    } finally {
      setEvaluating(false);
    }
  }
  const Counter = view === "integrations" ? "button" : "div";
  return (
    <Shell tenantName={workspace?.tenant_name} onAuth={() => changeScope()}>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow mb-2">Operations / Live evidence</p>
          <h1 className="text-3xl font-semibold tracking-tight">
            {view === "overview"
              ? "Integration operations"
              : view === "integrations"
                ? "Integrations"
                : view === "incidents"
                  ? "Incidents"
                  : "AI Operations Assistant"}
          </h1>
          <p className="muted mt-2">
            {view === "overview"
              ? "Detect integration failures before customers report them."
              : view === "integrations"
                ? "Health, freshness and trends across your connected systems."
                : view === "incidents"
                  ? "Track confirmed failures, investigation evidence and recovery."
                  : "Ask about priorities, changes and investigation evidence in this workspace."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="button-secondary"
            onClick={() => void reload()}
            disabled={fetching || evaluating}
          >
            <RefreshCw size={14} className={fetching ? "animate-spin" : ""} />
            {fetching ? "Loading…" : "Reload view"}
          </button>
          <button
            className="button"
            onClick={() => void evaluate()}
            disabled={
              !data || evaluating || fetching || workspace?.role !== "operator"
            }
            title={
              workspace?.role === "reader"
                ? "An operator token is required to evaluate."
                : "Evaluate the current window; does not create synthetic traffic."
            }
          >
            <RefreshCw size={14} className={evaluating ? "animate-spin" : ""} />
            {evaluating ? "Evaluating…" : "Evaluate now"}
          </button>
        </div>
      </div>

      {actionSuccess && (
        <p
          role="status"
          className="mb-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900"
        >
          {actionSuccess}
        </p>
      )}
      {(error || actionError) && (
        <ErrorNotice
          message={actionError || error}
          retained={!!data}
          retry={() => {
            setActionError("");
            void reload();
          }}
        />
      )}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-xs font-medium text-slate-600">
          Tenant
          <select
            aria-label="Filter by tenant"
            className="filter-select max-w-64"
            value={workspace?.tenant_id ?? ""}
            disabled={
              !workspace ||
              !workspace.can_switch_tenants ||
              fetching ||
              evaluating
            }
            onChange={(e) => changeScope(e.target.value)}
          >
            {!workspace && (
              <option value="">
                {error ? "Workspace unavailable" : "Loading workspace…"}
              </option>
            )}
            {workspace?.tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs text-slate-500" aria-live="polite">
          {loadedAt
            ? `View loaded ${time(new Date(loadedAt).toISOString())} · Auto-refresh 60s`
            : error
              ? "No telemetry connection"
              : "Waiting for telemetry"}
          {workspace?.role === "reader" ? " · Read-only access" : ""}
        </p>
      </div>
      {data && view === "overview" && (
        <MorningSummary items={items} now={checkedAt} />
      )}
      {data && workspace && view === "assistant" && (
        <OperationsAssistant
          key={`${workspace.tenant_id}:${scope}`}
          operator={workspace.role === "operator"}
        />
      )}
      {!!overdue && view !== "assistant" && (
        <div className="mb-6 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
          <Clock3 size={15} className="mt-0.5 shrink-0" />
          <p>
            {overdue} integration{overdue === 1 ? " needs" : "s need"} fresh
            evaluation. Check telemetry and evaluate before relying on recorded
            health.
          </p>
        </div>
      )}
      {!data && !error && <LoadingState />}
      {!!items.length && (view === "overview" || view === "integrations") && (
        <h2 className="mb-3 text-sm font-semibold">Fleet at a glance</h2>
      )}
      {!!items.length && (view === "overview" || view === "integrations") && (
        <div className="mb-6 grid grid-cols-2 gap-3 xl:grid-cols-4">
          {(
            [
              [
                "healthy",
                "Healthy",
                CheckCircle2,
                "text-emerald-700",
                "Within the configured policy",
              ],
              [
                "degraded",
                "Degraded",
                AlertTriangle,
                "text-amber-700",
                "Warning or pending confirmation",
              ],
              [
                "unhealthy",
                "Unhealthy",
                OctagonAlert,
                "text-rose-700",
                "Confirmed or sustained failure",
              ],
              [
                "unknown",
                "Unknown",
                CircleHelp,
                "text-slate-600",
                [
                  lowVolume ? `${lowVolume} low-volume` : "",
                  staleTelemetry ? `${staleTelemetry} stale / absent` : "",
                  overdue ? `${overdue} overdue` : "",
                ]
                  .filter(Boolean)
                  .join(" · ") || "No current evidence gaps",
              ],
            ] as const
          ).map(([status, label, Icon, color, hint]) => (
            <Counter
              key={status}
              onClick={
                view === "integrations"
                  ? () =>
                      setStatusFilter(statusFilter === status ? "all" : status)
                  : undefined
              }
              aria-pressed={
                view === "integrations" ? statusFilter === status : undefined
              }
              className={`card p-3 text-left ${statusFilter === status ? "ring-2 ring-teal" : "hover:border-slate-300"}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-slate-600">
                  {label}
                </span>
                <Icon size={18} className={color} />
              </div>
              <p className={`mt-2 text-xl font-semibold tabular-nums ${color}`}>
                {data ? counts[status] : "—"}
              </p>
              <p className="mt-2 text-xs leading-5 text-slate-500">{hint}</p>
            </Counter>
          ))}
        </div>
      )}

      {data && (
        <>
          {!!items.length && view === "overview" && (
            <section
              className="card mb-6 overflow-hidden"
              aria-labelledby="attention-title"
            >
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-5">
                <div>
                  <h2
                    id="attention-title"
                    className="flex items-center gap-2 font-semibold"
                  >
                    <AlertTriangle size={17} className="text-amber-700" />
                    Needs attention{" "}
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                      {attention.length}
                    </span>
                  </h2>
                  <p className="mt-1 text-xs text-slate-500">
                    Prioritized by current evidence · Evidence gaps included ·
                    Open Integrations to filter the fleet
                  </p>
                </div>
                <span className="text-xs text-slate-500">
                  {dashboard?.incidents.length ?? 0} open incidents in this
                  tenant
                </span>
              </div>
              {attention.slice(0, 3).map((row) => {
                const s = row.snapshot;
                const incident = dashboard?.incidents.find(
                  (item) => item.integration_id === row.integration.id,
                );
                return (
                  <Link
                    key={row.integration.id}
                    href={`/integrations/${encodeURIComponent(row.integration.id)}`}
                    className="grid gap-3 border-b border-slate-100 p-5 last:border-b-0 hover:bg-slate-50 md:grid-cols-[minmax(180px,1fr)_2fr_auto]"
                  >
                    <div>
                      <p className="text-sm font-semibold">
                        {row.integration.name}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <StatusBadge
                          status={currentEvidenceState(row, checkedAt)}
                        />
                        {isStale(row, checkedAt) && (
                          <span className="text-[13px] font-medium text-amber-800">
                            Evaluation overdue
                          </span>
                        )}
                      </div>
                    </div>
                    <div>
                      <p className="mb-1 text-[12px] font-semibold uppercase tracking-wider text-slate-500">
                        Reason / What changed
                      </p>
                      <p className="text-sm leading-6 text-slate-700">
                        {currentEvidenceState(row, checkedAt) === "unknown"
                          ? "Current evidence is insufficient or out of date. Confirm telemetry before relying on the recorded health decision."
                          : s?.reason_text}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        Scope: {workspace?.tenant_name} ·{" "}
                        {row.integration.owner} · Evaluated{" "}
                        {time(s?.evaluated_at)} · Last telemetry{" "}
                        {row.freshness?.last_event_at
                          ? time(row.freshness.last_event_at)
                          : "None received"}
                      </p>
                      <p className="mt-2 text-xs font-mono text-slate-700">
                        {percent(s?.evidence.metrics.error_rate)} errors · P95{" "}
                        {ms(s?.evidence.metrics.p95_ms)} ·{" "}
                        {s?.evidence.metrics.request_count ?? "—"} requests
                      </p>
                      {incident && (
                        <p className="mt-1 text-xs text-slate-500">
                          Incident opened {time(incident.opened_at)} ·{" "}
                          {Math.max(
                            0,
                            Math.floor(
                              (checkedAt - Date.parse(incident.opened_at)) /
                                60000,
                            ),
                          )}{" "}
                          min open
                          {incident.recovery_streak > 0
                            ? " · Recovery observed"
                            : ""}
                        </p>
                      )}
                      <p className="mt-2 text-xs font-medium text-slate-700">
                        First check: {investigationGuidance(row, checkedAt)}
                      </p>
                      <div className="mt-2">
                        <Trend current={s} previous={row.previous_snapshot} />
                      </div>
                    </div>
                    <span className="inline-flex items-center gap-1 self-center text-xs font-medium text-teal">
                      Investigate <ArrowRight size={14} />
                    </span>
                  </Link>
                );
              })}
              {attention.length === 0 && (
                <div className="p-6">
                  <p className="text-sm font-medium">
                    {filtered.length
                      ? "No attention items in this view."
                      : "No integrations match these filters."}
                  </p>
                  <p className="muted mt-1">
                    {filtered.length
                      ? "The matching integrations have healthy, recent evidence."
                      : "Clear filters to see other connections."}
                  </p>
                </div>
              )}
              {attention.length > 3 && (
                <Link
                  href="/integrations"
                  className="block border-t border-slate-100 p-3 text-sm font-medium text-teal"
                >
                  View all {attention.length} attention items →
                </Link>
              )}
            </section>
          )}
          {view === "overview" && !!items.length && (
            <>
              <section className="card mb-6 p-5">
                <h2 className="font-semibold">
                  Need an investigation starting point?
                </h2>
                <p className="mt-2 text-sm text-slate-600">
                  Ask AI to explain priorities and recommend checks, using your
                  workspace evidence.
                </p>
                <Link href="/assistant" className="button-secondary mt-3">
                  Open AI assistant →
                </Link>
              </section>
              <IncidentList
                incidents={
                  data.incidentFeed?.items ?? dashboard?.incidents ?? []
                }
                integrations={items}
                now={checkedAt}
                compact
              />
            </>
          )}
          {!!items.length && dashboard && view === "overview" && (
            <OperationalImpact
              dashboard={dashboard}
              counts={counts}
              demoWorkspace={demo}
            />
          )}
          {view === "overview" && (demo || workspace?.mode === "demo") && (
            <DemoGuide items={items} onRefresh={() => void reload()} />
          )}
          {view === "integrations" && (
            <>
              {" "}
              <div className="mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4">
                <label className="flex h-10 min-w-48 flex-1 items-center gap-2 rounded-lg border border-slate-200 px-3">
                  <Search size={15} className="text-slate-500" />
                  <input
                    aria-label="Search integrations"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search integration or owner"
                    className="w-full bg-transparent text-xs outline-none"
                  />
                </label>
                <select
                  className="filter-select"
                  aria-label="Filter by status"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="all">All statuses</option>
                  {Object.keys(counts).map((status) => (
                    <option key={status} value={status}>
                      {status[0].toUpperCase() + status.slice(1)}
                    </option>
                  ))}
                </select>
                <select
                  className="filter-select"
                  aria-label="Filter by integration type"
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                >
                  <option value="all">All integration types</option>
                  {types.map((type) => (
                    <option key={type} value={type}>
                      {typeName(type)}
                    </option>
                  ))}
                </select>
                <button
                  className="text-xs font-medium text-teal underline-offset-4 hover:underline"
                  onClick={resetFilters}
                >
                  Clear filters
                </button>
              </div>
              <section
                id="integration-list"
                className="card scroll-mt-6 overflow-hidden"
                aria-labelledby="systems-title"
              >
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-5">
                  <h2 id="systems-title" className="font-semibold">
                    Connected systems{" "}
                    <span className="ml-2 text-xs font-normal text-slate-500">
                      {visible.length} of {items.length}
                    </span>
                  </h2>
                  <label className="flex items-center gap-2 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={attentionOnly}
                      onChange={(e) => setAttentionOnly(e.target.checked)}
                      className="accent-teal"
                    />
                    Attention only
                  </label>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[1120px] text-left text-xs">
                    <caption className="sr-only">
                      Integration health, deterministic reason and window
                      metrics, ordered by severity
                    </caption>
                    <thead className="bg-slate-50 text-[12px] uppercase tracking-wider text-slate-500">
                      <tr>
                        {[
                          "Integration / reason",
                          "Current evidence",
                          "Error rate",
                          "P95 latency",
                          "Requests",
                          "Recent direction",
                          "Last evaluated",
                          "Telemetry",
                          "",
                        ].map((h, i) => (
                          <th
                            scope="col"
                            key={i}
                            className="px-5 py-3 font-medium"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {visible.map((row) => {
                        const s = row.snapshot,
                          m = s?.evidence.metrics;
                        return (
                          <tr
                            key={row.integration.id}
                            className="hover:bg-slate-50"
                          >
                            <td className="max-w-96 px-5 py-5">
                              <Link
                                href={`/integrations/${encodeURIComponent(row.integration.id)}`}
                                className="text-sm font-semibold hover:text-teal"
                              >
                                {row.integration.name}
                              </Link>
                              <p className="mt-1 text-[13px] text-slate-500">
                                {typeName(row.integration.category)} ·{" "}
                                {row.integration.evaluation_window_minutes}m
                                window
                              </p>
                              <p className="mt-2 max-w-80 text-xs leading-5 text-slate-600">
                                {currentEvidenceState(row, checkedAt) ===
                                "unknown"
                                  ? "Insufficient or out-of-date evidence. Check telemetry and request volume."
                                  : (s?.reason_text ??
                                    "Not evaluated; awaiting telemetry.")}
                              </p>
                            </td>
                            <td className="px-5">
                              <StatusBadge
                                status={currentEvidenceState(row, checkedAt)}
                              />
                              {isStale(row, checkedAt) && (
                                <p className="mt-2 text-[13px] text-amber-800">
                                  Evaluation overdue
                                </p>
                              )}
                            </td>
                            <td className="px-5 font-mono tabular-nums">
                              {percent(m?.error_rate)}
                            </td>
                            <td className="px-5 font-mono tabular-nums">
                              {ms(m?.p95_ms)}
                            </td>
                            <td className="px-5 tabular-nums">
                              {m?.request_count.toLocaleString() ?? "—"}
                            </td>
                            <td className="max-w-40 px-5">
                              <Trend
                                current={s}
                                previous={row.previous_snapshot}
                              />
                            </td>
                            <td className="px-5 text-slate-500">
                              {time(s?.evaluated_at)}
                            </td>
                            <td className="px-5 text-slate-600">
                              <p>
                                {row.freshness?.status === "RECENT_TRAFFIC"
                                  ? "Fresh"
                                  : row.freshness?.status === "STALE_TELEMETRY"
                                    ? "Stale"
                                    : "No telemetry"}
                              </p>
                              <p className="mt-1 text-xs">
                                {time(row.freshness?.last_event_at)}
                              </p>
                            </td>
                            <td className="pr-5">
                              <Link
                                aria-label={`View ${row.integration.name}`}
                                href={`/integrations/${encodeURIComponent(row.integration.id)}`}
                                className="inline-flex rounded p-2 text-teal hover:bg-teal/10"
                              >
                                <ArrowUpRight size={17} />
                              </Link>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {!visible.length && (
                  <div className="p-8 text-center">
                    <p className="text-sm font-medium">
                      {items.length
                        ? "No integrations match this view."
                        : "No integrations connected yet."}
                    </p>
                    <p className="muted mt-1">
                      {items.length
                        ? "Adjust the status, type or attention filters."
                        : "Provision integrations and ingest request events to begin monitoring."}
                    </p>
                    <button
                      className="button-secondary mt-4"
                      onClick={resetFilters}
                    >
                      Clear filters
                    </button>
                  </div>
                )}
                <div className="flex flex-wrap justify-between gap-2 border-t border-slate-100 px-5 py-3 text-[13px] text-slate-500">
                  <span>
                    Counts describe current evidence; historical decisions are
                    retained.
                  </span>
                  <span>
                    Open an integration for history and policy details.
                  </span>
                </div>
              </section>
            </>
          )}
          {view === "incidents" && (
            <>
              <p className="mb-4 text-sm text-slate-600">
                Latest {data.incidentFeed?.items.length ?? 0} of{" "}
                {data.incidentFeed?.total ?? 0} incidents · Active first ·
                Evidence and recovery remain available in detail.
              </p>
              <IncidentList
                incidents={data.incidentFeed?.items ?? []}
                integrations={items}
                now={checkedAt}
              />
            </>
          )}
        </>
      )}
    </Shell>
  );
}

import Link from "next/link";
import {
  currentEvidenceState,
  direction,
  isStale,
  needsAttention,
} from "@/lib/health-view";
import type { IntegrationRow } from "@/types";

export function MorningSummary({
  items,
  now,
}: {
  items: IntegrationRow[];
  now: number;
}) {
  const attention = items.filter((row) => needsAttention(row, now));
  const gaps = items.filter(
    (row) => currentEvidenceState(row, now) === "unknown",
  );
  const trends = items
    .filter((row) => !gaps.includes(row))
    .map((row) => direction(row.snapshot, row.previous_snapshot));
  const worsening = trends.filter((trend) => trend.kind === "up").length;
  const improving = trends.filter((trend) => trend.kind === "down").length;
  const overdue = gaps.filter(
    (row) => isStale(row, now) || row.freshness?.status !== "RECENT_TRAFFIC",
  ).length;
  if (
    !items.length ||
    items.every((row) => row.freshness?.status === "NO_TELEMETRY")
  )
    return <EmptyTelemetry />;
  return (
    <section
      className="mb-5 rounded-xl border border-teal/20 bg-white p-5 md:p-6"
      aria-labelledby="morning-title"
    >
      <p className="eyebrow mb-2">Morning operations / Current workspace</p>
      <h2 id="morning-title" className="text-2xl font-semibold tracking-tight">
        {attention.length
          ? `${attention.length} integration${attention.length === 1 ? " needs" : "s need"} attention`
          : "All monitored integrations are operating within policy"}
      </h2>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        {attention.length
          ? `Start with ${attention[0].integration.name}. Review the evidence and choose the next investigation.`
          : "Recent telemetry supports the current decisions. Continue observing for changes."}
      </p>
      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-slate-100 pt-3 text-xs text-slate-600">
        <span>
          {gaps.length
            ? `${gaps.length} evidence gaps · ${overdue} stale, absent or overdue`
            : "Fresh, sufficient evidence across the fleet"}
        </span>
        <span>
          {trends.some((trend) => trend.kind !== "none")
            ? `${improving} improving · ${worsening} worsening · Compared with prior window`
            : "Direction awaiting comparable recent windows"}
        </span>
        <a href="#attention-title" className="font-semibold text-teal">
          Review priorities ↓
        </a>
      </div>
    </section>
  );
}

export function EmptyTelemetry() {
  return (
    <section className="card mb-6 p-6" aria-labelledby="empty-title">
      <p className="eyebrow mb-2">Start observing</p>
      <h2 id="empty-title" className="text-xl font-semibold">
        No telemetry has been connected yet.
      </h2>
      <p className="muted mt-2">
        Connect request logs to detect integration failures before Ops has to
        rely on a support ticket. Register an integration with your
        administrator, then choose a data source.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Link className="button" href="/data-sources#pilot-title">
          Upload logs
        </Link>
        <Link className="button-secondary" href="/data-sources#api-title">
          Connect Live API
        </Link>
      </div>
    </section>
  );
}

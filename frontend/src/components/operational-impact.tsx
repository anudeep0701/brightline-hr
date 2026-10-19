import type { Dashboard, Status } from "@/types";

export function OperationalImpact({
  dashboard,
  counts,
  demoWorkspace = false,
}: {
  dashboard: Dashboard;
  counts: Record<Status, number>;
  demoWorkspace?: boolean;
}) {
  const demo = demoWorkspace || dashboard.mode === "demo";
  const impact = dashboard.operational_impact;
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const duration = impact.mean_confirmed_incident_duration_seconds;
  const metrics = [
    [
      "Needs attention now",
      total - counts.healthy,
      "Includes unknown evidence",
    ],
    [
      "Healthy now",
      total ? `${Math.round((counts.healthy / total) * 100)}%` : "—",
      "Share of all tenant integrations",
    ],
    [
      "Incidents detected",
      impact.incidents_detected,
      "Confirmed openings · last 24h",
    ],
    [
      "Recovered incidents",
      impact.recovered_incidents,
      "Resolutions · last 24h",
    ],
    [
      "Mean confirmed duration",
      duration === null ? "—" : `${(duration / 60).toFixed(1)} min`,
      "Opening → resolution · resolved in last 24h",
    ],
  ] as const;
  return (
    <section className="card mb-6 p-5" aria-labelledby="impact-title">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="impact-title" className="text-sm font-semibold">
          {demo
            ? "Demo / simulated operational impact"
            : "Observed operational impact"}
        </h2>
        <span className="text-xs text-slate-500">
          Tenant-wide · Last 24h incident outcomes
        </span>
      </div>
      {demo && (
        <p className="mb-4 text-xs leading-5 text-slate-600">
          Calculated from synthetic request traffic and confirmed incidents.
          These demonstrate operational outcomes; production MTTD requires an
          independently recorded failure start time.
        </p>
      )}
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {metrics.map(([label, value, hint]) => (
          <div key={label} className="border-l-2 border-teal/20 pl-3">
            <dt className="text-xs font-medium text-slate-600">{label}</dt>
            <dd className="mt-2 text-xl font-semibold tabular-nums">{value}</dd>
            <p className="mt-1 text-[11px] leading-4 text-slate-500">{hint}</p>
          </div>
        ))}
      </dl>
      <p className="mt-4 border-t border-slate-100 pt-3 text-[11px] leading-5 text-slate-500">
        {counts.unknown} integrations have unknown current evidence. At last
        refresh, {impact.stale_or_absent_integrations} had stale or absent
        telemetry or overdue evaluations. Incident duration measures confirmed
        system state, not verified customer impact.
        {demo ? " Demo outcomes are not customer ROI." : ""}
      </p>
    </section>
  );
}

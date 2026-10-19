import Link from "next/link";
import { currentEvidenceState } from "@/lib/health-view";
import { time } from "@/lib/api";
import type { Incident, IntegrationRow } from "@/types";

export function incidentDuration(incident: Incident, now: number) {
  const minutes = Math.max(
    0,
    Math.floor(
      ((incident.resolved_at ? Date.parse(incident.resolved_at) : now) -
        Date.parse(incident.opened_at)) /
        60000,
    ),
  );
  return minutes >= 1440
    ? `${Math.floor(minutes / 1440)}d ${Math.floor((minutes % 1440) / 60)}h`
    : minutes >= 60
      ? `${Math.floor(minutes / 60)}h ${minutes % 60}m`
      : `${minutes}m`;
}

export function IncidentList({
  incidents,
  integrations,
  now,
  compact = false,
}: {
  incidents: Incident[];
  integrations: IntegrationRow[];
  now: number;
  compact?: boolean;
}) {
  const active = incidents.filter((item) => !item.resolved_at);
  const resolved = incidents.filter((item) => item.resolved_at);
  return (
    <div className="space-y-6">
      {[
        ["Active incidents", active],
        ["Recovery / resolved", resolved],
      ].map(([title, values]) => {
        const rows = values as Incident[];
        return (
          <section key={title as string} className="card overflow-hidden">
            <div className="flex flex-wrap justify-between gap-2 border-b border-slate-100 p-5">
              <h2 className="font-semibold">
                {title as string}{" "}
                <span className="ml-2 text-sm text-slate-600">
                  {rows.length}
                </span>
              </h2>
              {compact && (
                <Link
                  href="/incidents"
                  className="text-sm font-medium text-teal"
                >
                  View incidents →
                </Link>
              )}
            </div>
            {rows.slice(0, compact ? 2 : rows.length).map((incident) => {
              const row = integrations.find(
                (item) => item.integration.id === incident.integration_id,
              );
              return (
                <article
                  key={incident.id}
                  className="grid gap-3 border-t border-slate-100 p-5 first:border-t-0 md:grid-cols-[1fr_2fr_auto]"
                >
                  <div>
                    <Link
                      href={`/integrations/${encodeURIComponent(incident.integration_id)}#incident-${encodeURIComponent(incident.id)}`}
                      className="font-semibold text-teal"
                    >
                      {row?.integration.name ?? incident.integration_id}
                    </Link>
                    <p
                      className={`mt-2 text-sm font-medium ${incident.resolved_at ? "text-emerald-800" : "text-rose-800"}`}
                    >
                      {incident.resolved_at
                        ? "Resolved"
                        : "Open · Confirmed unhealthy"}
                    </p>
                    <p className="mt-1 text-sm text-slate-600">
                      {incidentDuration(incident, now)}{" "}
                      {incident.resolved_at ? "duration" : "open"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm leading-6">
                      {incident.resolved_at
                        ? "Recovery confirmed by the stored health policy."
                        : row && currentEvidenceState(row, now) === "unknown"
                          ? "Current evidence is insufficient or stale; this confirmed incident remains open."
                          : (row?.snapshot?.reason_text ??
                            incident.opening_reason_text ??
                            "Open the incident to inspect its recorded trigger.")}
                    </p>
                    <p className="mt-2 text-sm text-slate-600">
                      Started {time(incident.opened_at)}
                      {incident.resolved_at
                        ? ` · Resolved ${time(incident.resolved_at)}`
                        : ""}
                    </p>
                    {!compact && (
                      <>
                        <p className="mt-2 text-sm">
                          Recovery:{" "}
                          {incident.healthy_windows_observed ??
                            incident.recovery_streak}
                          /{incident.healthy_windows_required ?? "—"} healthy
                          windows confirmed.
                        </p>
                        <details className="mt-3 text-sm leading-6 text-slate-600">
                          <summary className="cursor-pointer font-medium">
                            Trigger and recovery requirements
                          </summary>
                          <p className="mt-2">
                            {incident.opening_reason_text ??
                              "Inspect the opening snapshot."}
                          </p>
                          <p>
                            {incident.recovery_condition ??
                              "Inspect the stored incident policy."}
                          </p>
                        </details>
                      </>
                    )}
                  </div>
                  <Link
                    className="self-start text-sm font-medium text-teal"
                    href={`/integrations/${encodeURIComponent(incident.integration_id)}#incident-${encodeURIComponent(incident.id)}`}
                  >
                    Inspect incident →
                  </Link>
                </article>
              );
            })}
            {!rows.length && (
              <p className="p-5 text-sm text-slate-600">
                {title === "Active incidents"
                  ? "No active incidents. Confirmed failures will appear here."
                  : "No resolved incidents yet. Recovery history will appear after the required healthy windows."}
              </p>
            )}
          </section>
        );
      })}
    </div>
  );
}

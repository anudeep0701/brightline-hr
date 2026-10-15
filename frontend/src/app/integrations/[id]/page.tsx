"use client";
import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Sparkles, RefreshCw } from "lucide-react";
import { Shell } from "@/components/shell";
import { StatusBadge, History } from "@/components/status";
import { api, percent, ms, time } from "@/lib/api";
import type { Detail, Explanation } from "@/types";
export default function DetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [checkedAt, setCheckedAt] = useState(Date.now());
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setCheckedAt(Date.now());
    try {
      const next = await api<Detail>(
        `/api/v1/integrations/${encodeURIComponent(id)}`,
      );
      setData(next);
      setError("");
      setExplanation((old) =>
        old?.snapshot_id === next.snapshot?.id ? old : null,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load");
    }
  }, [id]);
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 60000);
    return () => clearInterval(timer);
  }, [load]);
  async function explain() {
    setBusy(true);
    try {
      setExplanation(
        await api<Explanation>(
          `/api/v1/integrations/${encodeURIComponent(id)}/explanation`,
          "POST",
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Explanation failed");
    } finally {
      setBusy(false);
    }
  }
  const s = data?.snapshot,
    m = s?.evidence.metrics;
  const stale = !s || checkedAt - new Date(s.bucket).getTime() > 600000;
  return (
    <Shell
      onAuth={() => {
        setData(null);
        setExplanation(null);
        void load();
      }}
    >
      <Link
        href="/"
        className="mb-7 inline-flex items-center gap-2 text-xs text-slate-500"
      >
        <ArrowLeft size={14} />
        All integrations
      </Link>
      {error && (
        <div
          role="alert"
          className="mb-5 rounded-lg bg-rose-50 p-4 text-sm text-rose-800"
        >
          {error}
        </div>
      )}
      {!data && !error && (
        <p className="muted">Loading integration evidence…</p>
      )}
      {data && (
        <>
          <div className="mb-7 flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="eyebrow mb-2">{data.integration.category}</p>
              <h1 className="text-3xl font-semibold">
                {data.integration.name}
              </h1>
              <p className="muted mt-2">
                Owner: {data.integration.owner} · Evaluated {time(s?.bucket)}
              </p>
            </div>
            <StatusBadge
              status={stale ? "unknown" : (s?.status ?? "unknown")}
            />
          </div>
          {stale && (
            <p className="mb-5 rounded-lg bg-amber-50 p-4 text-sm text-amber-800">
              Evaluation is overdue. The evidence below is historical; current
              health is unknown.
            </p>
          )}
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {[
              {
                label: "Error rate / 15m",
                value: percent(m?.error_rate),
                hint: `${m?.error_count ?? 0} failed requests`,
              },
              {
                label: "P95 latency / 15m",
                value: ms(m?.p95_ms),
                hint: `Target ${data.integration.latency_target_ms} ms`,
              },
              {
                label: "Request volume / 15m",
                value: m?.request_count.toLocaleString() ?? "—",
                hint: "20 requests for confident classification",
              },
              {
                label: "Error rate / 24h",
                value: percent(m?.daily_error_rate),
                hint: `${m?.daily_request_count.toLocaleString() ?? 0} requests · context only`,
              },
            ].map((c) => (
              <div key={c.label} className="card p-5">
                <p className="text-xs text-slate-500">{c.label}</p>
                <p className="my-4 text-2xl font-semibold">{c.value}</p>
                <p className="text-xs text-slate-400">{c.hint}</p>
              </div>
            ))}
          </div>
          <div className="mb-6 grid gap-5 xl:grid-cols-2">
            <section className="card p-6">
              <p className="eyebrow">Decision evidence</p>
              <h2 className="my-3 text-lg font-semibold">Why this status?</h2>
              {s?.evidence.reasons.map((r) => (
                <p key={r} className="mb-3 text-sm leading-6">
                  {r}
                </p>
              ))}
              <div className="mt-5 border-t pt-4 text-xs leading-6 text-slate-500">
                Error warning ≥ 1% · Critical ≥ 5%
                <br />
                Latency warning ≥ 1.5× target · Critical ≥ 3×
                <br />
                Freshness expected within {data.integration.max_gap_minutes} min
                · Last event {time(m?.last_request_at)}
                <br />
                Worst signal wins · Severity score {s?.score ?? "Unknown"}
                <br />
                Policy: {s?.evidence.policy_version ?? "—"}
                <br />
                <span className="break-all">Snapshot: {s?.id ?? "—"}</span>
              </div>
            </section>
            <section className="card p-6">
              <div className="flex flex-wrap justify-between gap-3">
                <div>
                  <p className="eyebrow">Operator assistance</p>
                  <h2 className="my-3 text-lg font-semibold">
                    Incident explanation
                  </h2>
                </div>
                <button
                  className="button self-start"
                  onClick={() => void explain()}
                  disabled={busy || !s}
                >
                  {busy ? (
                    <RefreshCw size={14} className="animate-spin" />
                  ) : (
                    <Sparkles size={14} />
                  )}
                  Explain
                </button>
              </div>
              <p className="muted">
                Grounded in this snapshot. Assistance never changes the health
                decision.
              </p>
              {explanation && (
                <div className="mt-4 rounded-lg bg-slate-50 p-4">
                  <p className="text-sm leading-6">{explanation.explanation}</p>
                  <p className="mt-3 text-xs text-slate-500">
                    {explanation.source.startsWith("openai")
                      ? "AI-generated assistance · Verify hypotheses"
                      : "Deterministic fallback · No AI required"}
                  </p>
                  <p className="mt-2 break-all font-mono text-[10px] text-slate-400">
                    Evidence SHA-256: {explanation.evidence_digest}
                  </p>
                </div>
              )}
              <div className="mt-6 border-t pt-4">
                <p className="eyebrow mb-3">Categorized failures / 15m</p>
                {Object.entries(m?.error_categories ?? {}).map(([k, v]) => (
                  <div key={k} className="flex justify-between py-1 text-sm">
                    <span className="capitalize">{k.replaceAll("_", " ")}</span>
                    <span>{v}</span>
                  </div>
                ))}
                {Object.keys(m?.error_categories ?? {}).length === 0 && (
                  <p className="muted">No failures in this window.</p>
                )}
              </div>
            </section>
          </div>
          <section className="card mb-6 p-6">
            <div className="mb-5 flex justify-between">
              <h2 className="font-semibold">Health history</h2>
              <span className="text-xs text-slate-400">
                Last 24 hours · {data.history.length} evaluations
              </span>
            </div>
            <History snapshots={data.history} />
            <div className="mt-3 flex flex-wrap justify-between gap-2 text-[11px] text-slate-400">
              <span>{time(data.history.at(-1)?.bucket)}</span>
              <span>
                Green: healthy · Amber: degraded · Red: unhealthy · Gray:
                unknown
              </span>
              <span>{time(data.history[0]?.bucket)}</span>
            </div>
          </section>
          <section className="card mb-6 p-6">
            <h2 className="mb-4 font-semibold">Incident timeline</h2>
            {data.incidents.map((i) => (
              <div
                key={i.id}
                className="flex flex-wrap justify-between gap-2 border-t py-3 text-sm"
              >
                <div>
                  {time(i.opened_at)} <span className="text-slate-400">→</span>{" "}
                  {i.resolved_at ? time(i.resolved_at) : "Still open"}
                </div>
                <span className="text-xs text-slate-500">
                  {i.resolved_at
                    ? "Resolved after two healthy evaluations"
                    : `${i.recovery_streak}/2 recovery checks`}
                </span>
              </div>
            ))}
            {data.incidents.length === 0 && (
              <p className="muted">No incidents recorded.</p>
            )}
          </section>
          <section className="card overflow-hidden">
            <div className="border-b p-5">
              <h2 className="font-semibold">Recent request logs</h2>
              <p className="mt-1 text-xs text-slate-400">
                Latest 50 · Sanitized metadata only · Newest first
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[600px] text-left text-xs">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    {[
                      "Occurred at",
                      "HTTP status",
                      "Duration",
                      "Error category",
                      "Event ID",
                    ].map((h) => (
                      <th key={h} className="p-4 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.logs.map((l) => (
                    <tr key={l.event_id}>
                      <td className="p-4">{time(l.occurred_at)}</td>
                      <td
                        className={
                          l.status_code >= 400 || l.timed_out
                            ? "p-4 font-semibold text-rose-600"
                            : "p-4 text-emerald-700"
                        }
                      >
                        {l.timed_out ? "Timeout" : l.status_code}
                      </td>
                      <td className="p-4 font-mono">{ms(l.latency_ms)}</td>
                      <td className="p-4">{l.error_category}</td>
                      <td className="max-w-48 truncate p-4 font-mono text-slate-400">
                        {l.event_id}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.logs.length && (
              <p className="p-5 muted">No telemetry received.</p>
            )}
          </section>
        </>
      )}
    </Shell>
  );
}

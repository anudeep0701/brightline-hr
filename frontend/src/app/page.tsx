"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  RefreshCw,
  Search,
  ArrowUpRight,
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
} from "lucide-react";
import { Shell } from "@/components/shell";
import { StatusBadge } from "@/components/status";
import { api, percent, ms, time } from "@/lib/api";
import type { Dashboard, Status } from "@/types";
export default function Page() {
  const [checkedAt, setCheckedAt] = useState(Date.now());
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const load = useCallback(async () => {
    setCheckedAt(Date.now());
    try {
      setData(await api<Dashboard>("/api/v1/dashboard"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to connect");
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 60000);
    return () => clearInterval(timer);
  }, [load]);
  async function refresh() {
    setBusy(true);
    try {
      await api("/api/v1/refresh", "POST");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setBusy(false);
    }
  }
  const items = (data?.integrations ?? []).map((x) => ({
    ...x,
    stale:
      x.stale ||
      !x.snapshot ||
      checkedAt - new Date(x.snapshot.bucket).getTime() > 600000,
  }));
  const status = (x: (typeof items)[number]): Status =>
    x.stale ? "unknown" : (x.snapshot?.status ?? "unknown");
  const counts = { healthy: 0, degraded: 0, unhealthy: 0, unknown: 0 };
  items.forEach((x) => counts[status(x)]++);
  const visible = items
    .filter(
      (x) =>
        (filter === "all" || status(x) === filter) &&
        `${x.integration.name} ${x.integration.category}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort(
      (a, b) =>
        ["unhealthy", "degraded", "unknown", "healthy"].indexOf(status(a)) -
        ["unhealthy", "degraded", "unknown", "healthy"].indexOf(status(b)),
    );
  return (
    <Shell
      onAuth={() => {
        setData(null);
        void load();
      }}
    >
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow mb-3">Operational overview</p>
          <h1 className="text-3xl font-semibold tracking-tight">
            Integration health
          </h1>
          <p className="muted mt-2">
            Start your day with a clear view of every connection.
          </p>
        </div>
        <button
          className="button"
          disabled={busy}
          onClick={() => void refresh()}
        >
          <RefreshCw size={15} className={busy ? "animate-spin" : ""} />
          {busy ? "Evaluating…" : "Evaluate now"}
        </button>
      </div>
      {data?.mode === "demo" && (
        <div className="mb-6 rounded-lg border border-teal/20 bg-teal/5 px-4 py-3 text-xs text-teal">
          Synthetic demo workspace · No customer data · Evaluation uses the last
          completed 5-minute boundary
        </div>
      )}
      {error && (
        <div
          role="alert"
          className="mb-6 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
        >
          {error}. Start the backend or connect a workspace token using
          Workspace access.
          {data &&
            " Showing the last fetched results; freshness may have changed."}
        </div>
      )}
      {!data && !error && (
        <div className="card mb-6 p-8 muted" aria-live="polite">
          Loading integration telemetry…
        </div>
      )}
      <div className="mb-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          {
            label: "Healthy connections",
            value: counts.healthy,
            icon: CheckCircle2,
            color: "text-emerald-600",
            hint: "Within error and latency policy",
          },
          {
            label: "Needs attention",
            value: counts.unhealthy + counts.degraded,
            icon: AlertTriangle,
            color: "text-amber-600",
            hint: `${counts.unhealthy} unhealthy · ${counts.degraded} degraded`,
          },
          {
            label: "Open incidents",
            value: data?.incidents.length ?? 0,
            icon: Activity,
            color: "text-rose-600",
            hint: "Awaiting sustained recovery",
          },
          {
            label: "Unknown health",
            value: counts.unknown,
            icon: Clock3,
            color: "text-slate-500",
            hint: "Sparse or stale telemetry",
          },
        ].map((c) => (
          <div className="card p-5" key={c.label}>
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-slate-500">{c.label}</p>
              <c.icon size={17} className={c.color} />
            </div>
            <div className="mb-2 mt-5 text-3xl font-semibold">
              {data ? c.value : "—"}
            </div>
            <p className="text-xs text-slate-400">{c.hint}</p>
          </div>
        ))}
      </div>
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 p-5">
          <div className="flex items-center gap-3">
            <h2 className="font-semibold">Connected systems</h2>
            <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">
              {items.length}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3">
              <Search size={14} className="text-slate-400" />
              <input
                aria-label="Search integrations"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search integrations"
                className="w-40 bg-transparent py-2 text-xs outline-none"
              />
            </label>
            <select
              aria-label="Filter health"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-3 text-xs"
            >
              <option value="all">All statuses</option>
              {Object.keys(counts).map((s) => (
                <option key={s} value={s}>
                  {s[0].toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] text-left text-sm">
            <thead className="bg-slate-50/80 text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                {[
                  "Integration",
                  "Health",
                  "Error rate",
                  "P95 latency",
                  "Requests / 15m",
                  "Last evaluated",
                  "",
                ].map((h, i) => (
                  <th key={i} className="px-5 py-3 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visible.map(({ integration: i, snapshot: s, stale }) => (
                <tr key={i.id} className="group hover:bg-slate-50">
                  <td className="px-5 py-5">
                    <Link
                      href={`/integrations/${i.id}`}
                      className="flex items-center gap-3"
                    >
                      <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm font-bold">
                        {i.name.slice(0, 2)}
                      </span>
                      <div>
                        <p className="font-semibold group-hover:text-teal">
                          {i.name}
                        </p>
                        <p className="mt-1 text-xs text-slate-400">
                          {i.category}
                        </p>
                      </div>
                    </Link>
                  </td>
                  <td className="px-5">
                    <StatusBadge
                      status={stale ? "unknown" : (s?.status ?? "unknown")}
                    />
                    {stale && (
                      <p className="mt-1 text-[10px] text-slate-400">
                        Evaluation overdue
                      </p>
                    )}
                  </td>
                  <td className="px-5 font-mono text-xs">
                    {percent(s?.evidence.metrics.error_rate)}
                  </td>
                  <td className="px-5 font-mono text-xs">
                    {ms(s?.evidence.metrics.p95_ms)}
                  </td>
                  <td className="px-5 text-slate-600">
                    {s?.evidence.metrics.request_count.toLocaleString() ?? "—"}
                  </td>
                  <td className="px-5 text-xs text-slate-500">
                    {time(s?.bucket)}
                  </td>
                  <td className="px-4">
                    <Link
                      aria-label={`View ${i.name}`}
                      href={`/integrations/${i.id}`}
                    >
                      <ArrowUpRight size={17} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && visible.length === 0 && (
          <p className="p-10 text-center muted">
            No integrations match this view.
          </p>
        )}
        <div className="flex flex-wrap justify-between gap-2 border-t border-slate-100 px-5 py-3 text-[11px] text-slate-400">
          <span>
            15-minute health window · P95 includes failures and timeouts
          </span>
          <span>
            Health evaluation every 5 min · View refreshes every 60 sec
          </span>
        </div>
      </div>
      <div className="mt-7 grid gap-5 xl:grid-cols-[1.4fr_1fr]">
        <section className="card p-6">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="font-semibold">Attention queue</h2>
            <span className="eyebrow">Active incidents</span>
          </div>
          {data?.incidents.length === 0 && (
            <p className="muted">
              No open incidents. Healthy connections remain under observation.
            </p>
          )}
          {data?.incidents.slice(0, 5).map((i) => (
            <Link
              key={i.id}
              href={`/integrations/${i.integration_id}`}
              className="flex items-center justify-between gap-3 border-t border-slate-100 py-4"
            >
              <div>
                <p className="text-sm font-medium">
                  {items.find((x) => x.integration.id === i.integration_id)
                    ?.integration.name ?? i.integration_id}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Opened {time(i.opened_at)} · {i.recovery_streak}/2 recovery
                  checks
                </p>
              </div>
              <ArrowRight size={16} />
            </Link>
          ))}
        </section>
        <section className="rounded-xl border border-ink/10 bg-ink p-6 text-white">
          <p className="eyebrow !text-emerald-300">Explainable by design</p>
          <h2 className="mb-3 mt-3 text-xl font-medium">
            Every signal has a reason.
          </h2>
          <p className="text-sm leading-6 text-slate-300">
            Errors take priority. Latency can escalate severity. Missing data
            stays unknown. Open any integration to inspect the exact evidence
            and thresholds behind its status.
          </p>
          <p className="mt-5 text-xs text-emerald-300">
            Deterministic policy · Versioned evidence · Optional AI assistance
          </p>
        </section>
      </div>
    </Shell>
  );
}

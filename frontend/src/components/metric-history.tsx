import { time, percent, ms } from "@/lib/api";
import type { Snapshot } from "@/types";

export function MetricHistory({ history }: { history: Snapshot[] }) {
  const ordered = [...history].sort((a, b) => a.bucket.localeCompare(b.bucket));
  const series = [
    {
      label: "Error rate",
      key: "error_rate" as const,
      format: percent,
      color: "#be123c",
    },
    {
      label: "P95 latency",
      key: "p95_ms" as const,
      format: ms,
      color: "#087f72",
    },
    {
      label: "Request volume",
      key: "request_count" as const,
      format: (n: number | null | undefined) =>
        n == null ? "—" : n.toLocaleString(),
      color: "#475569",
    },
  ];
  return (
    <section className="card mb-6 p-5 md:p-6">
      <div className="mb-5 flex flex-wrap justify-between gap-2">
        <h2 className="font-semibold">Metric history</h2>
        <span className="text-xs text-slate-500">
          Rolling evaluation windows · {history.length} observations
        </span>
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        {series.map(({ label, key, format, color }) => {
          const values = ordered.map((s) => s.evidence.metrics[key]);
          const valid = values.filter((v): v is number => v != null);
          const max = Math.max(...valid, key === "error_rate" ? 0.01 : 1);
          const minTime = ordered.length
            ? new Date(ordered[0].bucket).getTime()
            : 0;
          const duration = ordered.length
            ? Math.max(1, new Date(ordered.at(-1)!.bucket).getTime() - minTime)
            : 1;
          const x = (i: number) =>
            8 +
            ((new Date(ordered[i].bucket).getTime() - minTime) / duration) *
              264;
          const y = (v: number) => 88 - (v / max) * 72;
          const segments: string[] = [];
          let segment: string[] = [];
          values.forEach((v, i) => {
            if (v == null) {
              if (segment.length) segments.push(segment.join(" "));
              segment = [];
            } else segment.push(`${x(i)},${y(v)}`);
          });
          if (segment.length) segments.push(segment.join(" "));
          return (
            <div key={key}>
              <div className="flex justify-between text-xs text-slate-500">
                <h3 className="font-medium text-ink">{label}</h3>
                <span>Scale 0–{format(max)}</span>
              </div>
              {valid.length ? (
                <>
                  <p className="mt-2 text-xl font-semibold tabular-nums">
                    {format(values.at(-1))}
                  </p>
                  <svg
                    viewBox="0 0 280 104"
                    role="img"
                    aria-label={`${label} history. Latest ${format(values.at(-1))}, range ${format(Math.min(...valid))} to ${format(Math.max(...valid))}. Exact values in the table below.`}
                    className="mt-2 h-28 w-full"
                  >
                    <title>{`${label} over time; gaps mean no measurement`}</title>
                    <path
                      d="M8 88H272 M8 52H272 M8 16H272"
                      stroke="#e2e8f0"
                      strokeWidth="1"
                    />
                    {segments.map((points, i) => (
                      <polyline
                        key={i}
                        points={points}
                        fill="none"
                        stroke={color}
                        strokeWidth="2"
                      />
                    ))}
                    {valid.length <= 60 &&
                      values.map((v, i) =>
                        v == null ? null : (
                          <circle
                            key={i}
                            cx={x(i)}
                            cy={y(v)}
                            r="2"
                            fill={color}
                          >
                            <title>
                              {`${time(ordered[i].bucket)}: ${format(v)}`}
                            </title>
                          </circle>
                        ),
                      )}
                  </svg>
                </>
              ) : (
                <p className="flex h-40 items-center text-sm text-slate-500">
                  No measurements in this history.
                </p>
              )}
              <div className="flex justify-between text-[10px] text-slate-500">
                <span>{time(ordered[0]?.bucket)}</span>
                <span>{time(ordered.at(-1)?.bucket)}</span>
              </div>
            </div>
          );
        })}
      </div>
      <details className="mt-5 border-t border-slate-100 pt-4">
        <summary className="cursor-pointer text-xs font-medium text-teal">
          Exact window measurements
        </summary>
        <div className="mt-3 max-h-72 overflow-auto">
          <table className="w-full min-w-[540px] text-left text-xs">
            <caption className="sr-only">
              Exact metric measurements, newest first
            </caption>
            <thead className="sticky top-0 bg-slate-50">
              <tr>
                {["Window ending", "Error rate", "P95 latency", "Requests"].map(
                  (h) => (
                    <th scope="col" className="p-3 font-medium" key={h}>
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {[...ordered].reverse().map((s) => (
                <tr key={s.id} className="border-t border-slate-100">
                  <td className="p-3">{time(s.bucket)}</td>
                  <td className="p-3">
                    {percent(s.evidence.metrics.error_rate)}
                  </td>
                  <td className="p-3">{ms(s.evidence.metrics.p95_ms)}</td>
                  <td className="p-3">
                    {s.evidence.metrics.request_count.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

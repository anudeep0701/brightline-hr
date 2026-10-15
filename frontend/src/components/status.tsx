import type { Status } from "@/types";
const styles: Record<Status, string> = {
  healthy: "bg-emerald-50 text-emerald-800 border-emerald-200",
  degraded: "bg-amber-50 text-amber-800 border-amber-200",
  unhealthy: "bg-rose-50 text-rose-800 border-rose-200",
  unknown: "bg-slate-100 text-slate-600 border-slate-200",
};
export function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${styles[status]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}
export function History({
  snapshots,
}: {
  snapshots: { status: Status; bucket: string }[];
}) {
  const colors: Record<Status, string> = {
    healthy: "bg-emerald-400",
    degraded: "bg-amber-400",
    unhealthy: "bg-rose-400",
    unknown: "bg-slate-200",
  };
  return (
    <div
      className="flex h-12 items-end gap-1"
      aria-label="Health history, oldest to newest"
    >
      {[...snapshots].reverse().map((s) => (
        <div
          key={s.bucket}
          title={`${new Date(s.bucket).toLocaleString()}: ${s.status}`}
          className={`h-full min-w-1 flex-1 rounded-sm ${colors[s.status]}`}
        />
      ))}
      {snapshots.length === 0 && (
        <span className="text-sm text-slate-500">No evaluations yet</span>
      )}
    </div>
  );
}

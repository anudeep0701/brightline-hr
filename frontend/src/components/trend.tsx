import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { direction } from "@/lib/health-view";
import type { Snapshot } from "@/types";
export function Trend({
  current,
  previous,
}: {
  current: Snapshot | null;
  previous?: Snapshot | null;
}) {
  const trend = direction(current, previous);
  const Icon =
    trend.kind === "up"
      ? ArrowUpRight
      : trend.kind === "down"
        ? ArrowDownRight
        : Minus;
  return (
    <span
      title={trend.title}
      className={`inline-flex items-start gap-1 text-xs ${trend.kind === "up" ? "text-rose-700" : trend.kind === "down" ? "text-teal" : "text-slate-500"}`}
    >
      <Icon size={14} className="shrink-0" />
      {trend.text}
    </span>
  );
}

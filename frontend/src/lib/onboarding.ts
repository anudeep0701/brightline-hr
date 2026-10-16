export const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;
export function uploadFormat(name: string, size: number) {
  if (size > MAX_UPLOAD_BYTES) throw new Error("Files must be at most 2 MiB.");
  const suffix = name.split(".").pop()?.toLowerCase();
  if (!suffix || !["csv", "json", "ndjson", "jsonl"].includes(suffix))
    throw new Error("Choose a CSV, JSON, NDJSON or JSONL file.");
  return suffix;
}
export function sourceName(source: string) {
  return (
    {
      LIVE_API: "Live API",
      FILE_IMPORT: "File Import",
      DEMO: "Demo",
      UNKNOWN: "Unknown source",
    }[source] ?? "Unknown source"
  );
}
export function ingestionStatus(freshness: {
  status: string;
  evaluation_overdue: boolean;
}) {
  if (freshness.status === "NO_TELEMETRY") return "No telemetry received";
  if (freshness.status === "STALE_TELEMETRY") return "Telemetry is stale";
  if (freshness.evaluation_overdue) return "Evaluation overdue";
  return "Recent telemetry observed";
}

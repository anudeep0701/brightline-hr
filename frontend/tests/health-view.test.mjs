import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Exercise the production TypeScript helpers using the existing compiler; no browser/test dependency.
const source = await readFile(
  new URL("../src/lib/health-view.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022 },
});
const { direction, isStale, needsAttention, transitions, comparePriority } =
  await import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
  );
const snapshot = (
  status = "healthy",
  error_rate = 0.01,
  p95_ms = 100,
  bucket = "2026-10-15T12:00:00Z",
) => ({
  id: bucket,
  status,
  bucket,
  evidence: { metrics: { error_rate, p95_ms } },
});
const row = (s, stale = false) => ({
  snapshot: s,
  stale,
  integration: { name: "Payroll", refresh_minutes: 5 },
});

test("stale evidence requires attention without replacing the persisted healthy state", () => {
  const item = row(snapshot());
  assert.equal(isStale(item, Date.parse("2026-10-15T12:11:00Z")), true);
  assert.equal(needsAttention(item, Date.parse("2026-10-15T12:11:00Z")), true);
  assert.equal(item.snapshot.status, "healthy");
  assert.equal(isStale(item, Date.parse("2026-10-15T12:10:00Z")), false);
});
test("missing decisions need attention and have no invented trend", () => {
  assert.equal(needsAttention(row(null), Date.now()), true);
  assert.equal(direction(null, null).kind, "none");
  assert.equal(
    direction(snapshot("unknown", null, null), snapshot("unknown", null, null))
      .kind,
    "none",
  );
});
test("error changes use percentage points, and latency changes use relative percent", () => {
  assert.equal(
    direction(snapshot("healthy", 0.02), snapshot("healthy", 0.01)).text,
    "Errors +1.0 pp",
  );
  assert.equal(
    direction(snapshot("healthy", 0, 150), snapshot("healthy", 0, 100)).text,
    "P95 +50%",
  );
  assert.equal(
    direction(snapshot("healthy", 0, 80), snapshot("healthy", 0, 100)).kind,
    "down",
  );
});
test("a recorded health transition takes precedence over a single improving metric", () => {
  const change = direction(
    snapshot("unhealthy", 0.01),
    snapshot("degraded", 0.03),
  );
  assert.equal(change.text, "degraded → unhealthy");
  assert.equal(change.kind, "up");
});
test("transition history sorts by time and emits only actual state changes", () => {
  const first = snapshot("healthy", 0, 100, "2026-10-15T12:00:00Z");
  const middle = snapshot("degraded", 0.03, 100, "2026-10-15T12:05:00Z");
  const last = snapshot("degraded", 0.03, 100, "2026-10-15T12:10:00Z");
  const result = transitions([last, first, middle]);
  assert.equal(result.length, 1);
  assert.equal(result[0].previous, "healthy");
  assert.equal(result[0].snapshot.id, middle.id);
});
test("attention ordering puts confirmed failures before degradation and evidence gaps", () => {
  assert.deepEqual(
    [
      row(snapshot("healthy")),
      row(snapshot("unknown")),
      row(snapshot("degraded")),
      row(snapshot("unhealthy")),
    ]
      .sort(comparePriority)
      .map((x) => x.snapshot.status),
    ["unhealthy", "degraded", "unknown", "healthy"],
  );
});

test("telemetry gaps need attention even when the latest evaluation is recent and healthy", async () => {
  const { investigationGuidance } = await import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
  );
  const item = {
    ...row(snapshot()),
    freshness: { current_evidence_status: "UNKNOWN" },
  };
  assert.equal(needsAttention(item, Date.parse("2026-10-15T12:01:00Z")), true);
  assert.match(
    investigationGuidance(item, Date.parse("2026-10-15T12:01:00Z")),
    /telemetry/,
  );
});

test("investigation guidance uses provider-neutral observed error and latency evidence", async () => {
  const { investigationGuidance } = await import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
  );
  const item = row(snapshot("unhealthy"));
  item.snapshot.evidence.metrics.top_error_categories = [
    { category: "auth", count: 10 },
  ];
  assert.match(
    investigationGuidance(item, Date.parse("2026-10-15T12:01:00Z")),
    /credential/,
  );
  item.snapshot.evidence.metrics.top_error_categories = [];
  item.snapshot.evidence.signal_reason_codes = ["LATENCY_TARGET_CRITICAL"];
  assert.match(
    investigationGuidance(item, Date.parse("2026-10-15T12:01:00Z")),
    /response times/,
  );
});

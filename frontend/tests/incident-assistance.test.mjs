import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022 },
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
  );
}
const { currentEvidenceState, advisoryConfidence } = await load(
  "../src/lib/health-view.ts",
);
const { api, setTenant, setToken } = await load("../src/lib/api.ts");

const now = Date.parse("2026-10-16T12:00:00Z");
const row = (bucket, freshness = undefined) => ({
  snapshot: { status: "healthy", bucket },
  integration: { refresh_minutes: 5 },
  stale: false,
  freshness,
});

test("stale/no telemetry is UNKNOWN current evidence without rewriting historical HEALTHY", () => {
  const stale = row("2026-10-16T11:30:00Z");
  assert.equal(currentEvidenceState(stale, now), "unknown");
  assert.equal(stale.snapshot.status, "healthy");
  const absent = row("2026-10-16T12:00:00Z", {
    current_evidence_status: "UNKNOWN",
  });
  assert.equal(currentEvidenceState(absent, now), "unknown");
  assert.equal(
    currentEvidenceState(row("2026-10-16T12:00:00Z"), now),
    "healthy",
  );
});

test("advisory confidence labels are separate from health certainty", () => {
  assert.equal(advisoryConfidence(0.9), "High");
  assert.equal(advisoryConfidence(0.6), "Medium");
  assert.equal(advisoryConfidence(0.2), "Low");
  assert.equal(advisoryConfidence(0), "Low");
});

test("focused investigation sends structured topic with current workspace scope", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(new URL(url).searchParams.get("tenant_id"), "tenant-a");
    assert.equal(options.headers.Authorization, "Bearer local-test-workspace");
    assert.equal(options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(options.body), {
      topic: "recovery",
      incident_id: "resolved-incident",
    });
    return {
      ok: true,
      json: async () => ({
        source: "deterministic",
        report: { summary: "Recorded recovery" },
        audit: { health_state: "HEALTHY", fallback_used: true },
      }),
    };
  };
  try {
    setToken("local-test-workspace");
    setTenant("tenant-a");
    const response = await api(
      "/api/integrations/payroll/investigate",
      "POST",
      undefined,
      { topic: "recovery", incident_id: "resolved-incident" },
    );
    assert.equal(response.audit.health_state, "HEALTHY");
    assert.equal(response.audit.fallback_used, true);
  } finally {
    globalThis.fetch = original;
    setToken("");
  }
});

test("failed assistance exposes safe API message so deterministic evidence can remain visible", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    json: async () => ({
      detail: "Incident not found",
      code: "incident_not_found",
    }),
  });
  try {
    await assert.rejects(
      api("/api/integrations/payroll/investigate", "POST", undefined, {
        topic: "recovery",
        incident_id: "foreign",
      }),
      /Incident not found/,
    );
  } finally {
    globalThis.fetch = original;
  }
});

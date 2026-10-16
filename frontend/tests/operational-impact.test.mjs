import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const source = await readFile(
  new URL("../src/components/operational-impact.tsx", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
});
const exports = {};
new Function("require", "exports", outputText)(
  createRequire(import.meta.url),
  exports,
);
const { OperationalImpact } = exports;
function render(
  mode,
  duration,
  counts = { healthy: 1, degraded: 1, unhealthy: 1, unknown: 1 },
) {
  return renderToStaticMarkup(
    createElement(OperationalImpact, {
      counts,
      dashboard: {
        mode,
        operational_impact: {
          incidents_detected: 3,
          recovered_incidents: 2,
          mean_confirmed_incident_duration_seconds: duration,
        },
      },
    }),
  );
}

test("demo outcomes have a simulated label and disclose the duration denominator", () => {
  const html = render("demo", 600);
  assert.match(html, /Demo \/ simulated operational impact/);
  assert.match(html, /10\.0 min/);
  assert.match(html, /25%/);
  assert.match(html, /resolved in last 24h/);
  assert.match(html, /not customer ROI/);
  assert.match(html, /Tenant-wide/);
});

test("missing observations render unavailable values without fabricated zero duration or health", () => {
  const html = render("production", null, {
    healthy: 0,
    degraded: 0,
    unhealthy: 0,
    unknown: 0,
  });
  assert.match(html, /Observed operational impact/);
  assert.match(html, /—/);
  assert.doesNotMatch(html, /0\.0 min|0%|Demo \/ simulated/);
  assert.match(html, /not verified customer impact/);
});

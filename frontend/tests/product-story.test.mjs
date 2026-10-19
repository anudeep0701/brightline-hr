import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

// Render actual TSX components with React. Only routing/resource transport is replaced.
const require = createRequire(import.meta.url);
const src = path.resolve(import.meta.dirname, "../src");
let resource;
const cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file);
  const source = readFileSync(file, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
  });
  const module = { exports: {} };
  const localRequire = (name) => {
    if (name === "next/link")
      return {
        __esModule: true,
        default: ({ children, ...props }) =>
          React.createElement("a", props, children),
      };
    if (name === "next/navigation") return { usePathname: () => "/" };
    if (name === "@/lib/use-resource") return { useResource: () => resource };
    if (name.startsWith("@/")) {
      const base = path.join(src, name.slice(2));
      return load(existsSync(base + ".tsx") ? base + ".tsx" : base + ".ts");
    }
    return require(name);
  };
  new Function("require", "module", "exports", outputText)(
    localRequire,
    module,
    module.exports,
  );
  cache.set(file, module.exports);
  return module.exports;
}
const { MorningSummary } = load(
  path.join(src, "components/morning-summary.tsx"),
);
const { DemoGuide } = load(path.join(src, "components/demo-guide.tsx"));
const { IncidentAssistant } = load(
  path.join(src, "components/incident-assistant.tsx"),
);
const { LiveApiGuide } = load(path.join(src, "components/live-api-guide.tsx"));
const Dashboard = load(path.join(src, "app/page.tsx")).default;
const DataSources = load(path.join(src, "app/data-sources/page.tsx")).default;
const now = Date.parse("2026-10-16T12:00:00Z");
const row = (status, id = status) => ({
  integration: {
    id,
    name: id,
    category: "payroll",
    owner: "Platform Ops",
    refresh_minutes: 5,
    evaluation_window_minutes: 15,
    min_requests: 20,
  },
  stale: false,
  freshness: {
    current_evidence_status: status.toUpperCase(),
    status: "RECENT_TRAFFIC",
    last_event_at: new Date(now).toISOString(),
  },
  snapshot: {
    id,
    status,
    bucket: new Date(now).toISOString(),
    evaluated_at: new Date(now).toISOString(),
    evidence_sufficient: status !== "unknown",
    reason_text: "Observed request evidence",
    evidence: {
      metrics: {
        request_count: 100,
        error_rate: status === "healthy" ? 0 : 0.2,
        p95_ms: 500,
      },
    },
  },
  previous_snapshot: null,
});
const workspace = {
  mode: "demo",
  tenant_id: "brightline",
  tenant_name: "Brightline HR",
  role: "operator",
  can_switch_tenants: true,
  tenants: [{ id: "brightline", name: "Brightline HR" }],
};
const render = (component, props = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
function dashboard(items) {
  resource = {
    data: {
      workspace,
      dashboard: {
        mode: "demo",
        integrations: items,
        incidents: [],
        operational_impact: {
          incidents_detected: 2,
          recovered_incidents: 1,
          mean_confirmed_incident_duration_seconds: 900,
          stale_or_absent_integrations: 0,
        },
      },
    },
    checkedAt: now,
    loadedAt: now,
    error: "",
    reload() {},
  };
  return render(Dashboard);
}

test("morning summary distinguishes populated healthy, mixed and empty fleets", () => {
  assert.match(
    render(MorningSummary, { items: [row("healthy")], now }),
    /All monitored integrations are operating within policy/,
  );
  const html = render(MorningSummary, {
    items: [row("unhealthy"), row("degraded"), row("healthy")],
    now,
  });
  assert.match(html, /2 integrations need attention/);
  assert.match(html, /Start with unhealthy/);
  assert.match(
    render(MorningSummary, { items: [], now }),
    /No telemetry has been connected yet/,
  );
});
test("populated dashboard leads with attention, then measurable outcomes and secondary fleet counts", () => {
  const html = dashboard([row("healthy"), row("degraded"), row("unhealthy")]);
  assert.ok(html.indexOf("3 integrations need") === -1);
  assert.match(html, /2 integrations need attention/);
  assert.ok(
    html.indexOf('id="attention-title"') < html.indexOf("Fleet at a glance"),
  );
  assert.match(html, /Investigate \/ AI brief/);
  assert.match(html, /Scope: Brightline HR/);
  assert.match(html, /Demo \/ simulated operational impact/);
  assert.match(html, /15.0 min/);
});
test("stale healthy records cannot produce confident healthy messaging or improving claims", () => {
  const item = row("healthy");
  item.stale = true;
  item.previous_snapshot = row("unhealthy").snapshot;
  const html = render(MorningSummary, { items: [item], now });
  assert.match(html, /1 integration needs attention/);
  assert.match(html, /1 evidence gaps/);
  assert.match(html, /Direction awaiting comparable recent windows/);
  assert.doesNotMatch(
    html,
    /All monitored integrations are operating within policy/,
  );
});
test("first-use dashboard supplies onboarding and explicit demo loading, without fake counters", () => {
  const html = dashboard([]);
  assert.match(html, /Upload logs/);
  assert.match(html, /Connect Live API/);
  assert.match(html, /Load demo scenario/);
  assert.doesNotMatch(html, /Fleet at a glance/);
  assert.doesNotMatch(html, /All monitored integrations are operating/);
});
test("UNKNOWN context counts the engine's insufficient-request decisions", () => {
  const item = row("unknown");
  item.snapshot.reason_code = "INSUFFICIENT_REQUESTS";
  item.snapshot.evidence.metrics.request_count = 3;
  const html = dashboard([item]);
  assert.match(html, /1 low-volume/);
  assert.match(html, /1 integration needs attention/);
  assert.doesNotMatch(
    html,
    /All monitored integrations are operating within policy/,
  );
});
test("scenario selector exposes five journeys and links only to existing integration evidence", () => {
  const html = render(DemoGuide, {
    items: [row("unhealthy", "slack-notifications")],
  });
  for (const name of [
    "Normal operations",
    "Authentication outage",
    "Latency degradation",
    "Provider outage",
    "Recovery",
  ])
    assert.match(html, new RegExp(name));
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /href="\/integrations\/slack-notifications"/);
  assert.doesNotMatch(render(DemoGuide), /href="\/integrations\//);
  assert.match(html, /does not generate traffic/);
});
test("AI brief and focused investigation are visible before generation with a deterministic fallback", () => {
  const html = render(IncidentAssistant, {
    detail: {
      integration: row("unhealthy").integration,
      snapshot: row("unhealthy").snapshot,
      enrichment: null,
    },
    operator: true,
  });
  assert.match(html, /AI incident brief/);
  assert.match(html, /Advisory analysis from observed telemetry/);
  assert.match(html, /Deterministic explanation/);
  assert.match(html, /Investigate with AI/);
  assert.match(html, /no actions are executed/);
  assert.match(html, /Observed request evidence/);
});
test("AI generated report presents grounding, advisory confidence and suggested checks", () => {
  const html = render(IncidentAssistant, {
    detail: {
      integration: row("unhealthy").integration,
      snapshot: row("unhealthy").snapshot,
      enrichment: {
        source: "openai:test",
        audit: {
          generated_at: new Date(now).toISOString(),
          evidence_at: new Date(now).toISOString(),
          tenant_id: "brightline",
          integration_id: "payroll",
          model: "test",
          health_state: "UNHEALTHY",
        },
        report: {
          summary: "Known authentication errors",
          likely_issue_category: "authentication",
          what_changed: "Errors increased in the observed window",
          confidence: 0.8,
          suggested_checks: ["Review credential expiry"],
        },
      },
    },
    operator: true,
  });
  for (const text of [
    "AI insight · Advisory",
    "Known authentication errors",
    "High advisory confidence",
    "Review credential expiry",
    "What changed?",
  ])
    assert.ok(html.includes(text));
});
test("onboarding exposes accessible file selection and validation before import", () => {
  resource = {
    data: { workspace, sources: { items: [] } },
    error: "",
    reload() {},
  };
  const html = render(DataSources);
  assert.match(html, /Connect integration telemetry/);
  assert.match(html, /aria-label="Request-log file"/);
  assert.match(html, /Select log file or drop it here/);
  assert.match(html, /Validate file/);
  assert.match(html, /No records are saved until you confirm/);
  assert.doesNotMatch(html, /Confirm import of/);
});
test("live setup exposes scoped contract, copyable placeholders and a verification step", () => {
  const html = render(LiveApiGuide);
  for (const text of [
    "POST /api/ingest",
    "Ask an administrator",
    "Verify connection",
    "Copy sample request",
    "request_id",
    "latency_ms",
    "$INGESTION_API_KEY",
  ])
    assert.ok(html.includes(text));
  assert.doesNotMatch(html, /scripts\/ingestion_keys/);
});
test("loading and authentication errors offer useful feedback without showing empty healthy counts", () => {
  resource = { data: null, error: "", fetching: true, reload() {} };
  assert.match(render(Dashboard), /Loading integration telemetry/);
  resource.error = "Bearer token required";
  const html = render(Dashboard);
  assert.match(html, /Workspace access/);
  assert.match(html, /Try again/);
  assert.doesNotMatch(html, /All monitored integrations/);
});

test("current-evidence priority places active outages before stale historical failures", () => {
  const { compareCurrentPriority } = load(path.join(src, "lib/health-view.ts"));
  const stale = row("unhealthy", "old-outage");
  stale.stale = true;
  const warning = row("degraded", "warning");
  const outage = row("unhealthy", "outage");
  assert.deepEqual(
    [stale, warning, outage]
      .sort((a, b) => compareCurrentPriority(a, b, now))
      .map((item) => item.integration.id),
    ["outage", "warning", "old-outage"],
  );
});

test("detail tells the deterministic-to-AI story and reports actual recovery evidence", async () => {
  const { renderToPipeableStream } = await import("react-dom/server");
  const { Writable } = await import("node:stream");
  const item = row("healthy", "payroll");
  item.snapshot.evidence.thresholds = {};
  resource = {
    data: {
      workspace,
      detail: {
        ...item,
        history: [item.snapshot],
        logs: [],
        enrichment: null,
        incidents: [
          {
            id: "resolved",
            integration_id: "payroll",
            opened_at: "2026-10-16T11:00:00Z",
            resolved_at: "2026-10-16T11:30:00Z",
            recovery_began_at: "2026-10-16T11:25:00Z",
            recovery_streak: 2,
            healthy_windows_observed: 2,
            healthy_windows_required: 2,
            recovery_condition: "Two consecutive healthy windows",
            opening_reason_text: "Sustained high error rate",
          },
        ],
      },
    },
    checkedAt: now,
    error: "",
    reload() {},
  };
  const DetailPage = load(
    path.join(src, "app/integrations/[id]/page.tsx"),
  ).default;
  const html = await new Promise((resolve, reject) => {
    let result = "";
    const writable = new Writable({
      write(chunk, _encoding, callback) {
        result += chunk.toString();
        callback();
      },
    });
    writable.on("finish", () => resolve(result));
    const stream = renderToPipeableStream(
      React.createElement(DetailPage, {
        params: Promise.resolve({ id: "payroll" }),
      }),
      {
        onAllReady() {
          stream.pipe(writable);
        },
        onError: reject,
      },
    );
  });
  assert.match(html, /Health decision · Deterministic health policy/);
  assert.match(html, /href="#ai-investigation"/);
  assert.match(html, /href="#incident-timeline"/);
  assert.ok(
    html.indexOf('id="health-decision"') <
      html.indexOf('id="ai-investigation"'),
  );
  assert.match(html, /Advisory analysis from observed telemetry/);
  assert.match(html, /Confirmed duration/);
  assert.match(html, /Two consecutive healthy windows/);
  assert.match(html, /Sustained high error rate/);
  assert.match(
    html,
    /Operator investigations and customer-impact times are not recorded/,
  );
});

test("demo workspace is labeled and hides bearer entry while real workspace access remains", () => {
  const { DemoAccessContext } = load(path.join(src, "lib/demo-context.ts"));
  const { Shell } = load(path.join(src, "components/shell.tsx"));
  const component = React.createElement(
    Shell,
    { onAuth: () => {}, tenantName: "Brightline HR" },
    "Evidence",
  );
  const demo = renderToStaticMarkup(
    React.createElement(DemoAccessContext.Provider, { value: true }, component),
  );
  assert.match(demo, /Demo workspace · Synthetic telemetry/);
  assert.doesNotMatch(demo, /Workspace access|Paste workspace token/);
  assert.match(renderToStaticMarkup(component), /Workspace access/);
});

test("demo onboarding explains why shared telemetry cannot be modified", () => {
  const { DemoAccessContext } = load(path.join(src, "lib/demo-context.ts"));
  resource = {
    data: {
      workspace: { ...workspace, can_switch_tenants: false },
      sources: { items: [] },
    },
    reload: () => {},
  };
  const html = renderToStaticMarkup(
    React.createElement(
      DemoAccessContext.Provider,
      { value: true },
      React.createElement(DataSources),
    ),
  );
  assert.match(html, /shared demo cannot accept uploads/);
  assert.match(html, /disabled=""/);
  assert.doesNotMatch(html, /Connect an operator workspace token to validate/);
});

test("production-hosted demo still labels synthetic outcomes and offers scenario exploration", () => {
  const { DemoAccessContext } = load(path.join(src, "lib/demo-context.ts"));
  dashboard([row("unhealthy")]);
  resource.data.workspace = {
    ...workspace,
    mode: "production",
    can_switch_tenants: false,
  };
  resource.data.dashboard.mode = "production";
  const html = renderToStaticMarkup(
    React.createElement(
      DemoAccessContext.Provider,
      { value: true },
      React.createElement(Dashboard),
    ),
  );
  assert.match(html, /Demo \/ simulated operational impact/);
  assert.match(html, /Explore demo scenario/);
  assert.match(html, /Demo outcomes are not customer ROI/);
});

test("opted-in demo upload keeps preview and confirmation with bounded batch guidance", () => {
  const { DemoAccessContext, DemoImportContext } = load(
    path.join(src, "lib/demo-context.ts"),
  );
  resource = {
    data: {
      workspace: { ...workspace, can_switch_tenants: false },
      sources: { items: [] },
    },
    reload() {},
  };
  const html = renderToStaticMarkup(
    React.createElement(
      DemoAccessContext.Provider,
      { value: true },
      React.createElement(
        DemoImportContext.Provider,
        { value: true },
        React.createElement(DataSources),
      ),
    ),
  );
  assert.match(html, /Validate file/);
  assert.match(html, /3,000/);
  assert.match(html, /tagged/);
  assert.doesNotMatch(html, /shared demo cannot accept uploads/);
});

test("demo refresh distinguishes synthetic generation from evaluating existing traffic", () => {
  const { DemoAccessContext } = load(path.join(src, "lib/demo-context.ts"));
  const html = renderToStaticMarkup(
    React.createElement(
      DemoAccessContext.Provider,
      { value: true },
      React.createElement(DemoGuide),
    ),
  );
  assert.match(html, /Refresh demo data/);
  assert.match(html, /Evaluate now/);
  assert.match(html, /evaluates existing traffic/);
  assert.doesNotMatch(html, /scripts\/run_demo/);
});

test("operational text has readable defaults and visible keyboard focus", () => {
  const css = readFileSync(path.join(src, "app/globals.css"), "utf8");
  assert.match(css, /--text-xs: 0\.875rem/);
  assert.match(css, /--text-sm: 1rem/);
  assert.match(css, /focus-visible/);
});

test("AI provenance displays safe provider diagnostics without replacing the health reason", () => {
  const html = render(IncidentAssistant, {
    detail: {
      integration: row("unhealthy").integration,
      snapshot: row("unhealthy").snapshot,
      enrichment: {
        source: "deterministic",
        audit: {
          fallback_used: true,
          failure_category: "AUTHENTICATION_ERROR",
          requested_model: "gpt-6-luna",
          duration_ms: 125,
          health_state: "UNHEALTHY",
        },
        report: {
          summary: "Observed request evidence",
          likely_issue_category: "unknown",
          what_changed: "Known window comparison",
          confidence: 0,
          suggested_checks: ["Inspect existing evidence"],
        },
      },
    },
    operator: true,
  });
  assert.match(html, /AUTHENTICATION ERROR/);
  assert.match(html, /Requested model gpt-6-luna/);
  assert.match(html, /125 ms/);
  assert.match(html, /Observed request evidence/);
  assert.match(html, /Deterministic fallback used/);
});

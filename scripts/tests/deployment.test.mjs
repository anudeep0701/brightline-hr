import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import test from "node:test";

const config = JSON.parse(readFileSync(new URL("../../vercel.json", import.meta.url), "utf8"));
function service(path) {
  return config.rewrites.find((rule) => new RegExp(`^${rule.source}$`).test(path))?.destination.service;
}

test("public backend contracts and scheduler reach FastAPI before the frontend catch-all", () => {
  for (const path of [
    "/api", "/api/ingest", "/api/workspace", "/api/health-summary",
    "/api/integrations", "/api/integrations/payroll/metrics",
    "/api/integrations/payroll/incidents", "/api/integrations/payroll/brief",
    "/api/integrations/payroll/explain", "/api/integrations/payroll/investigate",
    "/api/imports/preview", "/api/imports/commit", "/api/evaluate",
    "/api/cron/refresh", "/api/v1/dashboard", "/healthz", "/readyz",
    "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json",
  ]) assert.equal(service(path), "backend", path);
  for (const path of ["/", "/data-sources", "/integrations/payroll", "/_next/static/chunk.js", "/apiculture"])
    assert.equal(service(path), "frontend", path);
  assert.deepEqual(config.crons, [{ path: "/api/cron/refresh", schedule: "*/5 * * * *" }]);
  assert.ok(config.rewrites.every((rule) => !rule.destination.path), "No prefix stripping or route renaming");
});

test("one root config owns independent framework builds and the existing Python entrypoint", () => {
  assert.equal(config.services.frontend.root, "frontend/");
  assert.equal(config.services.frontend.framework, "nextjs");
  assert.equal(config.services.frontend.installCommand, "npm ci");
  assert.equal(config.services.frontend.buildCommand, "npm run build");
  assert.equal(config.services.backend.root, "backend/");
  assert.equal(config.services.backend.framework, "fastapi");
  assert.equal(config.services.backend.entrypoint, "index:app");
  assert.equal(config.services.backend.installCommand, "pip install -r requirements.txt");
  assert.equal(existsSync(new URL("../../backend/vercel.json", import.meta.url)), false);
  for (const key of ["builds", "framework", "buildCommand", "installCommand", "outputDirectory"])
    assert.equal(Object.hasOwn(config, key), false, key);
});

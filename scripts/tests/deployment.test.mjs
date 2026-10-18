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
  assert.ok(config.rewrites.every((rule) => !rule.destination.path), "No prefix stripping or route renaming");
});

test("Hobby demo uses operator refresh without a scheduled cross-tenant cron", () => {
  assert.equal(Object.hasOwn(config, "crons"), false);
  assert.equal(service("/api/evaluate"), "backend");
  assert.equal(service("/api/cron/refresh"), "backend");
});

test("one root config owns independent framework builds and the existing Python entrypoint", () => {
  assert.equal(config.services.frontend.root, "frontend/");
  assert.equal(config.services.frontend.framework, "nextjs");
  assert.equal(config.services.frontend.installCommand, "npm ci");
  assert.equal(config.services.frontend.buildCommand, "npm run build");
  assert.equal(config.services.backend.root, "backend/");
  assert.equal(config.services.backend.framework, "fastapi");
  assert.equal(config.services.backend.entrypoint, "index:app");
  assert.equal(Object.hasOwn(config.services.backend, "installCommand"), false);
  assert.equal(existsSync(new URL("../../backend/vercel.json", import.meta.url)), false);
  for (const key of ["builds", "framework", "buildCommand", "installCommand", "outputDirectory"])
    assert.equal(Object.hasOwn(config, key), false, key);
});

test("Python deployment installs runtime dependencies without local tooling", () => {
  const runtime = readFileSync(new URL("../../backend/requirements.txt", import.meta.url), "utf8");
  const development = readFileSync(new URL("../../backend/requirements-dev.txt", import.meta.url), "utf8");
  for (const name of ["fastapi", "polars", "SQLAlchemy", "psycopg", "openai", "opentelemetry-api"])
    assert.match(runtime, new RegExp(`^${name}==`, "mi"));
  for (const name of ["pytest", "Faker", "numpy", "Pygments", "ruff", "uvicorn"]){
    assert.doesNotMatch(runtime, new RegExp(`^${name}==`, "mi"));
    assert.match(development, new RegExp(`^${name}==`, "mi"));
  }
  assert.match(development, /^-r requirements\.txt$/m);
  // A dependency-free project manifest would override automatic requirements discovery.
  assert.equal(existsSync(new URL("../../backend/pyproject.toml", import.meta.url)), false);
  assert.equal(existsSync(new URL("../../backend/pytest.ini", import.meta.url)), true);
  assert.equal(existsSync(new URL("../../backend/requirements.in", import.meta.url)), false);
  const excluded = config.services.backend.functions["index.py"].excludeFiles;
  for (const pattern of ["tests/**", "**/__pycache__/**", ".venv/**", "*.db", "requirements-dev.txt"])
    assert.ok(excluded.includes(pattern), pattern);
  assert.ok(!excluded.includes("app/**"));
});

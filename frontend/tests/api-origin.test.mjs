import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function client(mode, base = "") {
  const source = (
    await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8")
  )
    .replaceAll("process.env.NODE_ENV", JSON.stringify(mode))
    .replaceAll("process.env.NEXT_PUBLIC_API_BASE_URL", JSON.stringify(base));
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022 },
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
  );
}

test("production reads and AI writes use the browser origin and retain workspace scope", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const calls = [];
  globalThis.window = {
    location: { origin: "https://preview-brightline.example" },
  };
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ status: "UNHEALTHY" }) };
  };
  try {
    const api = await client("production");
    assert.equal(api.apiBaseUrl, "");
    api.setToken("workspace-test");
    api.setTenant("tenant-a");
    assert.equal((await api.api("/api/v1/dashboard")).status, "unhealthy");
    await api.api("/api/integrations/payroll/investigate", "POST", undefined, {
      topic: "error_driver",
    });
    for (const { url, options } of calls) {
      assert.equal(url.origin, "https://preview-brightline.example");
      assert.equal(url.searchParams.get("tenant_id"), "tenant-a");
      assert.equal(options.headers.Authorization, "Bearer workspace-test");
    }
    assert.equal(
      calls[1].url.pathname,
      "/api/integrations/payroll/investigate",
    );
    assert.equal(calls[1].options.method, "POST");
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
  }
});

test("production file confirmation keeps same-origin authorization and digest headers", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  globalThis.window = { location: { origin: "https://brightline.example" } };
  globalThis.fetch = async (url, options) => {
    assert.equal(url.origin, "https://brightline.example");
    assert.equal(url.pathname, "/api/imports/commit");
    assert.equal(options.headers.Authorization, "Bearer import-workspace");
    assert.equal(options.headers["X-Preview-Digest"], "preview-digest");
    assert.equal(options.headers["X-Confirm-Import"], "true");
    return { ok: true, json: async () => ({ accepted: 1 }) };
  };
  try {
    const api = await client("production");
    api.setToken("import-workspace");
    await api.uploadFile(
      new File(["[]"], "pilot.json"),
      "json",
      new AbortController().signal,
      "preview-digest",
    );
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
  }
});

test("standalone local development retains the port 8000 API default", async () => {
  assert.equal(
    (await client("development")).apiBaseUrl,
    "http://localhost:8000",
  );
});

test("an explicit API override remains available for isolated local validation", async () => {
  assert.equal(
    (await client("production", "http://localhost:8013/")).apiBaseUrl,
    "http://localhost:8013",
  );
});

test("demo entry uses cookie credentials and a CSRF header without a bearer token", async () => {
  const oldFetch = globalThis.fetch;
  const oldWindow = globalThis.window;
  globalThis.window = { location: { origin: "https://brightline.example" } };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, json: async () => ({ demo_mode: true }) };
  };
  try {
    const api = await client("production", "https://demo-entry.example");
    await api.api("/api/demo/session", "POST");
    api.setDemoAccess(true);
    await api.api("/api/evaluate", "POST");
    for (const { url, options } of calls) {
      assert.equal(url.search, "");
      assert.equal(options.credentials, "include");
      assert.equal(options.headers["X-Demo-Request"], "1");
      assert.equal(options.headers.Authorization, undefined);
    }
    api.setDemoAccess(false);
  } finally {
    globalThis.fetch = oldFetch;
    globalThis.window = oldWindow;
  }
});

test("expired demo sessions renew once and retry the workspace request without redirecting", async () => {
  const oldFetch = globalThis.fetch;
  const oldWindow = globalThis.window;
  globalThis.window = { location: { origin: "https://brightline.example" } };
  const calls = [];
  let refreshed = false;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url.pathname === "/api/demo/session") {
      refreshed = true;
      return { ok: true, status: 200 };
    }
    return {
      ok: refreshed,
      status: refreshed ? 200 : 401,
      json: async () => ({ tenant_id: "brightline" }),
    };
  };
  try {
    const api = await client("production", "https://demo-renewal.example");
    api.setDemoAccess(true);
    assert.equal((await api.api("/api/workspace")).tenant_id, "brightline");
    assert.deepEqual(
      calls.map(({ url }) => url.pathname),
      ["/api/workspace", "/api/demo/session", "/api/workspace"],
    );
    assert.ok(
      calls.every(({ options }) => options.headers.Authorization === undefined),
    );
    api.setDemoAccess(false);
  } finally {
    globalThis.fetch = oldFetch;
    globalThis.window = oldWindow;
  }
});

test("failed demo renewal reports a useful error without an authentication loop", async () => {
  const oldFetch = globalThis.fetch;
  const oldWindow = globalThis.window;
  globalThis.window = { location: { origin: "https://brightline.example" } };
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return { ok: false, status: 401 };
  };
  try {
    const api = await client("production", "https://demo-failure.example");
    api.setDemoAccess(true);
    await assert.rejects(
      api.api("/api/workspace"),
      /Demo session could not be renewed/,
    );
    assert.equal(calls, 2);
    api.setDemoAccess(false);
  } finally {
    globalThis.fetch = oldFetch;
    globalThis.window = oldWindow;
  }
});

test("normal two-port development does not require credentialed CORS for bearer access", async () => {
  const oldFetch = globalThis.fetch;
  const oldWindow = globalThis.window;
  globalThis.window = { location: { origin: "http://localhost:3000" } };
  globalThis.fetch = async (url, options) => {
    assert.equal(options.credentials, "same-origin");
    return { ok: true, status: 200, json: async () => ({ demo_mode: false }) };
  };
  try {
    const api = await client("development");
    api.setDemoAccess(false);
    await api.api("/api/demo/session");
    api.setToken("offline-local-test");
    await api.api("/api/workspace");
  } finally {
    globalThis.fetch = oldFetch;
    globalThis.window = oldWindow;
  }
});

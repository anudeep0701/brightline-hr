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

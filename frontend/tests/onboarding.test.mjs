import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function moduleAt(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022 },
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
  );
}
const { uploadFormat, ingestionStatus, sourceName } = await moduleAt(
  "../src/lib/onboarding.ts",
);
const { uploadFile, setToken, setTenant } = await moduleAt("../src/lib/api.ts");

test("file selection allows supported formats with a bounded size", () => {
  for (const format of ["csv", "json", "ndjson", "jsonl"])
    assert.equal(uploadFormat(`pilot.${format}`, 100), format);
  assert.equal(uploadFormat("pilot.CSV", 2 * 1024 * 1024), "csv");
  assert.throws(() => uploadFormat("pilot.exe", 100), /Choose a CSV/);
  assert.throws(() => uploadFormat("pilot.csv", 2 * 1024 * 1024 + 1), /2 MiB/);
});

test("source labels preserve unknown provenance and distinguish receipt from freshness", () => {
  assert.equal(sourceName("UNKNOWN"), "Unknown source");
  assert.equal(sourceName("FILE_IMPORT"), "File Import");
  assert.equal(sourceName("LIVE_API"), "Live API");
  assert.equal(sourceName("DEMO"), "Demo");
  assert.equal(
    ingestionStatus({ status: "STALE_TELEMETRY", evaluation_overdue: false }),
    "Telemetry is stale",
  );
  assert.equal(
    ingestionStatus({ status: "NO_TELEMETRY", evaluation_overdue: true }),
    "No telemetry received",
  );
  assert.equal(
    ingestionStatus({ status: "RECENT_TRAFFIC", evaluation_overdue: true }),
    "Evaluation overdue",
  );
});

test("preview uploads workspace-scoped bytes without confirmation; import requires preview digest", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ can_import: true }) };
  };
  try {
    setToken("workspace-test");
    setTenant("tenant-a");
    const file = new File(["timestamp,request_id\n"], "pilot.csv");
    await uploadFile(file, "csv", new AbortController().signal);
    await uploadFile(
      file,
      "csv",
      new AbortController().signal,
      "preview-sha256",
    );
    assert.equal(calls[0].url.pathname, "/api/imports/preview");
    assert.equal(calls[0].url.searchParams.get("tenant_id"), "tenant-a");
    assert.equal(
      calls[0].options.headers.Authorization,
      "Bearer workspace-test",
    );
    assert.equal(calls[0].options.headers["Content-Type"], "text/csv");
    assert.equal(calls[0].options.headers["X-Confirm-Import"], undefined);
    assert.equal(calls[0].options.body, file);
    assert.equal(calls[1].url.pathname, "/api/imports/commit");
    assert.equal(
      calls[1].options.headers["X-Preview-Digest"],
      "preview-sha256",
    );
    assert.equal(calls[1].options.headers["X-Confirm-Import"], "true");
  } finally {
    globalThis.fetch = original;
    setToken("");
  }
});

test("failed upload exposes safe server error without assuming import success", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    json: async () => ({
      detail: "Review the preview and explicitly confirm import",
    }),
  });
  try {
    await assert.rejects(
      uploadFile(
        new File(["[]"], "pilot.json"),
        "json",
        new AbortController().signal,
      ),
      /explicitly confirm/,
    );
  } finally {
    globalThis.fetch = original;
  }
});

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import {
  developmentEnvironment,
  frontendEnvironment,
  localConfig,
} from "../dev.mjs";

const demo = { DATABASE_URL: "sqlite:///./data/demo-v4.db", APP_ENV: "demo" };

test("missing database fails before launching either service", () => {
  const script = `import { localConfig } from './scripts/dev.mjs';
    try { localConfig({ DATABASE_URL: '' }); }
    catch (error) { console.error(error.message); process.exitCode = 1; }`;
  const result = spawnSync(
    process.execPath,
    ["--input-type=module", "-e", script],
    {
      cwd: new URL("../../", import.meta.url),
      env: { ...process.env, DATABASE_URL: "" },
      encoding: "utf8",
      timeout: 10000,
    },
  );
  assert.equal(result.status, 1);
  assert.match(result.stderr, /DATABASE_URL is required/);
  assert.doesNotMatch(result.stdout, /Frontend:|Uvicorn/);
});

test("existing SQLite demo configuration receives the matching local API default", () => {
  assert.equal(
    localConfig(demo).NEXT_PUBLIC_API_BASE_URL,
    "http://localhost:8000",
  );
});

test("local launcher refuses production and incompatible browser configuration without echoing values", () => {
  for (const overrides of [
    { APP_ENV: "production" },
    { VERCEL: "1" },
    { CORS_ALLOWED_ORIGINS: "https://private.example" },
    { NEXT_PUBLIC_API_BASE_URL: "https://secret-must-not-appear.example" },
  ]) {
    assert.throws(
      () => localConfig({ ...demo, ...overrides }),
      (error) => {
        assert.doesNotMatch(
          error.message,
          /secret-must-not-appear|private\.example/,
        );
        return true;
      },
    );
  }
});

test("frontend child receives public configuration without backend secrets", () => {
  const environment = {
    ...localConfig(demo),
    OPENAI_API_KEY: "private",
    OPENAI_MODEL: "gpt-6-luna",
    CRON_SECRET: "private",
    PGPASSWORD: "private",
    DEMO_MODE: "true",
    DEMO_TENANT_SLUG: "brightline",
    DEMO_SESSION_SECRET: "private-demo-signing",
    DEMO_ALLOW_FILE_IMPORT: "true",
    PATH: "path",
  };
  const browser = frontendEnvironment(environment);
  for (const name of [
    "DATABASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "CRON_SECRET",
    "PGPASSWORD",
    "DEMO_MODE",
    "DEMO_TENANT_SLUG",
    "DEMO_SESSION_SECRET",
    "DEMO_ALLOW_FILE_IMPORT",
  ]) {
    assert.equal(Object.hasOwn(browser, name), false);
    assert.equal(Object.hasOwn(environment, name), true);
  }
  assert.equal(browser.NEXT_PUBLIC_API_BASE_URL, "http://localhost:8000");
  assert.equal(browser.PATH, "path");
});

// Virtual files only: tests never read or create the developer's environment files.
function virtualFiles(files) {
  return (path) => {
    const name = path.endsWith(".env.local") ? ".env.local" : ".env";
    if (!(name in files))
      throw Object.assign(new Error("missing"), { code: "ENOENT" });
    return files[name];
  };
}

test("root configuration loads quoted values and keeps secrets out of frontend", () => {
  const environment = developmentEnvironment(
    { PATH: "system-path" },
    virtualFiles({
      ".env":
        'DATABASE_URL="sqlite:///./data/pilot.db"\nAPP_ENV=demo\nOPENAI_API_KEY="synthetic-secret"\nOPENAI_MODEL=gpt-6-luna\nNEXT_PUBLIC_API_BASE_URL=http://localhost:8000\nPATH=untrusted\nNODE_OPTIONS=untrusted\n',
    }),
  );
  assert.equal(environment.DATABASE_URL, "sqlite:///./data/pilot.db");
  assert.equal(environment.OPENAI_API_KEY, "synthetic-secret");
  assert.equal(environment.PATH, "system-path");
  assert.equal(environment.NODE_OPTIONS, undefined);
  assert.equal(
    frontendEnvironment(localConfig(environment)).OPENAI_API_KEY,
    undefined,
  );
  assert.equal(
    frontendEnvironment(localConfig(environment)).DATABASE_URL,
    undefined,
  );
});

test("nonempty terminal variables override local files, which override root defaults", () => {
  const environment = developmentEnvironment(
    { DATABASE_URL: "sqlite:///terminal.db", OPENAI_MODEL: "", PATH: "path" },
    virtualFiles({
      ".env":
        "DATABASE_URL=sqlite:///default.db\nOPENAI_MODEL=base-model\nAPP_ENV=demo",
      ".env.local": "DATABASE_URL=sqlite:///local.db\nOPENAI_MODEL=gpt-6-luna",
    }),
  );
  assert.equal(environment.DATABASE_URL, "sqlite:///terminal.db");
  assert.equal(environment.OPENAI_MODEL, "gpt-6-luna");
  assert.equal(
    developmentEnvironment(
      {},
      virtualFiles({
        ".env": "APP_ENV=demo",
        ".env.local": "DATABASE_URL=sqlite:///local.db",
      }),
    ).DATABASE_URL,
    "sqlite:///local.db",
  );
});

test("missing files and blank placeholders retain clear validation", () => {
  assert.throws(
    () => localConfig(developmentEnvironment({}, virtualFiles({}))),
    /DATABASE_URL is required/,
  );
  assert.throws(
    () =>
      localConfig(
        developmentEnvironment(
          {},
          virtualFiles({ ".env": "DATABASE_URL=\nOPENAI_API_KEY=" }),
        ),
      ),
    /DATABASE_URL is required/,
  );
});

test("configuration read errors are sanitized and hosted runs do not load files", () => {
  assert.throws(
    () =>
      developmentEnvironment({}, () => {
        throw new Error("synthetic-private-value");
      }),
    (error) => {
      assert.match(error.message, /Unable to load/);
      assert.doesNotMatch(error.message, /synthetic-private-value/);
      return true;
    },
  );
  for (const environment of [{ VERCEL: "1" }, { APP_ENV: "production" }]) {
    developmentEnvironment(environment, () =>
      assert.fail("Hosted process must not load local files"),
    );
  }
});

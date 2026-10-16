import assert from "node:assert/strict";
import test from "node:test";
import { accessCommand } from "../demo-access.mjs";

test("demo access invokes the existing CLI for brightline using the configured database", () => {
  const plan = accessCommand({
    DATABASE_URL: "sqlite:///synthetic.db",
    APP_ENV: "demo",
    OPENAI_API_KEY: "synthetic-private",
    CRON_SECRET: "synthetic-private",
  });
  assert.deepEqual(plan.args, [
    "scripts/admin.py",
    "brightline",
    "Brightline HR (Synthetic)",
    "--role",
    "operator",
    "--generate-token",
  ]);
  assert.equal(plan.env.DATABASE_URL, "sqlite:///synthetic.db");
  assert.equal(plan.env.OPENAI_API_KEY, undefined);
  assert.equal(plan.env.CRON_SECRET, undefined);
  assert.match(plan.command, /bin\/python$/);
  assert.match(
    accessCommand({ DATABASE_URL: "sqlite:///synthetic.db" }, "win32").command,
    /Scripts\/python.exe$/,
  );
});

test("demo access fails closed for missing database, production or hosted execution", () => {
  for (const environment of [
    {},
    { DATABASE_URL: "sqlite:///synthetic.db", APP_ENV: "production" },
    { DATABASE_URL: "sqlite:///synthetic.db", VERCEL: "1" },
  ]) {
    assert.throws(() => accessCommand(environment));
  }
});

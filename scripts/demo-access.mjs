/** Trusted local credential setup; no hosted execution, migrations or secret files. */
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { developmentEnvironment, localConfig } from "./dev.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export function accessCommand(environment, platform = process.platform) {
  const config = localConfig(environment);
  if (!["demo", "test"].includes(config.APP_ENV || "demo")) {
    throw new Error("Demo access setup requires APP_ENV=demo or test.");
  }
  const env = { ...config };
  delete env.OPENAI_API_KEY;
  delete env.CRON_SECRET;
  return {
    command: join(
      root,
      ".venv",
      platform === "win32" ? "Scripts/python.exe" : "bin/python",
    ),
    args: [
      "scripts/admin.py",
      "brightline",
      "Brightline HR (Synthetic)",
      "--role",
      "operator",
      "--generate-token",
    ],
    env,
  };
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    const plan = accessCommand(developmentEnvironment(process.env));
    const result = spawnSync(plan.command, plan.args, {
      cwd: root,
      env: plan.env,
      stdio: "inherit",
    });
    if (result.error)
      throw new Error(
        "Unable to start the workspace setup CLI. Check .venv and backend dependencies.",
      );
    process.exitCode = result.status ?? 1;
  } catch (error) {
    console.error(`Workspace access setup failed: ${error.message}`);
    process.exitCode = 1;
  }
}

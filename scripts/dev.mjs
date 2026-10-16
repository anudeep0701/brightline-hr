/** Local process supervisor with root configuration loading; no database mutations. */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { parseEnv } from "node:util";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const frontend = join(root, "frontend");

const configNames = [
  "DATABASE_URL",
  "OPENAI_API_KEY",
  "OPENAI_MODEL",
  "CRON_SECRET",
  "APP_ENV",
  "CORS_ALLOWED_ORIGINS",
  "NEXT_PUBLIC_API_BASE_URL",
  "PGPASSWORD",
];

export function developmentEnvironment(environment, read = readFileSync) {
  // Never enable local file loading in a hosted/production process.
  if (environment.VERCEL || environment.APP_ENV === "production")
    return { ...environment };
  const configured = {};
  for (const name of [".env", ".env.local"]) {
    let parsed;
    try {
      parsed = parseEnv(read(join(root, name), "utf8"));
    } catch (error) {
      if (error.code === "ENOENT") continue;
      // Parser/filesystem errors can include secrets; do not echo them.
      throw new Error(
        `Unable to load root ${name}. Check file permissions and dotenv syntax; no configuration values are printed.`,
      );
    }
    for (const key of configNames) {
      if (parsed[key]?.trim()) configured[key] = parsed[key];
    }
  }
  const result = { ...environment };
  for (const key of configNames) {
    if (!environment[key]?.trim() && configured[key] !== undefined)
      result[key] = configured[key];
  }
  return result;
}

export function localConfig(environment) {
  if (!environment.DATABASE_URL?.trim()) {
    throw new Error(
      "DATABASE_URL is required. Set it in the repository-root .env or .env.local, or export it in this terminal before npm run dev. For the existing SQLite demo use DATABASE_URL=sqlite:///./data/demo-v4.db and APP_ENV=demo, then run scripts/seed.py once.",
    );
  }
  if (environment.VERCEL || environment.APP_ENV === "production") {
    throw new Error(
      "This launcher is for local development; use APP_ENV=demo or test. Production services are built through the root Vercel Services configuration.",
    );
  }
  const origins = (environment.CORS_ALLOWED_ORIGINS || "http://localhost:3000")
    .split(",")
    .map((origin) => origin.trim());
  if (!origins.includes("http://localhost:3000")) {
    throw new Error(
      "CORS_ALLOWED_ORIGINS must include http://localhost:3000 for the local dashboard.",
    );
  }
  const base = environment.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  if (!/^http:\/\/(localhost|127\.0\.0\.1):8000\/?$/.test(base)) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL must be http://localhost:8000 or http://127.0.0.1:8000 for this local launcher.",
    );
  }
  return { ...environment, NEXT_PUBLIC_API_BASE_URL: base };
}

export function frontendEnvironment(environment) {
  const result = { ...environment };
  for (const name of [
    "DATABASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "CRON_SECRET",
    "PGPASSWORD",
  ]) {
    delete result[name];
  }
  return result;
}

function checkPort(port) {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", (error) =>
      reject(
        new Error(
          error.code === "EADDRINUSE"
            ? `Port ${port} is already in use. Stop its existing service before npm run dev.`
            : `Cannot bind local port ${port}; allow loopback networking.`,
        ),
      ),
    );
    server.listen(port, "127.0.0.1", () => server.close(resolvePort));
  });
}

async function main() {
  const environment = localConfig(developmentEnvironment(process.env));
  const python = join(
    root,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const next = join(frontend, "node_modules/next/dist/bin/next");
  if (!existsSync(python)) {
    throw new Error(
      "Missing .venv. Run python3 -m venv .venv and install backend/requirements.txt into that environment.",
    );
  }
  if (!existsSync(next)) {
    throw new Error(
      "Missing frontend dependencies. Run npm --prefix frontend ci.",
    );
  }
  // Centralize local configuration at the root so backend credentials are
  // filtered before Next starts. Never let Next independently load those keys.
  if (
    [".env", ".env.local", ".env.development", ".env.development.local"].some(
      (name) => existsSync(join(frontend, name)),
    )
  ) {
    throw new Error(
      "Next.js would independently load a frontend environment file. Move local configuration to the repository-root .env or .env.local so this launcher can keep backend secrets out of the frontend process.",
    );
  }
  const validation = spawnSync(
    python,
    [
      "-c",
      [
        "import sys",
        "sys.path.insert(0, 'backend')",
        "from app.config import get_settings",
        "try: get_settings()",
        "except ValueError as error: raise SystemExit(str(error))",
      ].join("\n"),
    ],
    { cwd: root, env: environment, encoding: "utf8", timeout: 10000 },
  );
  if (validation.status !== 0) {
    // Settings suppresses input values; unexpected tracebacks are never printed.
    const safeError = validation.stderr?.includes(
      "validation error for Settings",
    )
      ? validation.stderr.trim()
      : "Verify the .venv backend dependencies and local configuration.";
    throw new Error(`Backend configuration check failed. ${safeError}`);
  }
  await Promise.all([checkPort(8000), checkPort(3000)]);

  const children = [];
  let stopping = false;
  async function shutdown(code) {
    if (stopping) return;
    stopping = true;
    console.log("\nStopping frontend and backend…");
    const completions = children.map(({ child, exited }) => {
      if (process.platform === "win32") {
        // Windows does not provide POSIX process-group signals; terminate the tree.
        const killer = spawn(
          "taskkill",
          ["/PID", String(child.pid), "/T", "/F"],
          { stdio: "ignore" },
        );
        killer.on("error", () => child.kill());
      } else {
        try {
          process.kill(-child.pid, "SIGTERM");
        } catch {
          /* Already exited. */
        }
      }
      return exited;
    });
    let timer;
    await Promise.race([
      Promise.all(completions),
      new Promise((done) => {
        timer = setTimeout(done, 5000);
      }),
    ]);
    clearTimeout(timer);
    if (process.platform !== "win32") {
      // Also reap descendants if a direct child exited before its worker did.
      for (const { child } of children) {
        try {
          process.kill(-child.pid, "SIGKILL");
        } catch {
          /* Group is gone. */
        }
      }
    }
    process.exit(code);
  }
  process.on("SIGINT", () => void shutdown(0));
  process.on("SIGTERM", () => void shutdown(0));

  function launch(name, command, args, cwd, env) {
    const child = spawn(command, args, {
      cwd,
      env,
      stdio: "inherit",
      detached: process.platform !== "win32",
    });
    const exited = new Promise((done) => {
      child.once("exit", (code) => {
        done();
        if (!stopping) {
          console.error(`${name} exited; stopping the other service.`);
          void shutdown(code || 1);
        }
      });
      child.once("error", () => {
        done();
        console.error(
          `Unable to start ${name}; check its installed dependencies.`,
        );
        void shutdown(1);
      });
    });
    children.push({ child, exited });
  }
  launch(
    "Backend",
    python,
    [
      "-m",
      "uvicorn",
      "app.main:app",
      "--app-dir",
      "backend",
      "--reload",
      "--reload-dir",
      "backend/app",
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
    ],
    root,
    environment,
  );
  launch(
    "Frontend",
    process.execPath,
    [next, "dev", "--hostname", "127.0.0.1", "--port", "3000"],
    frontend,
    frontendEnvironment(environment),
  );
  console.log(
    "Frontend: http://localhost:3000\nBackend:  http://localhost:8000\nAPI docs: http://localhost:8000/docs\nCtrl+C stops both services. Database setup remains explicit.",
  );
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main().catch((error) => {
    console.error(`Development startup failed: ${error.message}`);
    process.exitCode = 1;
  });
}

"""Run a fresh synthetic scenario; optional AI uses the normal authorized API path."""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

SCENARIOS = {
    "all": "all",
    "healthy": "healthy",
    "authentication-outage": "authentication_failures",
    "latency-degradation": "latency_only_degradation",
    "complete-outage": "complete_outage",
    "recovery": "recovery_after_incident",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="all")
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--tenants", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--enable-ai",
        action="store_true",
        help="Allow operator-requested AI using an existing exported OPENAI_API_KEY; no key still falls back safely",
    )
    args = parser.parse_args()
    if os.getenv("VERCEL"):
        parser.error("The demo launcher is local-only and cannot run on Vercel")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    # Configure only this child process; never load/write env files or touch hosted data.
    with TemporaryDirectory(prefix="brightline-demo-") as directory:
        os.environ["APP_ENV"] = "demo"
        os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(directory) / "demo.db")
        if not args.enable_ai:
            os.environ.pop("OPENAI_API_KEY", None)
        import uvicorn

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from app.db.session import get_engine
        from seed import seed

        try:
            seed(
                scenario=SCENARIOS[args.scenario],
                duration_minutes=args.duration,
                tenants=args.tenants,
                random_seed=args.seed,
            )
            print(
                f"Local synthetic scenario: {args.scenario}. Stop with Ctrl+C; rerun to regenerate at the current time."
            )
            uvicorn.run(
                "app.main:app", host="127.0.0.1", port=args.port, log_level="warning"
            )
        finally:
            get_engine().dispose()


if __name__ == "__main__":
    main()

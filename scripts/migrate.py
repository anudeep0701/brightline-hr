"""Apply immutable PostgreSQL migrations using DATABASE_URL from the environment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.migrations import migrate, run_command

if __name__ == "__main__":
    run_command(migrate)

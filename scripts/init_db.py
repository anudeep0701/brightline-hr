"""Initialize PostgreSQL via migrations, or an explicit local demo/test SQLite DB."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.migrations import initialize_database, run_command

if __name__ == "__main__":
    run_command(initialize_database)

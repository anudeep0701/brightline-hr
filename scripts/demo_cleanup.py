"""Owner-only cleanup of tagged assessment imports; no tenant argument or credentials issued."""

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import get_settings
from app.db.migrations import run_command
from app.db.session import get_engine
from app.services.demo_data import clear_demo_imports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        required=True,
        help="Remove only tagged imports from configured DEMO_TENANT_SLUG; keep historical decisions",
    )
    parser.parse_args()
    settings = get_settings()
    if not settings.demo_mode or not settings.demo_tenant_slug:
        parser.error("Cleanup requires explicit DEMO_MODE=true and DEMO_TENANT_SLUG")
    with Session(get_engine()) as db:
        count = clear_demo_imports(db, settings)
    print(
        f"Removed {count} tagged demo import events. Historical metrics/incidents and all other tenant data are retained."
    )


if __name__ == "__main__":
    run_command(main)

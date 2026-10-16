"""Trusted database-side import; each invocation is explicitly bound to one tenant."""

import argparse
import csv
import json
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.session import get_engine
from app.ingestion.files import ingest_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--tenant",
        required=True,
        help="Existing tenant ID; mismatched event tenant IDs are rejected",
    )
    parser.add_argument(
        "--allow-historical",
        action="store_true",
        help="Allow trusted replay older than seven days; never allow future events",
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args(argv)
    try:
        # Check configuration before opening the source file; never load an env file.
        with Session(get_engine()) as session:
            result = ingest_file(
                session,
                args.tenant,
                args.path,
                allow_historical=args.allow_historical,
                batch_size=args.batch_size,
            )
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    except (OSError, csv.Error, UnicodeError):
        parser.exit(
            2,
            "Cannot parse input file: check its path, UTF-8 encoding and CSV structure. Earlier completed chunks, if any, remain committed.\n",
        )
    except SQLAlchemyError:
        parser.exit(
            2,
            "Storage unavailable. Verify DATABASE_URL, connectivity and migrations. Earlier completed chunks, if any, remain committed.\n",
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

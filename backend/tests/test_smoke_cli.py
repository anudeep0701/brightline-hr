"""Smoke tooling must reject hosted/existing targets before opening any connection."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-database-uri-should-not-appear",
        "postgresql://user:should-not-appear@hosted.invalid/brightline_smoke",
        "postgresql://user:should-not-appear@127.0.0.1/customer_production",
        "postgresql://user:should-not-appear@127.0.0.1/brightline_smoke?host=hosted.invalid",
    ],
)
def test_smoke_cli_refuses_unsafe_database_targets_without_secret_echo(url):
    environment = {**os.environ, "DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/smoke_test.py"), "--local-postgres"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "should-not-appear" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert "DATABASE_URL" in result.stderr

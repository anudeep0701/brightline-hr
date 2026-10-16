"""Offline, reproducible multi-tenant integration telemetry.

Import generate_events / to_ingestion_event in tests or demo seeders. This module
never loads application configuration, environment files, databases or APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from faker import Faker

DEFAULT_START = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
GENERATOR_VERSION = "1"
SCENARIOS = (
    "healthy",
    "elevated_error_rate",
    "latency_only_degradation",
    "complete_outage",
    "intermittent_failure",
    "authentication_failures",
    "low_traffic",
    "recovery_after_incident",
    "brief_spike",
    "sustained_bad_windows",
)


@dataclass(frozen=True)
class IntegrationSpec:
    id: str
    name: str
    type: str
    owner: str
    latency_target_ms: int
    scenario: str
    max_gap_minutes: int = 30


CATALOG = (
    IntegrationSpec(
        "workday-payroll",
        "Workday Payroll",
        "payroll",
        "Payroll operations",
        1200,
        "healthy",
    ),
    IntegrationSpec(
        "adp-payroll",
        "ADP Payroll",
        "payroll",
        "Payroll operations",
        1000,
        "elevated_error_rate",
    ),
    IntegrationSpec(
        "docusign",
        "DocuSign",
        "e_signature",
        "People operations",
        1500,
        "latency_only_degradation",
    ),
    IntegrationSpec(
        "greenhouse-ats",
        "Greenhouse ATS",
        "ats",
        "Talent operations",
        1000,
        "complete_outage",
    ),
    IntegrationSpec(
        "okta-directory",
        "Okta Directory Sync",
        "directory_sync",
        "IT operations",
        800,
        "intermittent_failure",
    ),
    IntegrationSpec(
        "slack-notifications",
        "Slack Notifications",
        "notifications",
        "People operations",
        800,
        "authentication_failures",
    ),
    IntegrationSpec(
        "twilio-notifications",
        "Twilio Notifications",
        "notifications",
        "People operations",
        1000,
        "low_traffic",
    ),
    IntegrationSpec(
        "adp-recovery",
        "ADP Payroll (Recovery)",
        "payroll",
        "Payroll operations",
        1000,
        "recovery_after_incident",
    ),
    IntegrationSpec(
        "slack-spike",
        "Slack Notifications (Brief spike)",
        "notifications",
        "People operations",
        800,
        "brief_spike",
    ),
    IntegrationSpec(
        "workday-sustained",
        "Workday Payroll (Sustained failures)",
        "payroll",
        "Payroll operations",
        1200,
        "sustained_bad_windows",
    ),
)

# Static synthetic messages deliberately contain no payloads, URLs or personal data.
ERRORS = {
    401: ("AUTH_TOKEN_EXPIRED", "Synthetic provider rejected an expired access token."),
    429: ("RATE_LIMIT_EXCEEDED", "Synthetic provider request quota exceeded."),
    502: (
        "UPSTREAM_CONNECTION_RESET",
        "Synthetic upstream connection was interrupted.",
    ),
    503: (
        "PROVIDER_UNAVAILABLE",
        "Synthetic provider service is temporarily unavailable.",
    ),
    504: ("REQUEST_TIMEOUT", "Synthetic request exceeded the 30-second timeout."),
}


def validate_options(
    scenario: str, duration_minutes: int, tenants: int, seed: int, start: datetime
):
    if scenario not in ("all", *SCENARIOS):
        raise ValueError(f"Unknown scenario: {scenario}")
    if (
        isinstance(duration_minutes, bool)
        or not isinstance(duration_minutes, int)
        or duration_minutes < 60
        or duration_minutes % 5
    ):
        raise ValueError(
            "Duration must be a multiple of 5 minutes and at least 60 minutes"
        )
    if isinstance(tenants, bool) or not isinstance(tenants, int) or tenants < 1:
        raise ValueError("Number of tenants must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("Random seed must be a nonnegative integer")
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("Start timestamp must include a timezone")
    start = start.astimezone(timezone.utc)
    if start.minute % 5 or start.second or start.microsecond:
        raise ValueError("Start must align to a completed 5-minute boundary")


def integrations_for(scenario: str = "all") -> tuple[IntegrationSpec, ...]:
    if scenario == "all":
        return CATALOG
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    # A focused run applies the requested scenario to each of the seven providers.
    return tuple(
        IntegrationSpec(x.id, x.name, x.type, x.owner, x.latency_target_ms, scenario)
        for x in CATALOG[:7]
    )


def tenant_specs(tenants: int, seed: int) -> list[dict[str, str]]:
    fake = Faker("en_US")
    fake.seed_instance(seed)
    return [
        {
            "id": "brightline" if i == 0 else f"tenant-{i + 1:03d}",
            "name": "Brightline HR (Synthetic)"
            if i == 0
            else f"{fake.company()} (Synthetic)",
        }
        for i in range(tenants)
    ]


def phase_bounds(duration_minutes: int) -> tuple[int, int]:
    breach_start = (duration_minutes // 3 // 5) * 5
    recovery_start = min(breach_start + duration_minutes // 4, duration_minutes - 25)
    return breach_start, recovery_start


def _status(
    scenario: str, minute: int, slot: int, ordinal: int, duration: int
) -> tuple[int, bool]:
    breach, recovery = phase_bounds(duration)
    if scenario == "complete_outage":
        return (504, True) if slot % 3 == 0 else (503, False)
    if scenario == "authentication_failures":
        return 401, False
    if scenario == "elevated_error_rate" and ordinal % 9 == 0:
        return (429 if ordinal % 18 == 0 else 503), False
    if scenario == "intermittent_failure" and (minute // 5) % 3 == 1 and slot % 3 == 0:
        return 502, False
    if (
        scenario == "recovery_after_incident"
        and breach <= minute < recovery
        and slot % 2 == 0
    ):
        return 503, False
    if scenario == "sustained_bad_windows" and minute >= breach and slot % 2 == 0:
        return 503, False
    if scenario == "brief_spike" and minute == breach and slot == 0:
        return 503, False
    return (200, False)


def generate_events(
    *,
    scenario: str = "all",
    duration_minutes: int = 90,
    tenants: int = 3,
    seed: int = 42,
    start: datetime = DEFAULT_START,
) -> Iterator[dict]:
    """Yield events in tenant/integration/time order, independent of system clock.

    Every series gets its own RNG stream so tenant 1 remains identical when more
    tenants are requested. IDs derive from series seed + event time and are unique
    across tenants. A scenario switch changes IDs, avoiding accidental deduping.
    """
    validate_options(scenario, duration_minutes, tenants, seed, start)
    start = start.astimezone(timezone.utc)
    for tenant in tenant_specs(tenants, seed):
        for integration in integrations_for(scenario):
            series_key = f"v{GENERATOR_VERSION}:{seed}:{tenant['id']}:{integration.id}:{integration.scenario}"
            series_seed = int.from_bytes(
                hashlib.sha256(series_key.encode()).digest()[:8], "big"
            )
            rng = np.random.default_rng(series_seed)
            # Tenant/provider-specific load with smooth intraday variation and bounded jitter.
            base_load = int(rng.integers(9, 14))
            ordinal = 0
            for minute in range(duration_minutes):
                daily_phase = (
                    (start.hour * 60 + start.minute + minute) / 1440 * 2 * math.pi
                )
                load = max(
                    8,
                    round(
                        base_load * (1 + 0.15 * math.sin(daily_phase))
                        + rng.normal(0, 1)
                    ),
                )
                if integration.scenario == "low_traffic":
                    load = 1 if minute % 10 == 0 else 0
                seconds = sorted(rng.choice(59, size=load, replace=load > 59).tolist())
                for slot, second in enumerate(seconds):
                    at = start + timedelta(minutes=minute, seconds=int(second) + 1)
                    status, timed_out = _status(
                        integration.scenario, minute, slot, ordinal, duration_minutes
                    )
                    latency = float(
                        np.clip(
                            rng.lognormal(
                                math.log(integration.latency_target_ms * 0.38), 0.22
                            ),
                            25,
                            integration.latency_target_ms * 1.2,
                        )
                    )
                    if integration.scenario == "latency_only_degradation":
                        latency = float(
                            rng.uniform(1.7, 2.7) * integration.latency_target_ms
                        )
                    if (
                        integration.scenario == "brief_spike"
                        and minute == phase_bounds(duration_minutes)[0]
                        and slot == 1
                    ):
                        latency = integration.latency_target_ms * 6
                    if status == 401:
                        latency = float(rng.uniform(40, 100))
                    if timed_out:
                        latency = 30000.0
                    code, message = ERRORS.get(status, (None, None))
                    request_key = f"{series_key}:duration={duration_minutes}:{at.isoformat()}:{slot}"
                    yield {
                        "timestamp": at.isoformat(),
                        "tenant_id": tenant["id"],
                        "integration_id": integration.id,
                        "integration_name": integration.name,
                        "integration_type": integration.type,
                        "request_id": str(uuid5(NAMESPACE_URL, request_key)),
                        "http_status": status,
                        "latency_ms": round(latency, 2),
                        "error_code": code,
                        "error_message": message,
                        "scenario": integration.scenario,
                        "timed_out": timed_out,
                        "latency_target_ms": integration.latency_target_ms,
                    }
                    ordinal += 1


def to_ingestion_event(event: dict) -> dict:
    """Explicit boundary: drop tenant/name/raw errors before existing API ingestion.

    Group by tenant and authenticate separately; never forward tenant identity in
    a request body as authorization. The backend derives error category itself.
    """
    return {
        "event_id": event["request_id"],
        "integration_id": event["integration_id"],
        "occurred_at": event["timestamp"],
        "status_code": event["http_status"],
        "latency_ms": event["latency_ms"],
        "timed_out": event["timed_out"],
    }


def write_dataset(output: Path, **options) -> dict:
    """Write a streaming JSONL dataset and reproducible metadata manifest."""
    start = options.get("start", DEFAULT_START)
    scenario = options.get("scenario", "all")
    duration = options.get("duration_minutes", 90)
    tenants = options.get("tenants", 3)
    seed = options.get("seed", 42)
    validate_options(scenario, duration, tenants, seed, start)
    output.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    digest = hashlib.sha256()
    with (output / "requests.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        for event in generate_events(**options):
            line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
            stream.write(line)
            digest.update(line.encode())
            counts[event["scenario"]] = counts.get(event["scenario"], 0) + 1
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "scenario": scenario,
        "duration_minutes": duration,
        "start": start.astimezone(timezone.utc).isoformat(),
        "end_exclusive": (start + timedelta(minutes=duration))
        .astimezone(timezone.utc)
        .isoformat(),
        "tenants": tenant_specs(tenants, seed),
        "integration_series_count": tenants * len(integrations_for(scenario)),
        "events_by_scenario": counts,
        "event_count": sum(counts.values()),
        "requests_sha256": digest.hexdigest(),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    parser.add_argument(
        "--duration",
        "--duration-minutes",
        dest="duration_minutes",
        type=int,
        default=90,
        help="Minutes; multiple of 5, minimum 60",
    )
    parser.add_argument(
        "--tenants", "--num-tenants", dest="tenants", type=int, default=3
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--start",
        default=DEFAULT_START.isoformat(),
        help="Timezone-aware ISO timestamp on a five-minute boundary",
    )
    parser.add_argument("--output", type=Path, default=Path("data/synthetic/generated"))
    args = parser.parse_args(argv)
    try:
        start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        manifest = write_dataset(
            args.output,
            scenario=args.scenario,
            duration_minutes=args.duration_minutes,
            tenants=args.tenants,
            seed=args.seed,
            start=start,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(
        f"Generated {manifest['event_count']} events across {manifest['integration_series_count']} series in {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

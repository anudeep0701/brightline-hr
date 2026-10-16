"""Offline JSON array/envelope, JSONL and CSV imports through the shared service."""

import csv
import json
from itertools import islice
from pathlib import Path

from app.ingestion.service import ingest


def file_records(path: Path):
    suffix = path.suffix.lower()
    if suffix not in (".json", ".jsonl", ".ndjson", ".csv"):
        raise ValueError("Input must be a .json, .jsonl, .ndjson or .csv file")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        yield from stream_records(stream, suffix)


def stream_records(stream, suffix):
    if suffix in (".jsonl", ".ndjson"):
        for line in stream:
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # Preserve record position; the common validator rejects it safely.
                yield None
    elif suffix == ".json":
        try:
            records = json.load(stream)
        except json.JSONDecodeError:
            raise ValueError(
                "JSON document is invalid; use JSONL for independently recoverable records"
            ) from None
        if isinstance(records, dict):
            keys = set(records)
            if keys == {"events"}:
                records = records["events"]
            elif keys == {"logs"}:
                records = records["logs"]
        if not isinstance(records, list):
            raise ValueError(
                "JSON must contain an array, or an events/logs array envelope"
            )
        yield from records
    else:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames
        if (
            not headers
            or any(not h for h in headers)
            or len(headers) != len(set(headers))
        ):
            raise ValueError("CSV requires unique nonempty column headers")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                yield None
                continue
            # CSV has no null literal; empty nullable metadata means absent.
            for key in (
                "error_code",
                "error_message",
                "integration_name",
                "integration_type",
                "tenant_id",
                "scenario",
                "latency_target_ms",
            ):
                if row.get(key) == "":
                    row.pop(key)
            yield row


def ingest_file(session, tenant_id, path, *, allow_historical=False, batch_size=1000):
    if not 1 <= batch_size <= 1000:
        raise ValueError("Batch size must be between 1 and 1000")
    records = iter(file_records(Path(path)))
    summary = dict(
        accepted=0, rejected=0, duplicates=0, rejections=[], rejections_omitted=0
    )
    offset = 0
    while chunk := list(islice(records, batch_size)):
        result = ingest(
            session,
            tenant_id,
            chunk,
            allow_historical=allow_historical,
            source_type="FILE_IMPORT",
        )
        for key in ("accepted", "rejected", "duplicates"):
            summary[key] += result[key]
        for rejection in result["rejections"]:
            if len(summary["rejections"]) < 100:
                summary["rejections"].append(
                    dict(rejection, index=rejection["index"] + offset)
                )
            else:
                summary["rejections_omitted"] += 1
        offset += len(chunk)
    summary["inserted"] = summary["accepted"]
    return summary

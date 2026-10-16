"""Bounded in-memory pilot uploads; no filenames, public files or staging secrets."""

import csv
import hashlib
import io
from itertools import islice

from app.ingestion.files import stream_records
from app.ingestion.service import ingest
from app.services.errors import ServiceError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_RECORDS = 1000
FORMATS = {"csv": ".csv", "json": ".json", "ndjson": ".ndjson", "jsonl": ".jsonl"}
CONTENT_TYPES = {
    "csv": {"text/csv", "application/csv"},
    "json": {"application/json"},
    "ndjson": {"application/x-ndjson", "application/ndjson"},
    "jsonl": {"application/x-ndjson", "application/ndjson"},
}


async def read_upload(stream, file_format, content_type):
    if (
        file_format not in FORMATS
        or content_type.split(";", 1)[0].lower() not in CONTENT_TYPES[file_format]
    ):
        raise ServiceError(
            415,
            "unsupported_file_type",
            "Use CSV, JSON, NDJSON or JSONL with its matching content type",
        )
    data = bytearray()
    async for chunk in stream:
        if len(data) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ServiceError(413, "file_too_large", "Files must be at most 2 MiB")
        data.extend(chunk)
    return bytes(data)


def parse_upload(data, file_format):
    try:
        stream = io.StringIO(data.decode("utf-8-sig"), newline="")
        rows = list(
            islice(stream_records(stream, FORMATS[file_format]), MAX_UPLOAD_RECORDS + 1)
        )
    except (ValueError, UnicodeError, csv.Error, RecursionError):
        raise ServiceError(
            422,
            "malformed_file",
            "Cannot parse file. Check UTF-8 encoding, JSON structure or unique CSV headers; no rows were imported",
        ) from None
    if not rows:
        raise ServiceError(422, "empty_file", "File contains no request records")
    if len(rows) > MAX_UPLOAD_RECORDS:
        raise ServiceError(
            413,
            "too_many_records",
            "Split the file into at most 1,000 records per upload",
        )
    return rows


def preview_upload(db, tenant_id, data, file_format):
    rows = parse_upload(data, file_format)
    report = ingest(
        db,
        tenant_id,
        rows,
        allow_historical=True,
        preview=True,
        source_type="FILE_IMPORT",
    )
    return {**report, "file_digest": hashlib.sha256(data).hexdigest()}


def commit_upload(db, tenant_id, data, file_format, confirmed, digest):
    if confirmed != "true":
        raise ServiceError(
            422,
            "confirmation_required",
            "Review the preview and explicitly confirm import",
        )
    if digest != hashlib.sha256(data).hexdigest():
        raise ServiceError(
            409,
            "file_changed",
            "File changed after preview; validate the selected file again",
        )
    return ingest(
        db,
        tenant_id,
        parse_upload(data, file_format),
        allow_historical=True,
        strict_authorization=True,
        source_type="FILE_IMPORT",
    )

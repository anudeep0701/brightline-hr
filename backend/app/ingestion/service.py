"""Tenant-scoped partial batch ingestion with database-enforced idempotency."""

from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DataError, IntegrityError

from app.ingestion.errors import IngestionBatchError
from app.models.entities import Integration, RequestEvent, Tenant
from app.schemas.ingestion import IngestResult, Rejection, RequestEventInput


def ingest(
    session,
    tenant_id,
    batch,
    *,
    allow_historical=False,
    now=None,
    strict_authorization=False,
    preview=False,
    source_type="LIVE_API",
    import_batch_id=None,
    commit=True,
    bulk=False,
):
    """One transaction per batch; invalid records use savepoints and never abort peers.

    Only trusted offline imports may opt into historical replay. API callers cannot
    change that flag. Storage outages abort the transaction and return no counts.
    """
    records = (
        batch
        if isinstance(batch, list)
        else batch.logs
        if hasattr(batch, "logs")
        else batch.events
    )
    if not 1 <= len(records) <= 1000:
        raise ValueError("Batch must contain 1 to 1000 records")
    if source_type not in {"LIVE_API", "FILE_IMPORT", "DEMO", "UNKNOWN"}:
        raise ValueError("Unsupported trusted ingestion source")
    tenant_query = select(Tenant).where(Tenant.id == tenant_id)
    tenant = session.scalar(tenant_query if preview else tenant_query.with_for_update())
    if tenant is None:
        raise ValueError(
            "Tenant not found; provision the tenant and integrations before ingestion"
        )
    integrations = {
        x.id: x
        for x in session.scalars(
            select(Integration).where(Integration.tenant_id == tenant_id)
        )
    }
    now = now or datetime.now(timezone.utc)
    result = IngestResult()
    dialect = session.get_bind().dialect.name
    insert = (
        pg_insert
        if dialect == "postgresql"
        else sqlite_insert
        if dialect == "sqlite"
        else None
    )
    if insert is None:
        raise ValueError("Ingestion requires PostgreSQL or demo/test SQLite")

    def reject(index, code, fields=()):
        result.rejected += 1
        result.rejections.append(Rejection(index=index, code=code, fields=list(fields)))

    validated = []
    permission_failure = False
    for index, record in enumerate(records):
        try:
            event = RequestEventInput.model_validate(record)
        except ValidationError as exc:
            # No submitted values or exception strings in operator-visible reports.
            # Return only known schema field names; attacker-controlled extra keys
            # may themselves contain secrets and are intentionally omitted.
            known = set(RequestEventInput.model_fields) | {
                "timestamp",
                "request_id",
                "http_status",
            }
            fields = sorted(
                {
                    str(e["loc"][0])
                    for e in exc.errors(include_input=False)
                    if e["loc"] and str(e["loc"][0]) in known
                }
            )
            reject(index, "invalid_record", fields)
            continue
        if event.tenant_id is not None and event.tenant_id != tenant_id:
            permission_failure = True
            reject(index, "tenant_mismatch", ["tenant_id"])
            continue
        integration = integrations.get(event.integration_id)
        if integration is None:
            permission_failure = True
            reject(index, "unknown_integration", ["integration_id"])
            continue
        if event.occurred_at > now or (
            not allow_historical and event.occurred_at < now - timedelta(days=7)
        ):
            reject(index, "timestamp_out_of_range", ["timestamp"])
            continue
        validated.append((index, event, integration))

    if strict_authorization and permission_failure:
        # Authorization is checked for the whole batch before storing any record.
        for index, _, _ in validated:
            reject(index, "batch_not_processed")
        result.rejections.sort(key=lambda error: error.index)
        raise IngestionBatchError(
            403,
            "ingestion_forbidden",
            "Batch contains a tenant or integration outside this credential's scope; no events stored",
            result,
        )
    if strict_authorization and not validated:
        raise IngestionBatchError(
            422, "invalid_events", "No valid request events in this batch", result
        )

    if preview:
        existing = set(
            session.scalars(
                select(RequestEvent.event_id).where(
                    RequestEvent.tenant_id == tenant_id,
                    RequestEvent.event_id.in_(
                        [event.event_id for _, event, _ in validated]
                    ),
                )
            )
        )
        seen = set(existing)
        for _, event, _ in validated:
            if event.event_id in seen:
                result.duplicates += 1
            else:
                result.accepted += 1
                seen.add(event.event_id)
        return dict(
            total_records=len(records),
            valid_records=result.accepted,
            duplicates=result.duplicates,
            rejected_records=result.rejected,
            unknown_integrations=sum(
                item.code == "unknown_integration" for item in result.rejections
            ),
            validation_errors=[item.model_dump() for item in result.rejections],
            can_import=not permission_failure and result.accepted > 0,
        )

    pending = []
    for index, event, integration in validated:
        raw = event.model_dump(mode="json")
        raw["tenant_id"] = tenant_id
        if import_batch_id is not None:
            raw["demo_import_batch_id"] = import_batch_id
        values = dict(
            tenant_id=tenant_id,
            event_id=event.event_id,
            integration_id=event.integration_id,
            occurred_at=event.occurred_at,
            status_code=event.status_code,
            latency_ms=event.latency_ms,
            timed_out=event.timed_out,
            error_category=event.error_category,
            integration_name=event.integration_name or integration.name,
            integration_type=event.integration_type or integration.category,
            error_code=event.error_code,
            error_message=event.error_message,
            received_at=now,
            raw_event=raw,
            source_type=source_type,
        )
        pending.append((index, values))
    if bulk and pending:
        try:
            with session.begin_nested():
                statement = (
                    insert(RequestEvent)
                    .values([row for _, row in pending])
                    .on_conflict_do_nothing(index_elements=["tenant_id", "event_id"])
                    .returning(RequestEvent.event_id)
                )
                stored = session.execute(statement).scalars().all()
            result.accepted += len(stored)
            result.duplicates += len(pending) - len(stored)
            pending = []
        except (IntegrityError, DataError):
            # The savepoint rolls the whole statement back. Preserve the normal
            # per-record rejection contract if one database constraint failed.
            pass
    for index, values in pending:
        try:
            with session.begin_nested():
                statement = (
                    insert(RequestEvent)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["tenant_id", "event_id"])
                    .returning(RequestEvent.event_id)
                )
                stored = session.execute(statement).scalar_one_or_none()
            if stored is None:
                result.duplicates += 1
            else:
                result.accepted += 1
        except (IntegrityError, DataError):
            reject(index, "constraint_violation")
    result.rejections.sort(key=lambda error: error.index)
    if strict_authorization and result.rejected == len(records):
        raise IngestionBatchError(
            422, "invalid_events", "No valid request events in this batch", result
        )
    if commit:
        session.commit()
    return result.model_dump()

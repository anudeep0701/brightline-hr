from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models.entities import Integration, RequestLog, Tenant


def ingest(session, tenant_id, batch):
    session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    now = datetime.now(timezone.utc)
    ids = set(
        session.scalars(
            select(Integration.id).where(Integration.tenant_id == tenant_id)
        )
    )
    for log in batch.logs:
        if log.integration_id not in ids:
            raise HTTPException(422, "Batch contains unknown integration")
        if log.occurred_at > now or log.occurred_at < now - timedelta(days=7):
            raise HTTPException(422, "Events must be within the past seven days")
    inserted = 0
    for log in batch.logs:
        if session.get(RequestLog, (tenant_id, log.event_id)) is None:
            session.add(RequestLog(tenant_id=tenant_id, **log.model_dump()))
            session.flush()
            inserted += 1
    session.commit()
    return dict(inserted=inserted, duplicates=len(batch.logs) - inserted)

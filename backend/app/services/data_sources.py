"""Observed ingestion evidence, not an assertion that an exporter is operational."""

from sqlalchemy import func, select

from app.models.entities import RequestEvent


def data_sources(db, tenant_id, items):
    observed = {}
    for integration_id, source, received in db.execute(
        select(
            RequestEvent.integration_id,
            RequestEvent.source_type,
            func.max(RequestEvent.received_at),
        )
        .where(RequestEvent.tenant_id == tenant_id)
        .group_by(RequestEvent.integration_id, RequestEvent.source_type)
    ):
        observed.setdefault(integration_id, []).append(
            dict(source_type=source, last_received_at=received)
        )
    return dict(
        tenant_id=tenant_id,
        items=[
            dict(
                integration_id=item["integration"]["id"],
                integration_name=item["integration"]["name"],
                sources=sorted(
                    observed.get(item["integration"]["id"], []),
                    key=lambda row: row["source_type"],
                ),
                freshness=item["freshness"],
            )
            for item in items
        ],
    )

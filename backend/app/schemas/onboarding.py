from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.contracts import FreshnessOut


class SourceOut(BaseModel):
    source_type: Literal["LIVE_API", "FILE_IMPORT", "DEMO", "UNKNOWN"]
    last_received_at: datetime


class DataSourceOut(BaseModel):
    integration_id: str
    integration_name: str
    sources: list[SourceOut]
    freshness: FreshnessOut


class DataSourcesOut(BaseModel):
    tenant_id: str
    items: list[DataSourceOut]

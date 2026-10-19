from pydantic import BaseModel


class DemoConfiguration(BaseModel):
    demo_mode: bool


class DemoSession(DemoConfiguration):
    tenant_id: str
    tenant_name: str
    expires_at: int

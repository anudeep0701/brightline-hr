from pydantic import BaseModel


class DemoConfiguration(BaseModel):
    demo_mode: bool


class DemoSession(DemoConfiguration):
    tenant_id: str
    tenant_name: str
    expires_at: int


class DemoCapabilities(DemoConfiguration):
    demo_allow_file_import: bool = False


class DemoRefresh(BaseModel):
    accepted: int
    evaluated: int
    bucket: str

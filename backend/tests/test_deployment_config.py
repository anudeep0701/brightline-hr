"""Same-origin production configuration must preserve safe local CORS behavior."""

import pytest
from app.config import Settings


def production(**overrides):
    return Settings(
        app_env="production",
        database_url="postgresql://test@localhost/unused",
        cron_secret="test-only-cron-secret-32-characters-long",
        **overrides,
    )


def test_same_origin_production_does_not_require_cors_configuration(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    assert production().cors_origins == []


def test_local_two_port_development_retains_exact_cors_default(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    assert Settings(app_env="demo").cors_origins == ["http://localhost:3000"]


def test_optional_production_cross_origin_grant_remains_explicit():
    assert production(cors_allowed_origins="https://ops.example").cors_origins == [
        "https://ops.example"
    ]


@pytest.mark.parametrize(
    "origin",
    ["*", "http://ops.example", "https://ops.example/path", "https://user@ops.example"],
)
def test_production_rejects_unsafe_explicit_cors_origins(origin):
    with pytest.raises(ValueError, match="exact HTTPS"):
        production(cors_allowed_origins=origin)

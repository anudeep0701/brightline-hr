from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_ignore_empty=True, extra="ignore", hide_input_in_errors=True
    )
    app_env: Literal["demo", "test", "production"] = "demo"
    database_url: str = ""
    openai_api_key: str = ""
    openai_model: str = Field(
        default="gpt-6-luna",
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_.:-]+$",
    )
    cron_secret: str = ""
    cors_allowed_origins: str = ""

    @property
    def cors_origins(self) -> list[str]:
        configured = [
            x.strip() for x in self.cors_allowed_origins.split(",") if x.strip()
        ]
        if configured:
            return configured
        return [] if self.app_env == "production" else ["http://localhost:3000"]

    @model_validator(mode="after")
    def secure_production(self):
        import os

        if not self.database_url.strip():
            raise ValueError(
                "DATABASE_URL is not configured. Set DATABASE_URL in the process environment to your Supabase PostgreSQL connection URI. For local demo/tests only, explicitly select a SQLite database."
            )
        if not self.database_url.startswith(
            ("postgres://", "postgresql://", "postgresql+psycopg://", "sqlite:")
        ):
            raise ValueError(
                "DATABASE_URL must use PostgreSQL (or explicit demo/test SQLite)"
            )

        if os.getenv("VERCEL") and self.app_env != "production":
            raise ValueError(
                "Vercel requires APP_ENV=production; demo must remain local"
            )
        if self.app_env == "production":
            if not self.database_url.startswith(
                ("postgres://", "postgresql://", "postgresql+psycopg://")
            ):
                raise ValueError("Production requires PostgreSQL")
            if len(self.cron_secret) < 32:
                raise ValueError(
                    "Production requires CRON_SECRET of at least 32 characters"
                )
            origins = [urlparse(x) for x in self.cors_origins]
            if any(
                o.scheme != "https"
                or not o.netloc
                or o.path not in ("",)
                or o.query
                or o.fragment
                or o.username
                for o in origins
            ):
                raise ValueError(
                    "Production requires exact HTTPS CORS origins without paths"
                )
        return self


@lru_cache
def get_settings():
    return Settings()

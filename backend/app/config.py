from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True, extra="ignore")
    app_env: Literal["demo", "test", "production"] = "demo"
    database_url: str = "sqlite:///../data/demo.db"
    openai_api_key: str = ""
    cron_secret: str = ""
    cors_allowed_origins: str = "http://localhost:3000"

    @model_validator(mode="after")
    def secure_production(self):
        import os

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
            origins = [
                urlparse(x.strip()) for x in self.cors_allowed_origins.split(",")
            ]
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

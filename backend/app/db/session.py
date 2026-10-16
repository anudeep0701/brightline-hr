from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings


@lru_cache
def get_engine():
    url = get_settings().database_url
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        return engine
    try:
        return create_engine(
            url, poolclass=NullPool, connect_args={"prepare_threshold": None}
        )
    except (ArgumentError, ValueError):
        raise ValueError(
            "DATABASE_URL is invalid; configure a valid PostgreSQL connection URI without printing credentials"
        ) from None


def get_db():
    with sessionmaker(get_engine(), expire_on_commit=False)() as session:
        yield session

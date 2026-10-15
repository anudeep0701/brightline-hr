from functools import lru_cache

from sqlalchemy import create_engine, event
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
    return create_engine(
        url, poolclass=NullPool, connect_args={"prepare_threshold": None}
    )


def get_db():
    with sessionmaker(get_engine(), expire_on_commit=False)() as session:
        yield session

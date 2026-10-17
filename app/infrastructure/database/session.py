"""Request-scoped SQLAlchemy sessions over a cached TLS engine."""

from collections.abc import Generator
from functools import lru_cache

from fastapi import HTTPException, status
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.infrastructure.database.engine import create_database_engine


@lru_cache(maxsize=1)
def get_database_engine() -> Engine:
    """Create the process-wide database engine on first database use."""

    return create_database_engine()


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return a factory that creates independent request-scoped sessions."""

    return sessionmaker(
        bind=get_database_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


def get_database_session() -> Generator[Session, None, None]:
    """Yield one database session and always close it after the request."""

    if not get_settings().database_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A persistência ainda não está configurada.",
        )

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def dispose_database_engine() -> None:
    """Close pooled connections during API shutdown."""

    if get_database_engine.cache_info().currsize:
        get_database_engine().dispose()
    get_session_factory.cache_clear()
    get_database_engine.cache_clear()

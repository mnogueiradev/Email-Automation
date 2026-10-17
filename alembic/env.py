"""Alembic environment using the application's verified-TLS TiDB engine."""

from logging.config import fileConfig

from alembic import context

from app.infrastructure.database import models  # noqa: F401 - register mapped tables
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import create_database_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render migration SQL without reading or embedding database credentials."""

    context.configure(
        url="mysql+pymysql://offline:offline@localhost/email_automation",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations through the same certificate-verified engine as the app."""

    engine = create_database_engine()
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

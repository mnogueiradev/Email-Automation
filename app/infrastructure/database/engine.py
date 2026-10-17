"""TiDB engine factory using verified TLS and explicit configuration."""

from sqlalchemy import URL, Engine, create_engine

from app.config import Settings, get_settings


def create_database_engine(settings: Settings | None = None) -> Engine:
    """Create a SQLAlchemy engine without opening a network connection.

    PyMySQL's certificate and hostname checks are always enabled. Callers are
    responsible for closing the returned engine during process shutdown.
    """

    configured = settings or get_settings()
    if not configured.database_configured:
        raise RuntimeError("A configuração completa e TLS do TiDB não está disponível.")

    assert configured.db_host is not None
    assert configured.db_user is not None
    assert configured.db_password is not None
    assert configured.db_name is not None
    assert configured.db_ca_file is not None

    url = URL.create(
        drivername="mysql+pymysql",
        username=configured.db_user,
        password=configured.db_password.get_secret_value(),
        host=configured.db_host,
        port=configured.db_port,
        database=configured.db_name,
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
        connect_args={
            "ssl_ca": str(configured.db_ca_file),
            "ssl_verify_cert": True,
            "ssl_verify_identity": True,
            "init_command": "SET time_zone = '+00:00'",
            "connect_timeout": 10,
            "read_timeout": 30,
            "write_timeout": 30,
        },
    )

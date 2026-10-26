from contextlib import contextmanager
from collections.abc import Iterator

import sqlalchemy as sa
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from fitcheck_backend.config import Settings


class StorageConfigurationError(RuntimeError):
    pass


def create_engine(settings: Settings) -> Engine:
    if settings.database_url is None:
        raise StorageConfigurationError("FITCHECK_DATABASE_URL is required for storage")
    try:
        url = make_url(settings.database_url.get_secret_value())
        allowed_query = {"sslmode", "sslrootcert", "sslcert", "sslkey", "sslpassword", "client_encoding", "application_name"}
        if (url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}
                or not url.host or not url.database
                or any(c in url.host for c in "@/\\?#") or any(c.isspace() or ord(c)<32 for c in url.host)
                or ("%" in url.host and ":" not in url.host)
                or (url.port is not None and not 1 <= url.port <= 65535)
                or set(url.query) - allowed_query
                or any(not isinstance(value, str) or "\x00" in value for value in url.query.values())
                or ("sslmode" in url.query and url.query["sslmode"] not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})):
            raise ValueError()
        # SQLAlchemy masks the authority password, but not URL query values.
        # Keep supported TLS key passwords solely in driver connection arguments.
        tls_password = url.query.get("sslpassword")
        url = url.difference_update_query(["sslpassword"])
        url = url.set(drivername="postgresql+psycopg")
    except Exception:
        raise StorageConfigurationError("Invalid PostgreSQL database configuration") from None
    connect_args = {"options": f"-c statement_timeout={settings.statement_timeout_ms}", "connect_timeout": 5}
    if tls_password is not None:
        connect_args["sslpassword"] = tls_password
    return sa.create_engine(
        url, pool_size=settings.pool_size, max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds, pool_pre_ping=True,
        echo=False, hide_parameters=True,
        connect_args=connect_args,
    )


@contextmanager
def unit_of_work(engine: Engine) -> Iterator[Session]:
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()

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
        if (url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}
                or not url.host or not url.database or url.port == 0
                or any(key in url.query for key in {"host", "hostaddr", "dbname", "user", "password", "port", "options"})):
            raise ValueError()
        url = url.set(drivername="postgresql+psycopg")
    except Exception:
        raise StorageConfigurationError("Invalid PostgreSQL database configuration") from None
    return sa.create_engine(
        url, pool_size=settings.pool_size, max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds, pool_pre_ping=True,
        echo=False, hide_parameters=True,
        connect_args={"options": f"-c statement_timeout={settings.statement_timeout_ms}", "connect_timeout": 5},
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

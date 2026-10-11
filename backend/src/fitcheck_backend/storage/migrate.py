"""Run explicitly before API/worker; never called at application startup."""
from contextlib import contextmanager
from pathlib import Path
import sys
import time

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection

from fitcheck_backend.config import Settings
from .database import create_engine, StorageConfigurationError

MIGRATION_LOCK_KEY = 0x464954434845434B


class MigrationLockTimeout(RuntimeError):
    pass


def migration_config(connection: Connection) -> Config:
    packaged = Path(__file__).parents[1] / "_migrations"
    source = Path(__file__).parents[3]
    directory = packaged if packaged.is_dir() else source / "migrations"
    config = Config(str(packaged / "alembic.ini" if packaged.is_dir() else source / "alembic.ini"))
    config.set_main_option("script_location", str(directory).replace("%", "%%"))
    config.attributes["connection"] = connection
    return config


@contextmanager
def migration_connection(settings: Settings):
    engine = create_engine(settings.model_copy(update={"statement_timeout_ms": 120000}))
    try:
        with engine.connect() as conn:
            locked = False
            deadline = time.monotonic() + 10
            try:
                while not locked:
                    locked = conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
                    conn.commit()
                    if not locked:
                        if time.monotonic() >= deadline:
                            raise MigrationLockTimeout("Another migration is still running")
                        time.sleep(0.1)
                with conn.begin():
                    yield conn
            finally:
                if conn.in_transaction():
                    conn.rollback()
                if locked:
                    conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
                    conn.commit()
    finally:
        engine.dispose()


def run_migrations(settings: Settings, *, revision: str = "head") -> None:
    with migration_connection(settings) as conn:
        command.upgrade(migration_config(conn), revision)


def check_schema(settings: Settings) -> None:
    with migration_connection(settings) as conn:
        command.check(migration_config(conn))


def main() -> int:
    if sys.argv[1:] not in [["upgrade"], ["check"]]:
        print("Usage: python -m fitcheck_backend.storage.migrate {upgrade|check}", file=sys.stderr)
        return 2
    try:
        settings = Settings()
        if sys.argv[1] == "upgrade":
            run_migrations(settings)
        else:
            check_schema(settings)
    except StorageConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Database migration failed; verify configuration, database access and migration state", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from datetime import UTC, datetime, timedelta, timezone
import importlib

import pytest
from pydantic import ValidationError

from fitcheck_backend.config import Settings


def test_database_url_is_secret_and_postgres_only():
    from fitcheck_backend.storage.database import create_engine, StorageConfigurationError
    settings = Settings(database_url="postgresql://user:private-pass@localhost/fitcheck")
    assert "private-pass" not in repr(settings)
    engine = create_engine(settings)
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.hide_parameters
    engine.dispose()
    with pytest.raises((StorageConfigurationError, ValidationError)) as caught:
        create_engine(Settings(database_url="sqlite:///private-pass"))
    assert "private-pass" not in str(caught.value)
    with pytest.raises(StorageConfigurationError):
        create_engine(Settings())


@pytest.mark.parametrize("url", ["postgresql://user:secret@localhost", "mysql://user:secret@host/db", "postgresql+asyncpg://user:secret@host/db", "postgresql://user:secret@/db", "not-a-url-secret"])
def test_invalid_dsn_does_not_expose_input(url):
    from fitcheck_backend.storage.database import create_engine, StorageConfigurationError
    with pytest.raises((StorageConfigurationError, ValidationError)) as caught:
        create_engine(Settings(database_url=url))
    assert "secret" not in str(caught.value)


def test_import_does_not_connect(monkeypatch):
    import psycopg
    def forbidden(*args, **kwargs):
        pytest.fail("Storage import connected to database")
    monkeypatch.setattr(psycopg, "connect", forbidden)
    importlib.import_module("fitcheck_backend.storage.database")


def test_naive_datetime_rejected():
    from fitcheck_backend.storage.base import UTCDateTime
    value = UTCDateTime()
    with pytest.raises(ValueError, match="timezone"):
        value.process_bind_param(datetime(2026, 1, 1), None)
    aware = datetime(2026, 1, 1, 3, tzinfo=timezone(timedelta(hours=3)))
    assert value.process_bind_param(aware, None) == datetime(2026, 1, 1, tzinfo=UTC)


def test_unit_of_work_rolls_back_and_closes(monkeypatch):
    from fitcheck_backend.storage import database
    events = []
    class Session:
        def commit(self): events.append("commit")
        def rollback(self): events.append("rollback")
        def close(self): events.append("close")
    monkeypatch.setattr(database, "sessionmaker", lambda **kwargs: Session)
    with pytest.raises(RuntimeError, match="failure"):
        with database.unit_of_work(object()):
            raise RuntimeError("failure")
    assert events == ["rollback", "close"]
    events.clear()
    with database.unit_of_work(object()):
        pass
    assert events == ["commit", "close"]

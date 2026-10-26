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


def test_tls_query_secret_never_appears_in_engine_repr():
    from fitcheck_backend.storage.database import create_engine
    engine = create_engine(Settings(database_url="postgresql://user:normal@localhost/db?sslpassword=secret-client-key-passphrase&sslmode=require"))
    try:
        assert "secret-client-key-passphrase" not in repr(engine)
        assert "sslpassword" not in engine.url.query
        assert engine.url.query["sslmode"] == "require"
    finally:
        engine.dispose()


def test_malformed_password_authority_rejected_without_disclosure():
    from fitcheck_backend.storage.database import create_engine, StorageConfigurationError
    with pytest.raises(StorageConfigurationError) as caught:
        create_engine(Settings(database_url="postgresql://user:pass@word@localhost/db"))
    assert "word" not in str(caught.value)


def test_encoded_password_special_characters_are_safe():
    from fitcheck_backend.storage.database import create_engine
    engine = create_engine(Settings(database_url="postgresql://user:pass%40word%3Asecret%2F@localhost/db?sslmode=require"))
    try:
        assert engine.url.password == "pass@word:secret/"
        assert "pass@word" not in repr(engine) and "secret" not in repr(engine)
    finally:
        engine.dispose()


def test_malformed_dsn_cli_is_safe():
    import os
    import subprocess
    import sys
    env = dict(os.environ, FITCHECK_DATABASE_URL="postgresql://user:pass@word@localhost/db")
    result = subprocess.run([sys.executable,"-m","fitcheck_backend.storage.migrate","upgrade"], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert "word" not in result.stderr and "pass" not in result.stderr
    assert "Invalid PostgreSQL database configuration" in result.stderr

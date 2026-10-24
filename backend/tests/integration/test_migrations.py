import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text, inspect
from alembic import command

from fitcheck_backend.config import Settings

pytestmark = pytest.mark.integration


def settings():
    return Settings(database_url=os.environ["FITCHECK_TEST_DATABASE_URL"])


def test_bootstrap_reupgrade_and_drift(engine, storage_factory):
    from fitcheck_backend.storage.migrate import run_migrations, check_schema
    from fitcheck_backend.storage.database import unit_of_work
    with unit_of_work(engine) as session:
        storage_factory(session)
    run_migrations(settings())
    check_schema(settings())
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM analyses")) == 1
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0013"
        assert conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'fitcheck_immutable_%' AND NOT tgisinternal")) == 4


def test_upgrade_existing_data_and_disposable_downgrade(engine):
    from fitcheck_backend.storage.migrate import migration_config, run_migrations
    with engine.begin() as conn:
        command.downgrade(migration_config(conn), "base")
    run_migrations(settings(), revision="0001")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO owners(id, kind, created_at) VALUES ('00000000-0000-0000-0000-000000000001','guest',now())"))
    run_migrations(settings())
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM owners")) == 1
    with engine.begin() as conn:
        command.downgrade(migration_config(conn), "base")
    assert "owners" not in inspect(engine).get_table_names()
    run_migrations(settings())


def test_concurrent_migration_serialized(engine, monkeypatch):
    from fitcheck_backend.storage.migrate import run_migrations
    original = command.upgrade
    def verify_exclusive(config, revision):
        with engine.connect() as observer:
            acquired = observer.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": 0x464954434845434B})
            if acquired:
                observer.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": 0x464954434845434B})
            assert not acquired, "migration does not hold its exclusive advisory lock"
        original(config, revision)
    monkeypatch.setattr(command, "upgrade", verify_exclusive)
    barrier = Barrier(2)
    def run():
        barrier.wait(timeout=10)
        run_migrations(settings())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)


def test_failed_runner_releases_lock(engine):
    from fitcheck_backend.storage.migrate import run_migrations, MIGRATION_LOCK_KEY
    with pytest.raises(Exception):
        run_migrations(settings(), revision="missing_revision")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
    run_migrations(settings())


def test_failed_ddl_rolls_back_and_releases_lock(engine, monkeypatch):
    from fitcheck_backend.storage.migrate import run_migrations
    original = command.upgrade
    def invalid_ddl(config, revision):
        conn = config.attributes["connection"]
        conn.execute(text("CREATE TABLE migration_rollback_probe(id integer)"))
        conn.execute(text("SELECT nonexistent_migration_function()"))
    monkeypatch.setattr(command, "upgrade", invalid_ddl)
    with pytest.raises(Exception):
        run_migrations(settings())
    assert "migration_rollback_probe" not in inspect(engine).get_table_names()
    monkeypatch.setattr(command, "upgrade", original)
    run_migrations(settings())


def test_terminated_connection_releases_lock(engine):
    with engine.connect() as doomed:
        pid = doomed.scalar(text("SELECT pg_backend_pid()"))
        assert doomed.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": 0x464954434845434B})
        doomed.commit()
        with engine.connect() as killer:
            assert killer.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        with pytest.raises(Exception):
            doomed.execute(text("SELECT 1"))
        doomed.rollback()
    from fitcheck_backend.storage.migrate import run_migrations
    run_migrations(settings())

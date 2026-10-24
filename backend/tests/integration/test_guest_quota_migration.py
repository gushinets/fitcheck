from datetime import timedelta
from decimal import Decimal
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.database import unit_of_work

pytestmark=pytest.mark.integration


def test_new_schema_capacity_and_session_digest_uniqueness(engine,storage_factory):
    from fitcheck_backend.storage.guest_access import GuestSessionRow
    from fitcheck_backend.storage.budgets import BudgetWindow
    with unit_of_work(engine) as s:
        owner=storage_factory(s,kind='guest')[0].id
        s.add(GuestSessionRow(owner_id=owner,token_digest='a'*64,expires_at=utcnow()+timedelta(days=1)))
        s.flush()
        with pytest.raises(IntegrityError),s.begin_nested():
            s.add(GuestSessionRow(owner_id=owner,token_digest='a'*64,expires_at=utcnow()+timedelta(days=1)))
            s.flush()
        with pytest.raises(IntegrityError),s.begin_nested():
            s.add(BudgetWindow(scope='owner',scope_key='a',owner_id=owner,window_start=utcnow(),expires_at=utcnow()+timedelta(days=1),
                limit_calls=8,limit_tokens=40000,limit_usd=Decimal('0.02'),calls=1,exposure_tokens=1,exposure_usd=Decimal('0.03')))
            s.flush()
    with engine.connect() as c:
        assert c.scalar(text('select version_num from alembic_version')) == '0013'


def test_upgrade_preserves_existing_result(engine,storage_factory):
    from fitcheck_backend.storage.migrate import migration_config,run_migrations,check_schema
    from fitcheck_backend.config import Settings
    from alembic import command
    from fitcheck_backend.storage.models import AnalysisRecord
    with engine.begin() as c:
        command.downgrade(migration_config(c),'0007')
    with unit_of_work(engine) as s:
        record=storage_factory(s)[4]
        identifier,payload=record.id,record.analysis
    settings=Settings(database_url=engine.url.render_as_string(hide_password=False))
    run_migrations(settings)
    check_schema(settings)
    with unit_of_work(engine) as s:
        assert s.get(AnalysisRecord,identifier).analysis == payload

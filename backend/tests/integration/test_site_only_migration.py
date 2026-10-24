import os
from datetime import timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from fitcheck_backend.config import Settings
from fitcheck_backend.storage.migrate import check_schema, schema_head
from fitcheck_backend.storage.auth_repository import AuthRepository
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.base import utcnow

pytestmark = pytest.mark.integration


def test_clean_initial_schema_includes_auth_and_payload_protection(engine):
    assert schema_head() == '0013'
    columns = {column['name'] for column in inspect(engine).get_columns('auth_tokens')}
    assert columns == {'id', 'user_id', 'purpose', 'token_digest', 'expires_at', 'consumed_at', 'created_at'}
    with engine.connect() as c:
        assert c.scalar(text('SELECT version_num FROM alembic_version')) == '0013'
        assert c.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'fitcheck_%' AND NOT tgisinternal")) == 5
    assert 'auth_rate_buckets' in inspect(engine).get_table_names()
    check_schema(Settings(database_url=os.environ['FITCHECK_TEST_DATABASE_URL']))


@pytest.mark.parametrize('kind,csrf', [('invalid', 'c' * 64), ('web', None)])
def test_schema_rejects_non_website_sessions_and_missing_csrf(engine, kind, csrf):
    with pytest.raises(IntegrityError):
        with unit_of_work(engine) as session:
            repo = AuthRepository(session)
            user = repo.create_user('a@example.com', 'hashed')
            repo.create_session(user, kind, 'a' * 64, csrf, utcnow() + timedelta(days=7))


def test_schema_rejects_unknown_token_purpose(engine):
    with pytest.raises(IntegrityError):
        with unit_of_work(engine) as session:
            repo = AuthRepository(session)
            user = repo.create_user('a@example.com', 'hashed')
            repo.create_token(user, 'invalid', 'a' * 64, utcnow() + timedelta(hours=1))

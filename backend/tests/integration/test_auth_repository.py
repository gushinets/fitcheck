from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy.exc import IntegrityError
from fitcheck_backend.storage.auth_repository import AuthRepository
from fitcheck_backend.storage.database import unit_of_work

pytestmark = pytest.mark.integration


def test_repository_expired_revoked_wrong_kind_session(engine):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with unit_of_work(engine) as s:
        r = AuthRepository(s)
        u = r.create_user('a@example.com', 'hashed')
        live = r.create_session(u, 'web', 'a'*64, 'c'*64, now+timedelta(days=7))
        assert r.session_by_digest('a'*64, 'web', now).id == live.id
        assert r.session_by_digest('a'*64, 'extension', now) is None
        assert r.session_by_digest('a'*64, 'web', now+timedelta(days=7)) is None
        r.revoke_sessions(u.id, now)
        assert r.session_by_digest('a'*64, 'web', now) is None


def test_extension_binding_rejects_other_user_session(engine):
    now = datetime.now(timezone.utc)
    with pytest.raises(IntegrityError) as exc:
        with unit_of_work(engine) as s:
            r = AuthRepository(s)
            a, b = r.create_user('a@example.com', 'hash'), r.create_user('b@example.com', 'hash')
            web = r.create_session(a, 'web', 'a'*64, 'c'*64, now+timedelta(days=7))
            r.create_token(b, 'extension_code', 'b'*64, now+timedelta(minutes=2), issued_session_id=web.id, code_challenge='c'*43, redirect_uri='https://'+'a'*32+'.chromiumapp.org/callback')
    assert exc.value.orig.sqlstate == '23503'

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import timedelta
import pytest
from sqlalchemy import select, func, update
from fitcheck_backend.auth.errors import AuthError
from fitcheck_backend.auth.service import AuthService
from fitcheck_backend.storage.models import User, AuthSession, AuthToken
from fitcheck_backend.storage.database import unit_of_work

pytestmark = pytest.mark.integration
PASSWORD = 'correct horse battery'


def test_registration_and_login_store_only_hashes(auth_components):
    a = auth_components
    issued = a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    assert not issued.principal.email_verified
    assert issued.expires_at == a.now[0] + timedelta(days=7)
    assert len(a.mailer.messages) == 1
    with unit_of_work(a.engine) as s:
        user = s.scalar(select(User))
        assert user.password_hash.startswith('$argon2id$') and PASSWORD not in user.password_hash
        assert s.scalar(select(AuthSession.token_digest)) != issued.token
        assert s.scalar(select(AuthToken.token_digest)) != a.mailer.messages[0].token
    assert a.service.session(issued.token).csrf_token == issued.csrf_token


def test_login_unknown_and_wrong_password_equal_error(auth_components):
    a = auth_components
    a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    for email in ['a@example.com', 'missing@example.com']:
        with pytest.raises(AuthError) as exc:
            a.service.login(email, 'wrong', '192.0.2.1')
        assert exc.value.code == 'invalid_credentials'


def test_login_rotates_browser_session_not_other_device(auth_components):
    a = auth_components
    first = a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    second = a.service.login('a@example.com', PASSWORD, '192.0.2.2')
    third = a.service.login('a@example.com', PASSWORD, '192.0.2.1', old_session_token=first.token)
    assert third.token != first.token and third.csrf_token != first.csrf_token
    with pytest.raises(AuthError):
        a.service.resolve(first.token, 'web')
    assert a.service.resolve(second.token, 'web').user_id == first.principal.user_id


def test_resolve_reads_current_verification_revocation_and_expiry(auth_components):
    a = auth_components
    issued = a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    with unit_of_work(a.engine) as s:
        s.execute(update(User).values(email_verified_at=a.now[0]))
    assert a.service.resolve(issued.token, 'web').email_verified
    with pytest.raises(AuthError):
        a.service.resolve(issued.token, 'extension')
    a.now[0] += timedelta(days=7)
    with pytest.raises(AuthError):
        a.service.resolve(issued.token, 'web')
    a.now[0] -= timedelta(days=7)
    a.service.logout(issued.principal)
    with pytest.raises(AuthError):
        a.service.resolve(issued.token, 'web')


def test_reset_hash_change_during_login_rejects_stale_password(auth_components, monkeypatch):
    a = auth_components
    a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    checked, release = Event(), Event()
    original = a.passwords.verify
    def paused(encoded, password):
        result = original(encoded, password)
        checked.set()
        assert release.wait(5)
        return result
    replacement = a.passwords.hash('changed password 123')
    monkeypatch.setattr(a.passwords, 'verify', paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(a.service.login, 'a@example.com', PASSWORD, '192.0.2.1')
        try:
            assert checked.wait(5)
            with unit_of_work(a.engine) as s:
                s.execute(update(User).values(password_hash=replacement))
                s.execute(update(AuthSession).values(revoked_at=a.now[0]))
        finally:
            release.set()
        with pytest.raises(AuthError) as exc:
            result.result(5)
        assert exc.value.code == 'invalid_credentials'
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.revoked_at.is_(None))) == 0


def test_disabled_mail_registration_has_no_identity_side_effects(auth_components):
    a = auth_components
    a.mailer.enabled = False
    with pytest.raises(AuthError) as exc:
        a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    assert exc.value.code == 'email_unavailable'
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(User)) == 0

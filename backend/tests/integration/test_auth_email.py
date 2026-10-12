from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from dataclasses import replace
import pytest
from sqlalchemy import select, func, update
from fitcheck_backend.auth.email_service import EmailAuthService
from fitcheck_backend.auth.errors import AuthError
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import User, AuthToken, AuthSession

pytestmark = pytest.mark.integration
PASSWORD = 'correct horse battery'


def email_service(a):
    return EmailAuthService(a.engine, a.crypto, a.passwords, a.limiter, a.mailer, a.clock)


def test_registration_mail_failure_recovers_by_login_and_resend(auth_components):
    a = auth_components
    a.mailer.fail = True
    with pytest.raises(AuthError) as exc:
        a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    assert exc.value.code == 'email_unavailable'
    a.mailer.fail = False
    logged = a.service.login('a@example.com', PASSWORD, '192.0.2.1')
    service = email_service(a)
    service.request_verification('a@example.com', '192.0.2.1')
    service.verify(logged.principal, a.mailer.messages[-1].token, '192.0.2.1')
    assert a.service.resolve(logged.token, 'web').email_verified


def test_verification_wrong_account_and_two_consumers(auth_components):
    a = auth_components
    first = a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    token = a.mailer.messages[-1].token
    other = a.service.register('b@example.com', PASSWORD, '192.0.2.2')
    service = email_service(a)
    with pytest.raises(AuthError) as exc:
        service.verify(other.principal, token, '192.0.2.2')
    assert exc.value.code == 'invalid_token'
    def consume():
        try:
            service.verify(first.principal, token, '192.0.2.1')
            return True
        except AuthError as exc:
            assert exc.code == 'invalid_token'
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: consume(), range(2))) == 1


def test_other_device_verification_requires_login(auth_components):
    a = auth_components
    a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    token = a.mailer.messages[-1].token
    device = a.service.login('a@example.com', PASSWORD, '192.0.2.2')
    service = email_service(a)
    with pytest.raises(AuthError):
        service.verify(replace(device.principal, kind='extension'), token, '192.0.2.2')
    service.verify(device.principal, token, '192.0.2.2')
    assert a.service.resolve(device.token, 'web').email_verified


def test_reset_resend_unknown_and_delivery_failure_share_acceptance(auth_components, caplog):
    a = auth_components
    a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    service = email_service(a)
    a.mailer.fail = True
    assert service.request_reset('a@example.com', '192.0.2.1') is None
    assert service.request_reset('absent@example.com', '192.0.2.1') is None
    assert 'a@example.com' not in caplog.text
    a.mailer.enabled = False
    with unit_of_work(a.engine) as s:
        before = s.scalar(select(func.count()).select_from(AuthToken))
    for email in ['a@example.com', 'absent@example.com']:
        with pytest.raises(AuthError) as exc:
            service.request_verification(email, '192.0.2.1')
        assert exc.value.code == 'email_unavailable'
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(AuthToken)) == before


def test_token_purpose_expiry_replay_and_supersession(auth_components):
    a = auth_components
    issued = a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    verify_token = a.mailer.messages[-1].token
    service = email_service(a)
    with pytest.raises(AuthError):
        service.confirm_reset(verify_token, 'changed password 123', '192.0.2.1')
    service.request_reset('a@example.com', '192.0.2.1')
    first_reset = a.mailer.messages[-1].token
    service.request_reset('a@example.com', '192.0.2.1')
    second_reset = a.mailer.messages[-1].token
    with pytest.raises(AuthError):
        service.confirm_reset(first_reset, 'changed password 123', '192.0.2.1')
    a.now[0] += timedelta(minutes=30)
    with pytest.raises(AuthError):
        service.confirm_reset(second_reset, 'changed password 123', '192.0.2.1')
    a.now[0] += timedelta(hours=23, minutes=30)
    with pytest.raises(AuthError):
        service.verify(issued.principal, verify_token, '192.0.2.1')


def test_reset_revokes_all_sessions_and_codes_without_login(auth_components):
    a = auth_components
    issued = a.service.register('a@example.com', PASSWORD, '192.0.2.1')
    other = a.service.login('a@example.com', PASSWORD, '192.0.2.2')
    with unit_of_work(a.engine) as s:
        s.add(AuthSession(user_id=issued.principal.user_id, kind='extension', token_digest='e'*64, expires_at=a.now[0]+timedelta(hours=1)))
        s.add(AuthToken(user_id=issued.principal.user_id, purpose='extension_code', token_digest='f'*64, code_challenge='a'*43, redirect_uri='https://example.com', issued_session_id=issued.principal.session_id, expires_at=a.now[0]+timedelta(minutes=2)))
    service = email_service(a)
    service.request_reset('a@example.com', '192.0.2.1')
    token = a.mailer.messages[-1].token
    service.confirm_reset(token, 'changed password 123', '192.0.2.1')
    with pytest.raises(AuthError):
        service.confirm_reset(token, 'changed password 123', '192.0.2.1')
    for raw in [issued.token, other.token]:
        with pytest.raises(AuthError): a.service.resolve(raw, 'web')
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.revoked_at.is_(None))) == 0
        assert s.scalar(select(func.count()).select_from(AuthToken).where(AuthToken.purpose=='extension_code', AuthToken.consumed_at.is_(None))) == 0
    with pytest.raises(AuthError): a.service.login('a@example.com', PASSWORD, '192.0.2.1')
    assert a.service.login('a@example.com', 'changed password 123', '192.0.2.1').principal.user_id == issued.principal.user_id

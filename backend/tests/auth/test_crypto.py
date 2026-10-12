import base64
from datetime import datetime, timedelta, timezone

from fitcheck_backend.auth.crypto import AuthCrypto


def test_token_digest_does_not_store_raw():
    c = AuthCrypto(b'x' * 32, lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    a, b = c.new_token(), c.new_token()
    assert a != b
    assert len(base64.urlsafe_b64decode(a + '=')) == 32
    assert len(c.digest(a)) == 64 and a not in c.digest(a)
    assert c.digest('abc') == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'


def test_bootstrap_expiry_and_purpose_separation():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    c = AuthCrypto(b'x' * 32, lambda: now[0])
    cookie, csrf = c.issue_bootstrap()
    assert c.verify_bootstrap(cookie, csrf)
    assert not c.verify_bootstrap(cookie, c.session_csrf(cookie))
    assert not c.verify_bootstrap(cookie + 'x', csrf)
    assert not c.verify_bootstrap(cookie, 'wrong')
    assert c.subject_digest('email', 'abc') != c.subject_digest('ip', 'abc')
    now[0] += timedelta(seconds=899)
    assert c.verify_bootstrap(cookie, csrf)
    now[0] += timedelta(seconds=1)
    assert not c.verify_bootstrap(cookie, csrf)


def test_malformed_bootstrap_is_rejected():
    c = AuthCrypto(b'x' * 32, lambda: datetime.now(timezone.utc))
    for value in ['', 'v1.0.bad.bad', 'x' * 10000, '\x00', 'v1.-1.a.b']:
        assert not c.verify_bootstrap(value, 'a')

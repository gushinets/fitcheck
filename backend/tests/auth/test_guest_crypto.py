from datetime import datetime,UTC
from fitcheck_backend.auth.crypto import AuthCrypto
from fitcheck_backend.guests.sessions import GuestSessions


def test_guest_csrf_has_independent_scope_and_token_binding():
    crypto=AuthCrypto(b'x'*32,lambda:datetime(2026,1,1,tzinfo=UTC))
    guests=GuestSessions(None,crypto,None,None,None)
    token=crypto.new_token()
    assert guests.csrf(token)!=crypto.session_csrf(token)
    assert guests.csrf(token)!=guests.csrf(crypto.new_token())
    assert len(guests.csrf(token))==43

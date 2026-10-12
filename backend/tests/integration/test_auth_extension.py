from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import pytest
from fitcheck_backend.auth.crypto import b64
from fitcheck_backend.auth.extension_service import ExtensionAuthService
from fitcheck_backend.auth.email_service import EmailAuthService
from fitcheck_backend.auth.errors import AuthError

pytestmark = pytest.mark.integration
REDIRECT = 'https://'+'a'*32+'.chromiumapp.org/callback'
VERIFIER = 'v'*43
CHALLENGE = b64(hashlib.sha256(VERIFIER.encode()).digest())


def verified(a):
    issued = a.service.register('a@example.com', 'correct horse battery', '192.0.2.1')
    EmailAuthService(a.engine,a.crypto,a.passwords,a.limiter,a.mailer,a.clock).verify(issued.principal,a.mailer.messages[-1].token,'192.0.2.1')
    return a.service.resolve(issued.token,'web')


def test_pkce_exact_redirect_verifier_state_and_replay(auth_components):
    a=auth_components
    principal=verified(a)
    service=ExtensionAuthService(a.engine,a.crypto,a.limiter,a.clock,(REDIRECT,))
    code=service.authorize(principal,REDIRECT,CHALLENGE,'original-state')
    assert code.state=='original-state' and code.expires_at==a.now[0]+timedelta(minutes=2)
    for verifier,redirect in [('wrong'*9,REDIRECT),(VERIFIER,REDIRECT+'?evil=1')]:
        with pytest.raises(AuthError): service.exchange(code.value,verifier,redirect,'192.0.2.1')
    issued=service.exchange(code.value,VERIFIER,REDIRECT,'192.0.2.1')
    assert issued.expires_at==a.now[0]+timedelta(hours=1) and issued.csrf_token is None
    assert a.service.resolve(issued.token,'extension').user_id==principal.user_id
    with pytest.raises(AuthError): service.exchange(code.value,VERIFIER,REDIRECT,'192.0.2.1')
    for redirect in [REDIRECT+'#fragment',REDIRECT.replace('a'*32,'b'*32)]:
        with pytest.raises(AuthError): service.authorize(principal,redirect,CHALLENGE,'state')
    service.revoke(issued.principal)
    with pytest.raises(AuthError): a.service.resolve(issued.token,'extension')


def test_pkce_code_bound_to_live_issuing_session(auth_components):
    a=auth_components
    pending=a.service.register('pending@example.com','correct horse battery','192.0.2.2')
    service=ExtensionAuthService(a.engine,a.crypto,a.limiter,a.clock,(REDIRECT,))
    with pytest.raises(AuthError): service.authorize(pending.principal,REDIRECT,CHALLENGE,'state')
    principal=verified(a)
    code=service.authorize(principal,REDIRECT,CHALLENGE,'state')
    a.service.logout(principal)
    with pytest.raises(AuthError): service.exchange(code.value,VERIFIER,REDIRECT,'192.0.2.1')
    fresh=a.service.login('a@example.com','correct horse battery','192.0.2.1')
    code=service.authorize(fresh.principal,REDIRECT,CHALLENGE,'state')
    def exchange():
        try:
            service.exchange(code.value,VERIFIER,REDIRECT,'192.0.2.1');return True
        except AuthError as exc:
            assert exc.code=='invalid_token';return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _:exchange(),range(2)))==1
    code=service.authorize(fresh.principal,REDIRECT,CHALLENGE,'state')
    a.now[0]+=timedelta(minutes=2)
    with pytest.raises(AuthError): service.exchange(code.value,VERIFIER,REDIRECT,'192.0.2.1')

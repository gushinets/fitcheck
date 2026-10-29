import asyncio
import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fitcheck_backend.api.dependencies import client_ip
from fitcheck_backend.config import Settings


@pytest.mark.parametrize('peer,trusted,forwarded,want', [
    ('192.0.2.1', [], '203.0.113.5', '192.0.2.1'),
    ('192.0.2.1', ['127.0.0.1'], '203.0.113.5', '192.0.2.1'),
    ('127.0.0.1', ['127.0.0.1'], '203.0.113.5', '203.0.113.5'),
    ('127.0.0.1', ['127.0.0.1'], '198.51.100.9, 203.0.113.5', '203.0.113.5'),
    ('127.0.0.1', ['127.0.0.1'], '2001:db8::5', '2001:db8::5'),
    ('127.0.0.1', ['127.0.0.1'], '203.0.113.6', '203.0.113.6'),
])
def test_proxy_headers_cannot_override_untrusted_peer(peer, trusted, forwarded, want):
    async def app(scope,receive,send):
        assert client_ip(Request(scope))==scope['expected']
    async def check():
        scope={'type':'http','client':(peer,1234),'headers':[(b'x-forwarded-for',forwarded.encode())],'expected':want}
        await ProxyHeadersMiddleware(app,trusted_hosts=trusted)(scope,None,None)
    asyncio.run(check())


def test_uvicorn_only_enables_explicit_proxy_trust(monkeypatch):
    import fitcheck_backend.__main__ as main
    called=[]
    monkeypatch.setattr(main.uvicorn,'run',lambda app,**kwargs:called.append(kwargs))
    for proxies in [[],['127.0.0.1','10.0.0.0/24']]:
        s=Settings(trusted_proxy_ips=proxies)
        monkeypatch.setattr(main,'Settings',lambda:s)
        main.main()
    assert called[0]['proxy_headers'] is False
    assert called[1]['proxy_headers'] is True and called[1]['forwarded_allow_ips']=='127.0.0.1,10.0.0.0/24'

import asyncio
import json
from urllib.request import getproxies_environment

import httpx
import pytest
from fitcheck_backend.config import Settings


def test_key_configuration_is_optional_and_redacted():
    assert Settings().open_ai_key is None
    settings = Settings(open_ai_key='private-test-key')
    assert 'private-test-key' not in repr(settings)


@pytest.mark.parametrize('environment,proxied', [
    ({}, False),
    ({'HTTPS_PROXY': 'http://proxy.test:3128'}, True),
    ({'ALL_PROXY': 'http://proxy.test:3128'}, True),
    ({'HTTPS_PROXY': 'http://proxy.test:3128', 'NO_PROXY': 'api.openai.com'}, False),
])
def test_adapter_routes_through_environment_proxy_without_transport_retries(monkeypatch, environment, proxied):
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    # Ignore machine-wide Windows registry proxies; exercise environment routing only.
    monkeypatch.setattr('httpx._utils.getproxies', getproxies_environment)
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    async def run():
        adapter = LiteLlmAdapter('test-key')
        try:
            transport = adapter.client._transport_for_url(httpx.URL('https://api.openai.com/v1/chat/completions'))
            assert (transport is not adapter.client._transport) == proxied
            assert transport._pool._retries == 0
        finally:
            await adapter.aclose()
    asyncio.run(run())


def test_explicit_test_transport_bypasses_environment_proxy(monkeypatch):
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.test:3128')
    transport = httpx.MockTransport(lambda _: pytest.fail('Unexpected HTTP request'))
    async def run():
        adapter = LiteLlmAdapter('test-key', transport=transport)
        try:
            assert adapter.client._transport_for_url(httpx.URL('https://api.openai.com/v1/chat/completions')) is transport
        finally:
            await adapter.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('status,code', [(401,'upstream'),(429,'rate_limit'),(503,'upstream'),(422,'upstream')])
def test_real_sdk_does_not_retry_one_physical_request(status,code):
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    from fitcheck_backend.llm.policy import analysis_policy
    from fitcheck_backend.llm.errors import ProviderFailure
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(status,json={'error':{'message':'private-key and user content','type':'error'}})
    async def run():
        adapter=LiteLlmAdapter('test-key',transport=httpx.MockTransport(handler))
        try:
            await adapter.complete(messages=[{'role':'user','content':'hello'}],policy=analysis_policy(),max_tokens=1200,timeout=2)
        finally: await adapter.aclose()
    with pytest.raises(ProviderFailure) as result: asyncio.run(run())
    assert result.value.code==code and 'private' not in str(result.value)
    assert len(requests)==1


def test_real_sdk_success_usage_and_close():
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    from fitcheck_backend.llm.policy import analysis_policy
    requests=[]
    def handler(request):
        body=json.loads(request.content)
        requests.append(body)
        assert request.url.host=='api.openai.com'
        assert body['model']=='gpt-6-luna' and body['response_format']=={'type':'json_object'}
        assert body['reasoning_effort']=='medium' and body['max_completion_tokens']==1200
        return httpx.Response(200,json={'id':'test','object':'chat.completion','created':1,'model':'gpt-6-luna',
            'choices':[{'index':0,'message':{'role':'assistant','content':'{"ok":true}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':12,'completion_tokens':4,'total_tokens':16}})
    async def run():
        adapter=LiteLlmAdapter('test-key',transport=httpx.MockTransport(handler))
        try:
            result=await adapter.complete(messages=[{'role':'user','content':'hello'}],policy=analysis_policy(),max_tokens=1200,timeout=2)
            assert result.content=='{"ok":true}' and result.input_tokens==12 and result.output_tokens==4
            assert result.cost is None or result.cost>=0
        finally: await adapter.aclose()
        assert adapter.client.is_closed
    asyncio.run(run())
    assert len(requests)==1


@pytest.mark.parametrize('status',[429,503])
def test_real_sdk_preserves_retry_after_at_http_boundary(status):
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    from fitcheck_backend.llm.policy import analysis_policy
    from fitcheck_backend.llm.errors import ProviderFailure
    def handler(request):
        return httpx.Response(status,headers={'Retry-After':'3'},json={'error':{'message':'retry later'}})
    async def run():
        adapter=LiteLlmAdapter('test-key',transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(ProviderFailure) as result:
                await adapter.complete(messages=[{'role':'user','content':'hello'}],policy=analysis_policy(),max_tokens=1200,timeout=2)
            assert result.value.retry_after==3 and result.value.retryable
        finally: await adapter.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('deadline,want_calls,want_delay',[(60,2,[3]),(1,1,[])])
def test_real_sdk_gateway_respects_wait_and_remaining_deadline(deadline,want_calls,want_delay):
    from dataclasses import replace
    from llm_fakes import components,complete
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    from fitcheck_backend.llm.policy import analysis_policy
    from fitcheck_backend.llm.errors import LlmError
    requests,delays,now=[],[],[0.0]
    def handler(request):
        requests.append(request)
        if len(requests)==1:
            return httpx.Response(429,headers={'Retry-After':'3'},json={'error':{'message':'retry later'}})
        return httpx.Response(200,json={'id':'test','object':'chat.completion','created':1,'model':'gpt-6-luna',
            'choices':[{'index':0,'message':{'role':'assistant','content':'{}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}})
    async def sleep(delay): delays.append(delay);now[0]+=delay
    gateway,context,ledger,_=components([],policy=replace(analysis_policy(),deadline_seconds=deadline),clock=lambda:now[0],sleeper=sleep)
    async def run():
        adapter=LiteLlmAdapter('test-key',transport=httpx.MockTransport(handler))
        gateway.adapter=adapter
        try:
            if deadline==1:
                with pytest.raises(LlmError) as result: await complete(gateway,context)
                assert result.value.code=='rate_limit'
            else:
                result=await complete(gateway,context)
                assert result.reply.content=='{}'
        finally: await adapter.aclose()
    asyncio.run(run())
    assert len(requests)==len(ledger.rows)==want_calls and delays==want_delay

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from fitcheck_backend.config import Settings
from fitcheck_backend.llm.policy import analysis_policy, suggestion_policy


def test_openai_aliases_and_invalid_model_fail_safe(monkeypatch):
    monkeypatch.setenv('OPEN_AI_KEY', 'private-test-key')
    monkeypatch.setenv('OPEN_AI_MODEL', 'gpt-6-luna')
    settings = Settings()
    assert settings.open_ai_key.get_secret_value() == 'private-test-key'
    assert settings.open_ai_model == 'gpt-6-luna'
    assert 'private-test-key' not in repr(settings)
    for model in ['gpt-6.1-luna', 'openai/gpt-6-luna', 'gpt-6-luna ', 'deepseek-v4-flash', '']:
        monkeypatch.setenv('OPEN_AI_MODEL', model)
        with pytest.raises(ValidationError):
            Settings()
        with pytest.raises(ValueError):
            analysis_policy(model)
        with pytest.raises(ValueError):
            suggestion_policy(model)


def response():
    return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1,
        'model': 'gpt-6-luna', 'choices': [{'index': 0, 'message': {'role': 'assistant',
            'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 12, 'completion_tokens': 4, 'total_tokens': 16}})


@pytest.mark.parametrize('policy,cap', [(analysis_policy, 1200), (analysis_policy, 1000), (suggestion_policy, 500)])
def test_adapter_outbound_exact_host_path_reasoning_none_and_max_completion_tokens(policy, cap):
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == 'https://api.openai.com/v1/chat/completions'
        body = json.loads(request.content)
        assert body['model'] == 'gpt-6-luna'
        assert body['reasoning_effort'] == 'none'
        assert body['max_completion_tokens'] == cap
        assert body['response_format'] == {'type': 'json_object'}
        # Validate the serialized request from the installed LiteLLM/OpenAI SDKs:
        # unknown kwargs otherwise become provider body fields (e.g. no_log).
        assert set(body) == {'model', 'messages', 'reasoning_effort',
            'max_completion_tokens', 'response_format', 'service_tier'}
        assert not {'temperature', 'thinking', 'max_tokens'} & body.keys()
        return response()
    async def run():
        adapter = LiteLlmAdapter('test-key', transport=httpx.MockTransport(handler))
        try:
            reply = await adapter.complete(messages=[{'role': 'user', 'content': 'Return JSON'}],
                policy=policy(), max_tokens=cap, timeout=2)
            assert (reply.content, reply.input_tokens, reply.output_tokens) == ('{"ok":true}', 12, 4)
        finally:
            await adapter.aclose()
        assert adapter.client.is_closed
    asyncio.run(run())
    assert len(requests) == 1


def test_concurrent_calls_have_independent_send_counters():
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    requests = []
    async def handler(request):
        requests.append(request)
        await asyncio.sleep(0)
        return response()
    async def run():
        adapter = LiteLlmAdapter('test-key', transport=httpx.MockTransport(handler))
        try:
            replies = await asyncio.gather(*(adapter.complete(messages=[{'role': 'user', 'content': 'JSON'}],
                policy=analysis_policy(), max_tokens=1200, timeout=2) for _ in range(3)))
            assert len(replies) == 3
        finally:
            await adapter.aclose()
    asyncio.run(run())
    assert len(requests) == 3


def test_sdk_child_tasks_share_one_send_counter(monkeypatch):
    from fitcheck_backend.llm import litellm_adapter
    from fitcheck_backend.llm.errors import ProviderFailure
    requests = []
    def handler(request):
        requests.append(request)
        return response()
    async def run():
        adapter = litellm_adapter.LiteLlmAdapter('test-key', transport=httpx.MockTransport(handler))
        async def hidden_sends(**kwargs):
            outcomes = await asyncio.gather(*(adapter.client.post('https://api.openai.com/v1/chat/completions')
                for _ in range(2)), return_exceptions=True)
            assert sum(isinstance(value, RuntimeError) for value in outcomes) == 1
            raise RuntimeError('Hidden SDK sends blocked')
        monkeypatch.setattr(litellm_adapter.litellm, 'acompletion', hidden_sends)
        try:
            with pytest.raises(ProviderFailure):
                await adapter.complete(messages=[], policy=analysis_policy(), max_tokens=1200, timeout=2)
        finally:
            await adapter.aclose()
    asyncio.run(run())
    assert len(requests) == 1


def test_unregistered_policy_rejected_before_http():
    from dataclasses import replace
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    from fitcheck_backend.llm.errors import LlmError
    async def run():
        adapter = LiteLlmAdapter('test-key', transport=httpx.MockTransport(lambda _: pytest.fail('HTTP escaped policy')))
        try:
            for override in [{'model': 'unknown'}, {'provider': 'deepseek'},
                    {'gateway_model': 'openai/other'}, {'policy_version': 'fitcheck.llm.policy.v1'}]:
                with pytest.raises(LlmError) as error:
                    await adapter.complete(messages=[], policy=replace(analysis_policy(), **override), max_tokens=1200, timeout=2)
                assert error.value.code == 'service_unavailable'
        finally:
            await adapter.aclose()
    asyncio.run(run())


def test_redirect_and_second_send_blocked():
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    from fitcheck_backend.llm.errors import ProviderFailure
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={'location': 'https://api.openai.com/v1/chat/completions'})
    async def run():
        adapter = LiteLlmAdapter('test-key', transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(ProviderFailure):
                await adapter.complete(messages=[{'role': 'user', 'content': 'JSON'}],
                    policy=analysis_policy(), max_tokens=1200, timeout=2)
            token = adapter._sends.set([0])
            try:
                await adapter.client.post('https://api.openai.com/v1/chat/completions')
                with pytest.raises(RuntimeError, match='retry blocked'):
                    await adapter.client.post('https://api.openai.com/v1/chat/completions')
            finally:
                adapter._sends.reset(token)
        finally:
            await adapter.aclose()
    asyncio.run(run())
    assert len(requests) == 2


@pytest.mark.parametrize('url', ['http://api.openai.com/v1/chat/completions',
    'https://api.openai.com:444/v1/chat/completions', 'https://api.openai.com/v1/responses',
    'https://api.openai.com/v1/chat/completions?q=1', 'https://user@api.openai.com/v1/chat/completions',
    'https://api.deepseek.com/v1/chat/completions'])
def test_invalid_destination_blocked_before_transport(url):
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    async def run():
        adapter = LiteLlmAdapter('test-key', transport=httpx.MockTransport(lambda _: pytest.fail('HTTP escaped guard')))
        token = adapter._sends.set([0])
        try:
            with pytest.raises(RuntimeError, match='destination blocked'):
                await adapter.client.post(url)
        finally:
            adapter._sends.reset(token)
            await adapter.aclose()
    asyncio.run(run())



def test_adapter_prices_actual_sdk_cache_write_usage_and_actual_tier():
    from decimal import Decimal
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    async def run(tier):
        def handler(request):
            value=json.loads(response().content)
            value['service_tier']=tier
            value['usage'].update(prompt_tokens=1,completion_tokens=0,total_tokens=1,
                prompt_tokens_details={'cached_tokens':0,'cache_write_tokens':1},
                completion_tokens_details={'reasoning_tokens':0})
            return httpx.Response(200,json=value)
        adapter=LiteLlmAdapter('fake-key',transport=httpx.MockTransport(handler))
        try:
            return await adapter.complete(messages=[{'role':'user','content':'JSON'}],policy=analysis_policy(),max_tokens=12,timeout=2)
        finally:
            await adapter.aclose()
    result=asyncio.run(run('default'))
    assert result.cost==Decimal('0.000000125') and result.cost_basis=='estimated'
    assert result.cached_input_tokens==0 and result.cache_write_tokens==1 and result.reasoning_tokens==0
    assert result.service_tier=='default' and result.rate_version=='openai.luna.2026-10-16'
    result=asyncio.run(run('flex'))
    assert result.cost is None and result.cost_reason=='unsupported_service_tier'

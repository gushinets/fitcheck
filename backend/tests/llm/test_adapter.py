import asyncio
import json

import httpx
import pytest
from fitcheck_backend.config import Settings


def test_key_configuration_is_optional_and_redacted():
    assert Settings().deepseek_api_key is None
    settings = Settings(deepseek_api_key='private-test-key')
    assert 'private-test-key' not in repr(settings)


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
        assert request.url.host=='api.deepseek.com'
        assert body['model']=='deepseek-v4-flash' and body['response_format']=={'type':'json_object'}
        assert body['thinking']=={'type':'disabled'} and body['max_tokens']==1200
        return httpx.Response(200,json={'id':'test','object':'chat.completion','created':1,'model':'deepseek-v4-flash',
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

import asyncio
from uuid import uuid4
import pytest
from fitcheck_backend.config import Settings


def test_missing_key_fails_safely_without_database_or_provider():
    from fitcheck_backend.llm.runtime import LlmRuntime
    from fitcheck_backend.llm.errors import LlmError
    async def run():
        runtime=LlmRuntime(Settings(),None)
        try:
            with pytest.raises(LlmError) as result:
                await runtime.suggestions.suggest(owner_id=uuid4(),specialization='Backend developer',locale='en')
            assert result.value.code=='service_unavailable'
            assert runtime.gateway.adapter.client.is_closed is False
        finally: await runtime.aclose()
        assert runtime.gateway.adapter.client.is_closed is True
    asyncio.run(run())


def test_runtime_reuses_adapters_models_and_services():
    from fitcheck_backend.llm.runtime import LlmRuntime
    async def run():
        runtime=LlmRuntime(Settings(),None)
        try:
            assert runtime.analysis.executor.structured.gateway is runtime.gateway
            assert runtime.suggestions.executor.structured.gateway is runtime.gateway
        finally: await runtime.aclose()
    asyncio.run(run())


def test_concurrent_cached_agent_runs_do_not_mix_input_or_owner():
    import json
    from dataclasses import replace
    from llm_fakes import components
    from fitcheck_backend.llm.policy import suggestion_policy
    from fitcheck_backend.llm.types import ProviderReply,CallBudget
    from fitcheck_backend.skill_suggestions.executor import SuggestionExecutor
    import time
    gateway,first,ledger,adapter=components([],policy=suggestion_policy())
    second=replace(first,owner_id=uuid4(),operation_id=uuid4(),
        budget=CallBudget(4,time.monotonic()+60,time.monotonic))
    async def fetch(**kwargs):
        request=json.loads(next(m['content'] for m in kwargs['messages'] if m['role']=='user'))
        await asyncio.sleep(0)
        skill='React' if request['specialization']=='Frontend' else 'Python'
        return ProviderReply(json.dumps({'skills':[skill]}),2,1,None,None)
    adapter.complete=fetch
    executor=SuggestionExecutor(gateway)
    async def run():
        return await asyncio.gather(executor.run(first,'Frontend','en'),executor.run(second,'Backend','ru'))
    assert asyncio.run(run())==[['React'],['Python']]
    assert {r['attempt'].owner_id for r in ledger.rows.values()}=={first.owner_id,second.owner_id}

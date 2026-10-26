import asyncio
from dataclasses import replace
from decimal import Decimal
import pytest
from llm_fakes import components,reply,complete


def test_transport_retry_creates_two_physical_rows():
    from fitcheck_backend.llm.errors import ProviderFailure
    gateway, context, ledger, adapter = components([ProviderFailure('upstream',retryable=True),reply()])
    result = asyncio.run(complete(gateway,context))
    assert result.reply.content == '{"ok":true}' and len(ledger.rows) == 2
    assert [v['state'] for v in ledger.rows.values()] == ['failed','succeeded']
    assert [v['attempt'].transport_attempt for v in ledger.rows.values()] == [1,2]
    assert list(ledger.rows.values())[1]['input_tokens'] == 12
    assert all(call['timeout'] <= 45 for call in adapter.calls)


@pytest.mark.parametrize('code,retryable,count', [('upstream',False,1),('timeout',True,2),('rate_limit',True,2),('upstream',True,2)])
def test_transport_exhaustion(code,retryable,count):
    from fitcheck_backend.llm.errors import ProviderFailure,LlmError
    gateway, context, ledger, _ = components([ProviderFailure(code,retryable=retryable)]*2)
    with pytest.raises(LlmError) as result: asyncio.run(complete(gateway,context))
    assert result.value.code == code and len(ledger.rows) == count
    assert all(v['state']=='failed' for v in ledger.rows.values())


@pytest.mark.parametrize('where', ['start','finish'])
def test_ledger_failure_stops_provider_and_hides_exception(where):
    from fitcheck_backend.llm.errors import LlmError
    gateway, context, ledger, adapter = components([reply(),reply()])
    setattr(ledger,'fail_'+where,True)
    with pytest.raises(LlmError) as result: asyncio.run(complete(gateway,context))
    assert result.value.code == 'service_unavailable' and 'secret' not in str(result.value)
    assert len(adapter.calls) == (0 if where=='start' else 1)


def test_retry_after_does_not_cross_deadline():
    from fitcheck_backend.llm.errors import ProviderFailure,LlmError
    from fitcheck_backend.llm.policy import analysis_policy
    now=[0.0]
    async def sleep(delay): now[0]+=delay
    gateway, context, ledger, _ = components([ProviderFailure('rate_limit',retryable=True,retry_after=100),reply()],
        policy=replace(analysis_policy(),deadline_seconds=1),clock=lambda:now[0],sleeper=sleep)
    with pytest.raises(LlmError) as result: asyncio.run(complete(gateway,context))
    assert result.value.code in {'rate_limit','timeout'} and len(ledger.rows)==1 and now[0]<=1


def test_hard_cap_stops_before_next_physical_call():
    from fitcheck_backend.llm.errors import LlmError
    from fitcheck_backend.llm.policy import analysis_policy
    gateway, context, ledger, _ = components([reply(),reply()], policy=replace(analysis_policy(),max_calls=1))
    async def run():
        await complete(gateway,context)
        await complete(gateway,context)
    with pytest.raises(LlmError): asyncio.run(run())
    assert len(ledger.rows)==1


def test_invalid_output_keeps_actual_usage_and_latency():
    gateway, context, ledger, _ = components([reply()])
    async def run():
        result=await complete(gateway,context)
        gateway.reject(result)
    asyncio.run(run())
    row = next(iter(ledger.rows.values()))
    assert row['state']=='failed' and row['error_code']=='invalid_output'
    assert row['input_tokens']==12 and row['cost']==Decimal('0.0001') and row['latency_ms']>=0


def test_unknown_usage_remains_null():
    from fitcheck_backend.llm.types import ProviderReply
    gateway, context, ledger, _ = components([ProviderReply('bad',None,None,None,None)])
    asyncio.run(complete(gateway,context))
    row=next(iter(ledger.rows.values()))
    assert row['input_tokens'] is None and row['cost'] is None and row['currency'] is None


def test_attempt_timeout_cancels_inflight_provider():
    from fitcheck_backend.llm.errors import LlmError
    from fitcheck_backend.llm.policy import analysis_policy
    gateway,context,ledger,adapter=components([],policy=replace(analysis_policy(),attempt_seconds=0.01,transport_attempts=1))
    cancelled=[]
    async def hang(**kwargs):
        try: await asyncio.sleep(1)
        finally: cancelled.append(True)
    adapter.complete=hang
    with pytest.raises(LlmError) as result: asyncio.run(complete(gateway,context))
    assert result.value.code=='timeout' and cancelled==[True]
    assert next(iter(ledger.rows.values()))['state']=='failed'


def test_rejected_attempt_retains_exact_usage_and_rate_provenance():
    from fitcheck_backend.llm.types import ProviderReply
    priced=ProviderReply('{}',1,0,Decimal('0.000000125'),'USD',cached_input_tokens=0,
        cache_write_tokens=1,reasoning_tokens=0,cost_basis='estimated',rate_version='openai.luna.2026-10-16',
        service_tier='default',processing_region='global',response_model='gpt-6-luna')
    gateway,context,ledger,_=components([priced])
    async def run():
        result=await complete(gateway,context)
        gateway.reject(result)
    asyncio.run(run())
    row=next(iter(ledger.rows.values()))
    assert row['state']=='failed' and row['cost']==priced.cost
    for name in ('cached_input_tokens','cache_write_tokens','reasoning_tokens','cost_basis','rate_version','service_tier','processing_region','response_model'):
        assert row[name]==getattr(priced,name)

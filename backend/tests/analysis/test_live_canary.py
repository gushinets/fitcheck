"""Explicit, paid opt-in; never a dependency of deterministic CI."""
import asyncio
import os
from uuid import uuid4
import pytest


@pytest.mark.skipif(os.environ.get('FITCHECK_RUN_LLM_CANARY')!='1' or not os.environ.get('FITCHECK_DEEPSEEK_API_KEY'),
    reason='Live LLM canary requires explicit opt-in and provider key')
def test_live_anonymized_analysis_canary():
    from fitcheck_backend.llm.litellm_adapter import LiteLlmAdapter
    from fitcheck_backend.llm.gateway import ProviderGateway
    from fitcheck_backend.llm.policy import analysis_policy
    from fitcheck_backend.llm.types import OperationContext,CallBudget
    from fitcheck_backend.analysis.executor import AnalysisExecutor
    from analysis_fixtures import input_value
    import time
    # Canary metrics stay in process; persisted accounting is tested on disposable PG.
    class CanaryLedger:
        def __init__(self): self.rows={}
        def start(self,attempt):
            key=uuid4();self.rows[key]={'attempt':attempt}
            return key
        def finish(self,key,**fields): self.rows[key].update(fields)
    async def run():
        adapter=LiteLlmAdapter(os.environ['FITCHECK_DEEPSEEK_API_KEY'])
        policy=analysis_policy()
        context=OperationContext(uuid4(),None,uuid4(),policy,CallBudget(8,time.monotonic()+120,time.monotonic))
        ledger=CanaryLedger()
        try:
            result=await AnalysisExecutor(ProviderGateway(adapter,ledger)).run(context,input_value())
            assert result.status in {'GO','NO_GO'} and result.verdict_threshold==70
            assert len(result.strengths)==len(result.strength_evidence)
            assert 2<=len(ledger.rows)<=8 and all('latency_ms' in row for row in ledger.rows.values())
        finally: await adapter.aclose()
    asyncio.run(run())

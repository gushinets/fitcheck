import asyncio
import pytest
from llm_fakes import components


def test_suggestions_four_call_cap():
    from fitcheck_backend.skill_suggestions.executor import SuggestionExecutor
    from fitcheck_backend.llm.policy import suggestion_policy
    from fitcheck_backend.llm.errors import ProviderFailure,LlmError
    from fitcheck_backend.llm.types import ProviderReply
    fail=ProviderFailure('upstream',retryable=True)
    gateway,context,ledger,_=components([fail,ProviderReply('{"skills":[42]}',3,1,None,None),fail,
        ProviderReply('{"skills":[" Python ","python","FastAPI"]}',3,1,None,None)],policy=suggestion_policy())
    result=asyncio.run(SuggestionExecutor(gateway).run(context,'Backend developer','en'))
    assert result==['Python','FastAPI'] and len(ledger.rows)==4
    assert [r['attempt'].semantic_attempt for r in ledger.rows.values()]==[1,1,2,2]


def test_suggestion_validation_exhaustion():
    from fitcheck_backend.skill_suggestions.executor import SuggestionExecutor
    from fitcheck_backend.llm.policy import suggestion_policy
    from fitcheck_backend.llm.errors import LlmError
    from fitcheck_backend.llm.types import ProviderReply
    gateway,context,ledger,_=components([ProviderReply('{"skills":[42]}',3,1,None,None)]*2,policy=suggestion_policy())
    with pytest.raises(LlmError) as result:
        asyncio.run(SuggestionExecutor(gateway).run(context,'Backend','ru'))
    assert result.value.code=='invalid_output' and len(ledger.rows)==2
    assert all(r['state']=='failed' for r in ledger.rows.values())

from decimal import Decimal
import pytest
from fitcheck_backend.budgets.tokens import upper_call_bounds
from fitcheck_backend.llm.errors import LlmError


def test_unicode_schema_and_framing_have_conservative_bound():
    text='Привет 🧑‍💻'*100
    b=upper_call_bounds(messages=[{'role':'user','content':text}],response_schema={'description':text},model='gpt-6-luna',max_output_tokens=1200)
    assert b.input_tokens>=2*len(text.encode('utf-8'))
    assert b.output_tokens==1200
    assert b.usd==Decimal(b.input_tokens*125+1200*500).scaleb(-9)


@pytest.mark.parametrize('model,text',[('unknown','ok'),('gpt-6-luna','x'*272001)],ids=['unknown-model','oversized-input'])
def test_unsupported_pricing_fails_closed(model,text):
    with pytest.raises(LlmError):upper_call_bounds(messages=[{'role':'user','content':text}],response_schema=None,model=model,max_output_tokens=1200)


def test_budget_rejection_has_no_physical_send():
    import asyncio
    from llm_fakes import components,complete,reply
    from fitcheck_backend.quotas.errors import QuotaError
    gateway,context,ledger,adapter=components([reply()])
    def reject(attempt,*,bounds):raise QuotaError('budget_exceeded')
    ledger.start=reject
    with pytest.raises(LlmError) as error:asyncio.run(complete(gateway,context))
    assert error.value.code=='budget_exceeded'
    assert adapter.calls==[]

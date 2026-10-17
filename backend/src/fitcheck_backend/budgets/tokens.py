"""Conservative text-only request bounds for the pinned provider policy.

A token cannot contain less than one UTF-8 byte. Count serialized bytes,
plus a deliberately generous per-message/template allowance; never use a
language-dependent chars/token average for financial admission.
"""
import json
from decimal import Decimal
from .types import CallBounds
from ..llm.pricing import RATE_VERSION
from ..llm.errors import LlmError


def upper_call_bounds(*,messages,response_schema,model,max_output_tokens):
    if model!='gpt-6-luna' or type(max_output_tokens) is not int or not 1<=max_output_tokens<=100000:
        raise LlmError('budget_exceeded')
    if not isinstance(messages,list) or len(messages)>1000:
        raise LlmError('budget_exceeded')
    for m in messages:
        if (not isinstance(m,dict) or set(m)-{'role','content','name'} or
                m.get('role') not in {'system','developer','user','assistant'} or
                not isinstance(m.get('content'),str)):
            raise LlmError('budget_exceeded')
    encoded=json.dumps({'messages':messages,'response_format':response_schema or {'type':'json_object'}},ensure_ascii=False,separators=(',',':')).encode('utf-8')
    count=len(encoded)+256+64*len(messages)
    if count>272000:raise LlmError('budget_exceeded')
    return CallBounds(count,max_output_tokens,Decimal(count*125+max_output_tokens*500).scaleb(-9),RATE_VERSION)

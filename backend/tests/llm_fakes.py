import asyncio
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest


class Ledger:
    def __init__(self):
        self.rows = {}
        self.fail_start = self.fail_finish = False
    def start(self, attempt):
        if self.fail_start: raise RuntimeError('db key=secret')
        key = uuid4(); self.rows[key] = {'attempt':attempt,'state':'started'}
        return key
    def finish(self, key, **fields):
        if self.fail_finish: raise RuntimeError('db key=secret')
        self.rows[key].update(fields)


class Adapter:
    def __init__(self, values):
        self.values, self.calls = iter(values), []
    def available(self):
        return True
    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.values)
        if isinstance(value, BaseException): raise value
        return value


def components(values, *, policy=None, clock=None, sleeper=None):
    from fitcheck_backend.llm.gateway import ProviderGateway
    from fitcheck_backend.llm.types import OperationContext, CallBudget
    from fitcheck_backend.llm.policy import analysis_policy
    import time
    clock = clock or time.monotonic
    policy = policy or analysis_policy()
    ledger, adapter = Ledger(), Adapter(values)
    context = OperationContext(uuid4(),None,uuid4(),policy,CallBudget(policy.max_calls,clock()+policy.deadline_seconds,clock))
    gateway = ProviderGateway(adapter,ledger,clock=clock, sleep=sleeper or asyncio.sleep)
    return gateway, context, ledger, adapter


def reply():
    from fitcheck_backend.llm.types import ProviderReply
    return ProviderReply('{"ok":true}',12,4,Decimal('0.0001'),'USD')


async def complete(gateway, context):
    return await gateway.complete(context=context,messages=[{'role':'user','content':'data'}],
        semantic_attempt=1,operation='analysis.generate',max_tokens=1200)


import asyncio
from types import SimpleNamespace
from uuid import uuid4
from threading import Event
import pytest
from fitcheck_backend.jobs.types import JobLease


class Queue:
    def __init__(self):
        self.beats = self.claims = self.recoveries = 0
        self.ok = True
    def heartbeat(self,lease): self.beats += 1; return self.ok
    def recover_expired(self): self.recoveries += 1; return 0
    def claim(self): self.claims += 1; return job()


class Publication:
    def __init__(self): self.results = []; self.failures = []
    def succeed_suggestions(self,lease,result): self.results.append(result); return True
    def fail(self,lease,error): self.failures.append(error); return True


class Health:
    def __init__(self): self.ok = False
    def mark(self): self.ok = True
    def clear(self): self.ok = False


def job(): return JobLease(uuid4(),uuid4(),'skill_suggestions',uuid4(),1,{})


def runner(q,executor,pub,**changes):
    from fitcheck_backend.worker.runner import WorkerRunner
    settings = SimpleNamespace(poll_interval=0.01,heartbeat_seconds=0.01,drain_seconds=0.03,**changes)
    return WorkerRunner(q,executor,pub,settings,Health())


def test_heartbeat_runs_during_slow_provider():
    async def run():
        q,pub = Queue(),Publication()
        class Executor:
            async def execute(self,lease):
                while q.beats < 2: await asyncio.sleep(0)
                return ['React']
        value = runner(q,Executor(),pub)
        await asyncio.wait_for(value.process(job()),1)
        assert q.beats >= 2 and pub.results == [['React']]
    asyncio.run(run())


def test_failed_heartbeat_cancels_execution_and_never_publishes():
    async def run():
        q,pub = Queue(),Publication(); q.ok = False
        cancelled = asyncio.Event()
        class Executor:
            async def execute(self,lease):
                try: await asyncio.Event().wait()
                finally: cancelled.set()
        value = runner(q,Executor(),pub)
        await asyncio.wait_for(value.process(job()),1)
        assert cancelled.is_set() and pub.results == [] and pub.failures == []
    asyncio.run(run())


def test_shutdown_stops_claim_and_drains_current_job():
    async def run():
        q,pub = Queue(),Publication()
        class Executor:
            async def execute(self,lease):
                value.request_shutdown()
                await asyncio.sleep(0)
                return ['React']
        value = runner(q,Executor(),pub)
        await asyncio.wait_for(value.run_forever(),1)
        assert q.claims == 1 and pub.results == [['React']]
    asyncio.run(run())


def test_drain_timeout_leaves_recoverable_job():
    async def run():
        q,pub = Queue(),Publication()
        class Executor:
            async def execute(self,lease):
                value.request_shutdown()
                await asyncio.Event().wait()
        value = runner(q,Executor(),pub)
        await asyncio.wait_for(value.run_forever(),1)
        assert q.claims == 1 and pub.results == [] and pub.failures == []
    asyncio.run(run())


def test_recovery_runs_under_continuous_backlog():
    async def run():
        q,pub = Queue(),Publication()
        class Executor:
            async def execute(self,lease):
                if q.claims == 3: value.request_shutdown()
                return ['React']
        value = runner(q,Executor(),pub)
        await asyncio.wait_for(value.run_forever(),1)
        assert q.recoveries == q.claims == 3
    asyncio.run(run())


def test_blocked_db_call_does_not_block_heartbeat_event_loop():
    from llm_fakes import components, reply, complete
    async def run():
        gateway,context,ledger,_ = components([reply()])
        releasing = Event()
        original = ledger.start
        observed = []
        def blocking(attempt):
            observed.append(releasing.wait(timeout=0.2))
            return original(attempt)
        ledger.start = blocking
        async def release():
            await asyncio.sleep(0)
            releasing.set()
        await asyncio.gather(complete(gateway,context),release())
        assert observed == [True]
    asyncio.run(run())

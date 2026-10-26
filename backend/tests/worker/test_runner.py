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
        def blocking(attempt, *, bounds):
            observed.append(releasing.wait(timeout=0.2))
            return original(attempt,bounds=bounds)
        ledger.start = blocking
        async def release():
            await asyncio.sleep(0)
            releasing.set()
        await asyncio.gather(complete(gateway,context),release())
        assert observed == [True]
    asyncio.run(run())


@pytest.mark.parametrize('failed_execution',[False,True])
def test_inflight_failed_heartbeat_prevents_terminal_publication(failed_execution):
    async def run():
        from fitcheck_backend.llm.errors import LlmError
        entered,released,finished = Event(),Event(),Event()
        q,pub = Queue(),Publication()
        def heartbeat(lease):
            entered.set()
            assert released.wait(1)
            finished.set()
            raise RuntimeError('database heartbeat failed')
        q.heartbeat = heartbeat
        class Executor:
            async def execute(self,lease):
                while not entered.is_set(): await asyncio.sleep(0)
                if failed_execution: raise LlmError('timeout')
                return ['React']
        value = runner(q,Executor(),pub)
        task = asyncio.create_task(value.process(job()))
        while not entered.is_set(): await asyncio.sleep(0)
        # Let the execution task finish while DB heartbeat is still pending.
        for _ in range(20): await asyncio.sleep(0)
        released.set()
        await asyncio.wait_for(task,1)
        assert finished.is_set()
        assert pub.results == [] and pub.failures == []
    asyncio.run(run())


def test_cancellation_during_ledger_admission_finalizes_without_http():
    from llm_fakes import components,reply,complete
    async def run():
        gateway,context,ledger,adapter = components([reply()])
        entered,released,settled = Event(),Event(),Event()
        original = ledger.start
        def start(attempt, *, bounds):
            entered.set()
            assert released.wait(1)
            call_id = original(attempt,bounds=bounds)
            settled.set()
            return call_id
        ledger.start = start
        task = asyncio.create_task(complete(gateway,context))
        while not entered.is_set(): await asyncio.sleep(0)
        task.cancel()
        released.set()
        with pytest.raises(asyncio.CancelledError): await task
        # Barrier ensures the physical ledger thread finished before assertions.
        assert await asyncio.to_thread(settled.wait,1)
        assert len(ledger.rows) == 1
        assert [r['state'] for r in ledger.rows.values()] == ['unknown']
        assert adapter.calls == []
    asyncio.run(run())


def test_deadline_during_ledger_admission_settles_before_job_failure():
    from llm_fakes import components,reply,complete
    from fitcheck_backend.llm.errors import LlmError
    async def run():
        gateway,context,ledger,adapter = components([reply()])
        entered,released = Event(),Event()
        original = ledger.start
        def start(attempt, *, bounds):
            entered.set()
            assert released.wait(1)
            return original(attempt,bounds=bounds)
        ledger.start = start
        class Executor:
            task = None
            async def execute(self,lease):
                self.task = asyncio.current_task()
                try:
                    async with asyncio.timeout(0.05): await complete(gateway,context)
                except TimeoutError: raise LlmError('timeout') from None
        executor,pub = Executor(),Publication()
        value = runner(Queue(),executor,pub)
        task = asyncio.create_task(value.process(job()))
        while not entered.is_set() or not executor.task.cancelling(): await asyncio.sleep(0)
        released.set()
        await asyncio.wait_for(task,1)
        assert [r['state'] for r in ledger.rows.values()] == ['unknown']
        assert [error.code for error in pub.failures] == ['timeout']
        assert adapter.calls == []
    asyncio.run(run())


def test_health_io_cannot_block_shutdown_event_loop():
    entered, released = Event(), Event()
    async def run():
        q, pub = Queue(), Publication()
        class Executor:
            async def execute(self, lease): return ['React']
        value = runner(q, Executor(), pub)
        def mark():
            entered.set()
            assert released.wait(2), 'Health I/O blocked the event loop'
        value.health.mark = mark
        task = asyncio.create_task(value.run_forever())
        try:
            while not entered.is_set(): await asyncio.sleep(0)
            value.request_shutdown()
            released.set()
            await asyncio.wait_for(task, 2)
        finally:
            released.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert q.claims == 1
    asyncio.run(run())

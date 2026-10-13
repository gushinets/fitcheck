import asyncio
import logging
from ..api.errors import ErrorBody
from ..jobs.errors import JobError
from ..llm.errors import LlmError

logger = logging.getLogger('fitcheck.worker')


class WorkerRunner:
    def __init__(self,queue,executor,publication,settings,health):
        self.queue,self.executor,self.publication = queue,executor,publication
        self.settings,self.health = settings,health
        self.stopping = asyncio.Event()

    def request_shutdown(self):
        self.stopping.set()

    async def _heartbeat(self,lease):
        while True:
            await asyncio.sleep(self.settings.heartbeat_seconds)
            try:
                if not await asyncio.to_thread(self.queue.heartbeat,lease):
                    self.health.clear(); return
                self.health.mark()
            except Exception:
                self.health.clear(); return

    async def _drain(self):
        await self.stopping.wait()
        await asyncio.sleep(self.settings.drain_seconds)

    async def process(self,lease):
        execution = asyncio.create_task(self.executor.execute(lease))
        heartbeat = asyncio.create_task(self._heartbeat(lease))
        drain = asyncio.create_task(self._drain())
        try:
            done,_ = await asyncio.wait([execution,heartbeat,drain],return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done or drain in done:
                execution.cancel()
                return
            try:
                result = execution.result()
            except (JobError,LlmError) as exc:
                error = ErrorBody(code=exc.code,message=exc.code.replace('_',' ').capitalize(),requestId=str(lease.job_id))
                await asyncio.to_thread(self.publication.fail,lease,error)
            except Exception:
                error = ErrorBody(code='service_unavailable',message='Service unavailable',requestId=str(lease.job_id))
                await asyncio.to_thread(self.publication.fail,lease,error)
            else:
                if heartbeat.done() or drain.done(): return
                if lease.type == 'analysis':
                    await asyncio.to_thread(self.publication.succeed_analysis,lease,result)
                else:
                    await asyncio.to_thread(self.publication.succeed_suggestions,lease,result)
        finally:
            for task in (execution,heartbeat,drain):
                if not task.done(): task.cancel()
            await asyncio.gather(execution,heartbeat,drain,return_exceptions=True)

    async def run_forever(self):
        try:
            while not self.stopping.is_set():
                try:
                    await asyncio.to_thread(self.queue.recover_expired)
                    lease = await asyncio.to_thread(self.queue.claim)
                    self.health.mark()
                    if lease is not None:
                        await self.process(lease)
                        continue
                except Exception:
                    self.health.clear()
                    logger.warning('worker iteration unavailable')
                try:
                    await asyncio.wait_for(self.stopping.wait(),timeout=self.settings.poll_interval)
                except TimeoutError:
                    pass
        finally:
            self.health.clear()

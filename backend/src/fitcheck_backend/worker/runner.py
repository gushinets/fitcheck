import asyncio
import logging
import hashlib
import time
from ..api.errors import ErrorBody
from ..jobs.errors import JobError
from ..llm.errors import LlmError
from sqlalchemy.exc import SQLAlchemyError
from ..storage.import_repository import ImportLeaseLost

logger = logging.getLogger('fitcheck.worker')


class WorkerRunner:
    def __init__(self,queue,executor,publication,settings,health,*,import_executor=None):
        self.queue,self.executor,self.publication = queue,executor,publication
        self.settings,self.health = settings,health
        self.import_executor = import_executor
        self.stopping = asyncio.Event()

    def request_shutdown(self):
        self.stopping.set()

    async def _heartbeat(self,lease,stop):
        while True:
            try:
                await asyncio.wait_for(stop.wait(),timeout=self.settings.heartbeat_seconds)
                return True
            except TimeoutError:
                pass
            try:
                if not await asyncio.to_thread(self.queue.heartbeat,lease):
                    await asyncio.to_thread(self.health.clear); return False
                await asyncio.to_thread(self.health.mark)
            except Exception:
                await asyncio.to_thread(self.health.clear); return False

    async def _drain(self):
        await self.stopping.wait()
        await asyncio.sleep(self.settings.drain_seconds)

    async def process(self,lease):
        began = time.monotonic()
        fields = {'job_id':str(lease.job_id),'owner_ref':hashlib.sha256(lease.owner_id.bytes).hexdigest()[:24]}
        logger.info('job_started',extra={'event':'job_started',**fields})
        outcome = 'interrupted'
        executor=self.import_executor if lease.type=="import" else self.executor
        execution = asyncio.create_task(executor.execute(lease))
        stop_heartbeat = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(lease,stop_heartbeat))
        drain = asyncio.create_task(self._drain())
        try:
            done,_ = await asyncio.wait([execution,heartbeat,drain],return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done or drain in done:
                outcome = 'lease_lost' if heartbeat in done else 'interrupted'
                execution.cancel()
                return
            # Resolve any DB heartbeat already in flight, then stop scheduling
            # heartbeats before terminal publication. Failure is fail-closed.
            stop_heartbeat.set()
            if not await heartbeat or drain.done():
                return
            try:
                result = execution.result()
            except (JobError,LlmError) as exc:
                outcome = 'failed'
                error = ErrorBody(code=exc.code,message=exc.code.replace('_',' ').capitalize(),requestId=str(lease.job_id))
                await asyncio.to_thread(self.publication.fail,lease,error)
            except ImportLeaseLost:
                outcome = 'lease_lost'
                return
            except SQLAlchemyError:
                outcome = 'failed'
                if lease.type=='import':
                    # Leave the lease for normal bounded queue recovery; committed
                    # item outcomes survive a transient DB failure.
                    return
                error = ErrorBody(code='service_unavailable',message='Service unavailable',requestId=str(lease.job_id))
                await asyncio.to_thread(self.publication.fail,lease,error)
            except Exception:
                outcome = 'failed'
                error = ErrorBody(code='service_unavailable',message='Service unavailable',requestId=str(lease.job_id))
                await asyncio.to_thread(self.publication.fail,lease,error)
            else:
                if lease.type == 'analysis':
                    published = await asyncio.to_thread(self.publication.succeed_analysis,lease,result)
                elif lease.type=='import':
                    published = await asyncio.to_thread(self.publication.succeed_import,lease,result)
                else:
                    published = await asyncio.to_thread(self.publication.succeed_suggestions,lease,result)
                outcome = 'succeeded' if published else 'lease_lost'
        finally:
            logger.info('job_finished',extra={'event':'job_finished',**fields,'outcome':outcome,'duration_ms':(time.monotonic()-began)*1000})
            for task in (execution,heartbeat,drain):
                if not task.done(): task.cancel()
            await asyncio.gather(execution,heartbeat,drain,return_exceptions=True)

    async def run_forever(self):
        try:
            while not self.stopping.is_set():
                try:
                    await asyncio.to_thread(self.queue.recover_expired)
                    lease = await asyncio.to_thread(self.queue.claim)
                    await asyncio.to_thread(self.health.mark)
                    if lease is not None:
                        await self.process(lease)
                        continue
                except Exception:
                    await asyncio.to_thread(self.health.clear)
                    logger.warning('worker iteration unavailable')
                try:
                    await asyncio.wait_for(self.stopping.wait(),timeout=self.settings.poll_interval)
                except TimeoutError:
                    pass
        finally:
            await asyncio.to_thread(self.health.clear)

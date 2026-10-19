import asyncio
from concurrent.futures import ThreadPoolExecutor
from ..config import Settings
from ..storage.database import create_engine
from ..storage.migrate import check_schema
from ..storage.job_queue import JobQueue
from ..storage.job_publication import JobPublication
from ..llm.runtime import LlmRuntime
from ..jobs.execution import FrozenJobExecutor
from .settings import WorkerSettings
from .health import WorkerHealth
from .runner import WorkerRunner
from ..imports.execution import ImportExecutor


class WorkerRuntime:
    def __init__(self,settings: Settings,worker_settings=None):
        self.settings = settings.model_copy(update={'statement_timeout_ms':5000,'pool_timeout_seconds':5})
        self.worker_settings = worker_settings or WorkerSettings()
        self.health = WorkerHealth(self.worker_settings.health_path,
            max_age=self.worker_settings.heartbeat_seconds*2+5)
        self.engine = self.llm = self.runner = None
        self.metrics_server = None

    async def start(self):
        if self.settings.open_ai_key is None or not self.settings.open_ai_key.get_secret_value().strip():
            await asyncio.to_thread(self.health.clear)
            raise ValueError('Worker provider configuration unavailable')
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=4,thread_name_prefix='fitcheck-db'))
        await asyncio.to_thread(self.health.claim)
        await asyncio.to_thread(self.health.clear)
        await asyncio.to_thread(check_schema,self.settings)
        self.engine = create_engine(self.settings)
        self.llm = LlmRuntime(self.settings,self.engine)
        metrics_environment = self.settings.metrics_environment if self.settings.metrics_enabled else None
        self.runner = WorkerRunner(JobQueue(self.engine,lease_seconds=self.worker_settings.lease_seconds,metrics_environment=metrics_environment),
            FrozenJobExecutor(self.llm,model=self.settings.open_ai_model),JobPublication(self.engine,metrics_environment=metrics_environment),self.worker_settings,self.health,import_executor=ImportExecutor(self.engine))
        await asyncio.to_thread(self.health.mark)
        if self.worker_settings.metrics_port:
            from ..operations.worker_metrics import start_worker_metrics
            self.metrics_server = start_worker_metrics(self.worker_settings.metrics_host,self.worker_settings.metrics_port,self.worker_settings.health_path)
        return self.runner

    async def aclose(self):
        try:
            if getattr(self,'metrics_server',None) is not None:
                await asyncio.to_thread(self.metrics_server.shutdown)
                self.metrics_server.server_close()
            await asyncio.to_thread(self.health.close)
        finally:
            try:
                if self.llm is not None:
                    await self.llm.aclose()
            finally:
                if self.engine is not None:
                    await asyncio.to_thread(self.engine.dispose)

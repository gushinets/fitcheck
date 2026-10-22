"""Loopback-only E2E fixture. Real auth/storage/queue; captured mail and free deterministic results.

Always uses a dedicated fitcheck_e2e_test database, never backend/.env.
"""
import asyncio
import json
import os
import threading
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from fastapi import HTTPException

from fitcheck_backend.config import Settings
from fitcheck_backend.api.app import create_app
from fitcheck_backend.api.runtime import AuthRuntime
from fitcheck_backend.storage.migrate import run_migrations
from fitcheck_backend.storage.job_queue import JobQueue
from fitcheck_backend.storage.job_publication import JobPublication
from fitcheck_backend.jobs.envelope import decode_envelope
from fitcheck_backend.contracts.resources import AnalysisSnapshot
from fitcheck_backend.contracts.domain import FitAnalysis
from fitcheck_backend.analysis.service import AnalysisResult
from fitcheck_backend.imports.execution import ImportExecutor
from fitcheck_backend.extraction.network import PublicPageResponse
from fitcheck_backend.extraction.errors import ExtractionError

url = make_url(os.environ.get('FITCHECK_E2E_DATABASE_URL', 'postgresql+psycopg://fitcheck_test:fitcheck_test@127.0.0.1:55464/fitcheck_e2e_test'))
if url.database != 'fitcheck_e2e_test' or url.host not in {'127.0.0.1', 'localhost'}:
    raise RuntimeError('E2E requires a loopback database named fitcheck_e2e_test')
admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
with admin.connect() as connection:
    if not connection.scalar(text("SELECT 1 FROM pg_database WHERE datname = 'fitcheck_e2e_test'")):
        connection.execute(text('CREATE DATABASE fitcheck_e2e_test'))
admin.dispose()
settings = Settings(env='test', database_url=url.render_as_string(hide_password=False),
    auth_enabled=True, jobs_enabled=True, guest_enabled=True, auth_secret='ab' * 32,
    allowed_origins=['http://127.0.0.1:38153'], auth_web_base_url='http://127.0.0.1:38153',
    guest_create_hourly_limit=100, guest_create_daily_limit=100)
run_migrations(settings)


class Mailbox:
    def __init__(self): self.messages = []
    def available(self): return True
    def send(self, message): self.messages.append(message)


mailbox = Mailbox()
runtime = AuthRuntime(settings, mailer=mailbox)
with runtime.engine.begin() as connection:
    connection.execute(text('TRUNCATE owners, provider_calls, auth_rate_buckets CASCADE'))
app = create_app(settings, auth_runtime=runtime)
domain = json.loads((Path(__file__).parents[1] / 'backend/tests/fixtures/domain.json').read_text(encoding='utf-8'))


def captured_task_page(url):
    if url != 'https://tasks.example.test/projects/n8n/task?ref=history#details':
        raise ExtractionError('fetch_failed')
    return PublicPageResponse('https://tasks.example.test/projects/n8n/canonical-task', 'text/plain',
        'n8n integration task\nBuild reliable n8n automations connecting customer tools and CRM APIs.\nSkills: n8n, TypeScript')


# Replace only the external page fetch; extraction/auth/API/storage remain real.
runtime.extraction.fetch_page = captured_task_page


@app.get('/testing/mail')
def mail(email: str):
    for message in reversed(mailbox.messages):
        if message.recipient == email: return {'token': message.token}
    raise HTTPException(404)


stop = threading.Event()


def worker():
    queue, publication = JobQueue(runtime.engine), JobPublication(runtime.engine)
    while not stop.wait(.1):
        lease = queue.claim()
        if lease is None: continue
        # Keep a job in flight long enough to test reload/recovery.
        if stop.wait(2): return
        if lease.type == 'analysis':
            e = decode_envelope(lease.type, lease.input)
            snapshot = AnalysisSnapshot(profileRevision=e.profile_revision, profile=e.profile, vacancy=e.vacancy,
                locale=e.locale, promptVersion=e.versions.prompt_version, schemaVersion=e.versions.schema_version,
                policyVersion=e.versions.policy_version)
            # Captured fixture outcomes exercise both history verdicts without a paid model.
            analysis = {**domain['analysis'], 'score': 40, 'status': 'NO_GO'} if e.vacancy.title == 'Persisted React task' else domain['analysis']
            publication.succeed_analysis(lease, AnalysisResult(FitAnalysis.model_validate(analysis), snapshot))
        elif lease.type == 'skill_suggestions':
            publication.succeed_suggestions(lease, ['React', 'TypeScript'])
        else:
            report = asyncio.run(ImportExecutor(runtime.engine).execute(lease))
            publication.succeed_import(lease, report)


@asynccontextmanager
async def lifecycle(_app):
    thread = threading.Thread(target=worker, daemon=True); thread.start()
    try: yield
    finally: stop.set(); thread.join(timeout=5); runtime.close()


app.router.lifespan_context = lifecycle
if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=38154, log_level='warning')

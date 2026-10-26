"""Paid, explicit canary: real API admission, worker, provider and PostgreSQL."""
import asyncio
import os
from uuid import UUID

import pytest
from sqlalchemy import select

from test_profile_http import profile_http, save, DATA
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.models import AnalysisRecord, Job, ProviderCall
from fitcheck_backend.worker.runtime import WorkerRuntime
from fitcheck_backend.worker.settings import WorkerSettings


pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('FITCHECK_RUN_LLM_CANARY') != '1' or not os.environ.get('OPEN_AI_KEY'),
    reason='Live jobs canary requires explicit opt-in and provider key')]


@pytest.fixture
def live_profile_http(auth_components, request):
    # The real worker checks session expiry against PostgreSQL's wall clock.
    auth_components.now[0] = utcnow()
    return request.getfixturevalue('profile_http')


def test_live_analysis_and_suggestions_are_published_and_accounted(live_profile_http, tmp_path):
    a, client, _, _, headers = live_profile_http
    client.app.state.settings.jobs_enabled = True
    assert save(client, headers).status_code == 200
    jobs = []
    for path, body in [
        ('analysis', dict(mode='account', vacancy=DATA['vacancy'], profileRevision='1', locale='en')),
        ('skill-suggestion', dict(specialization='React frontend developer', locale='en')),
    ]:
        admitted = client.post(f'/v1/{path}-jobs', json=body,
            headers={**headers, 'Idempotency-Key': f'live-{path}'})
        assert admitted.status_code == 202
        assert admitted.json()['status'] == 'queued'
        jobs.append(UUID(admitted.json()['jobId']))

    async def run():
        worker = WorkerRuntime(client.app.state.settings, WorkerSettings(
            health_path=str(tmp_path / 'worker-health.json')))
        try:
            runner = await worker.start()
            # Observe sends without replacing the real adapter or HTTP transport.
            sends = []
            async def count_send(request):
                sends.append(request.url.path)
            worker.llm.gateway.adapter.client.event_hooks['request'].append(count_send)
            for job_id in jobs:
                lease = await asyncio.to_thread(runner.queue.claim)
                assert lease is not None and lease.job_id == job_id
                assert client.get(f'/v1/jobs/{job_id}').json()['status'] == 'running'
                await runner.process(lease)
            return sends
        finally:
            await worker.aclose()

    sends = asyncio.run(run())
    for job_id in jobs:
        response = client.get(f'/v1/jobs/{job_id}')
        assert response.status_code == 200
        assert response.json()['status'] == 'succeeded'
    analysis = client.get(f'/v1/jobs/{jobs[0]}').json()
    assert analysis['result']['analysis']['verdictThreshold'] == 70
    assert client.get('/v1/analyses/' + analysis['analysisId']).json() == analysis['result']
    assert client.get(f'/v1/jobs/{jobs[1]}').json()['skills']
    with unit_of_work(a.engine) as session:
        assert session.scalar(select(AnalysisRecord).where(AnalysisRecord.job_id == jobs[0])) is not None
        assert session.get(Job, jobs[1]).output['skills']
        calls = session.scalars(select(ProviderCall).where(ProviderCall.job_id.in_(jobs))).all()
        assert len(calls) == len(sends)
        assert {call.job_id for call in calls} == set(jobs)
        assert all(call.finished_at is not None and call.latency_ms >= 0 for call in calls)
        assert all(call.input_tokens is not None and call.output_tokens is not None for call in calls)
        assert all(call.state in {'succeeded', 'failed'} for call in calls)

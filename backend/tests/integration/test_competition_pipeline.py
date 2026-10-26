import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_profile_http import profile_http, save, DATA
from test_analysis_service import service, model_reply
from fitcheck_backend.extraction.network import PublicPageResponse
from fitcheck_backend.jobs.execution import FrozenJobExecutor
from fitcheck_backend.storage.job_queue import JobQueue
from fitcheck_backend.storage.job_publication import JobPublication
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import VacancyRecord
from fitcheck_backend.storage.base import utcnow

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / 'fixtures/freelancer-current'
INLINE = ('n8n workflow automation\nBuild reliable n8n workflows connecting webhooks and customer APIs. '
    'Remote work, all communication in English. Hourly budget: USD 25-35. '
    'Proposals: 248. Average bid: 500 USD.')


@pytest.fixture(autouse=True)
def current_auth_clock(auth_components):
    # Provider reservations recheck the actual originating session at DB time.
    # Issue test cookies now rather than the auth fixture's fixed January date.
    auth_components.now[0] = utcnow()


@pytest.mark.parametrize('name,count', [('lead', 9), ('n8n', 171), ('shopify', 406), ('whatsapp', 106), ('inline', 248), ('manual', 248)])
def test_extracted_competition_survives_draft_frozen_execution_and_history(profile_http, monkeypatch, name, count):
    a, client, runtime, _, headers = profile_http
    client.app.state.settings.jobs_enabled = True
    assert save(client, headers).status_code == 200
    if name in ('inline', 'manual'):
        body = {'type': 'text', 'text': INLINE}
    else:
        url = f'https://www.freelancer.com/projects/test/{name}'
        monkeypatch.setattr(runtime.extraction, 'fetch_page', lambda _: PublicPageResponse(
            url, 'text/html', (FIXTURES / f'{name}.html').read_text()))
        body = {'type': 'url', 'url': url}
    response = client.post('/v1/extractions', headers=headers, json=body)
    assert response.status_code == 200, response.text
    vacancy = response.json()['vacancy']
    assert vacancy['proposalCount'] == count
    if name in ('inline', 'manual'):
        assert vacancy['averageBid'] == 500 and vacancy['averageBidCurrency'] == 'USD'
        assert vacancy['hourlyRateMin'] == 25 and vacancy['hourlyRateMax'] == 35
    else:
        assert 'averageBid' not in vacancy
    # The website's manual draft has no client-side competition extraction.
    manual = {key: value for key, value in vacancy.items() if key not in (
        'proposalCount', 'averageBid', 'averageBidCurrency', 'provenance')} if name == 'manual' else vacancy
    draft = {'vacancy': manual, 'locale': 'en'}
    saved = client.put('/v1/draft', headers=headers, json=draft)
    assert saved.status_code == 200
    vacancy = saved.json()['vacancy']
    assert vacancy['proposalCount'] == count
    assert client.get('/v1/draft').json() == saved.json()
    admitted = client.post('/v1/analysis-jobs', headers={**headers, 'Idempotency-Key': name},
        json={'mode': 'account', 'vacancy': manual, 'profileRevision': '1', 'locale': 'en'})
    assert admitted.status_code == 202, admitted.text
    application, adapter = service(a.engine, [model_reply({**DATA['analysis'], 'score': 74, 'strengths': [], 'risks': []}),
        model_reply({'supported': True, 'unsupportedClaims': []})])
    lease = JobQueue(a.engine).claim()
    result = asyncio.run(FrozenJobExecutor(SimpleNamespace(analysis=application)).execute(lease))
    analysis_id = JobPublication(a.engine).succeed_analysis(lease, result)
    generation = json.loads(adapter.calls[0]['messages'][-1]['content'].split('\n')[1])
    audit = json.loads(adapter.calls[1]['messages'][-1]['content'])
    expected = {'level': 'low' if count < 10 else 'high', 'proposalCount': count}
    if name in ('inline', 'manual'):
        expected.update(averageBid=500, averageBidCurrency='USD')
    assert generation['competition'] == audit['competition'] == expected
    history = client.get('/v1/history').json()['items'][0]
    assert history['analysisId'] == str(analysis_id)
    assert history['snapshot']['vacancy'] == vacancy
    assert str(count) in history['analysis']['summary']
    assert history['analysis']['score'] == 74
    if count >= 50:
        assert any('High competition' in risk and str(count) in risk for risk in history['analysis']['risks'])
    if name in ('inline', 'manual'):
        assert '500 USD' in history['analysis']['summary']
    with unit_of_work(a.engine) as session:
        stored = session.query(VacancyRecord).one()
        assert stored.vacancy['proposalCount'] == count

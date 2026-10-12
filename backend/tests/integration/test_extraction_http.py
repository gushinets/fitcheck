import pytest

from test_profile_http import profile_http, WEB
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import User

pytestmark = pytest.mark.integration
TEXT = 'Lead Generation\nFind business leads for the marketing team.\nBudget: €250–750\nSkills: Lead generation, Cold outreach'


def test_text_extraction_returns_editable_vacancy_and_preserves_draft(profile_http):
    _, client, _, _, headers = profile_http
    result = client.post('/v1/extractions', headers=headers, json={'type': 'text', 'text': TEXT})
    assert result.status_code == 200, result.text
    vacancy = result.json()['vacancy']
    assert vacancy['id']
    assert vacancy['title'] == 'Lead Generation'
    assert vacancy['skills'] == ['Lead generation', 'Cold outreach']
    assert vacancy['fixedBudget'] == 250 and vacancy['fixedBudgetMax'] == 750
    assert vacancy['budgetCurrency'] == 'EUR'
    assert 'url' not in vacancy and 'proposalCount' not in vacancy
    assert vacancy['provenance']['fixedBudget'] == 'text'
    assert result.headers['cache-control'] == 'no-store'
    assert client.get('/v1/draft').json() is None
    vacancy['description'] = 'User corrected requirements before submitting the analysis.'
    assert client.put('/v1/draft', headers=headers, json={'vacancy': vacancy, 'locale': 'en'}).status_code == 200
    assert client.get('/v1/draft').json()['vacancy'] == vacancy


def test_url_extraction_preserves_final_source_and_competition(profile_http, monkeypatch):
    from fitcheck_backend.extraction.network import PublicPageResponse
    _, client, runtime, _, headers = profile_http
    def fetch(url):
        return PublicPageResponse('https://jobs.example/final', 'text/plain',
            TEXT + '\nProposals: 248\nAverage bid: $500')
    monkeypatch.setattr(runtime.extraction, 'fetch_page', fetch)
    result = client.post('/v1/extractions', headers=headers, json={'type': 'url', 'url': 'https://jobs.example/initial'})
    assert result.status_code == 200, result.text
    vacancy = result.json()['vacancy']
    assert vacancy['url'] == 'https://jobs.example/final'
    assert vacancy['proposalCount'] == 248 and vacancy['averageBid'] == 500
    assert vacancy['averageBidCurrency'] == 'USD'
    assert vacancy['fixedBudget'] == 250 and vacancy['budgetCurrency'] == 'EUR'


def test_auth_and_csrf_guard_all_extraction_before_network(profile_http, monkeypatch):
    a, client, runtime, issued, headers = profile_http
    def unexpected(_):
        pytest.fail('Denied extraction must not fetch a page')
    monkeypatch.setattr(runtime.extraction, 'fetch_page', unexpected)
    request = {'type': 'url', 'url': 'https://jobs.example/task'}
    assert client.post('/v1/extractions', json=request).status_code == 403
    assert client.post('/v1/extractions', headers={**headers, 'Origin': 'https://evil.example'}, json=request).status_code == 403
    client.cookies.clear()
    assert client.post('/v1/extractions', headers=headers, json=request).status_code == 401
    client.cookies.set('__Host-fitcheck_session', issued.token)
    with unit_of_work(a.engine) as session:
        session.get(User, issued.principal.user_id).email_verified_at = None
    assert client.post('/v1/extractions', headers=headers, json=request).status_code == 403


@pytest.mark.parametrize('code,status', [('blocked_address',403), ('timeout',504),
    ('unsupported_content',415), ('response_too_large',413), ('fetch_failed',502)])
def test_network_errors_are_safe_and_allow_manual_input(profile_http, monkeypatch, code, status):
    from fitcheck_backend.extraction.errors import ExtractionError
    _, client, runtime, _, headers = profile_http
    def failed(_):
        raise ExtractionError(code) from RuntimeError('password=private-secret')
    monkeypatch.setattr(runtime.extraction, 'fetch_page', failed)
    result = client.post('/v1/extractions', headers=headers, json={'type': 'url', 'url': 'https://jobs.example/task'})
    assert result.status_code == status and result.json()['error']['code'] == code
    assert 'private-secret' not in result.text
    assert result.json()['error']['requestId'] == result.headers['x-request-id']
    assert client.post('/v1/extractions', headers=headers, json={'type':'text', 'text':TEXT}).status_code == 200


@pytest.mark.parametrize('body', [{'type':'text','text':'Short\nNo content'},
    {'type':'url','url':'file:///etc/passwd'}, {'type':'text','text':TEXT,'ownerId':'other'},
    {'type':'text','text':'x' * 20001}])
def test_invalid_input_and_insufficient_content(profile_http, body):
    _, client, _, _, headers = profile_http
    result = client.post('/v1/extractions', headers=headers, json=body)
    assert result.status_code == 400, result.text


def test_extraction_rate_limits_survive_failed_fetches(profile_http, monkeypatch):
    from fitcheck_backend.extraction.errors import ExtractionError
    _, client, runtime, _, headers = profile_http
    def failed(_):
        raise ExtractionError('fetch_failed')
    monkeypatch.setattr(runtime.extraction, 'fetch_page', failed)
    body = {'type':'url', 'url':'https://jobs.example/task'}
    for _ in range(30):
        assert client.post('/v1/extractions', headers=headers, json=body).status_code == 502
    limited = client.post('/v1/extractions', headers=headers, json=body)
    assert limited.status_code == 429 and int(limited.headers['retry-after']) > 0

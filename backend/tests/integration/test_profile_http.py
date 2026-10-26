import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from fitcheck_backend.api.app import create_app
from fitcheck_backend.api.runtime import AuthRuntime
from fitcheck_backend.config import Settings
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import User, ProfileRevision

pytestmark = pytest.mark.integration
DATA = json.loads((Path(__file__).parents[1] / 'fixtures/domain.json').read_text())
WEB = 'https://web.example.com'


@pytest.fixture
def profile_http(auth_components):
    a = auth_components
    settings = Settings(env='production', auth_enabled=True, auth_secret='78' * 32,
        auth_web_base_url=WEB, database_url=a.engine.url.render_as_string(hide_password=False),
        allowed_origins=[WEB])
    runtime = AuthRuntime(settings, engine=a.engine, mailer=a.mailer, clock=a.clock)
    issued = a.service.register('profile@example.com', 'correct horse battery', '127.0.0.1')
    with unit_of_work(a.engine) as session:
        session.get(User, issued.principal.user_id).email_verified_at = a.clock()
    app = create_app(settings, auth_runtime=runtime)
    with TestClient(app, base_url='https://api.example.com') as client:
        client.cookies.set('__Host-fitcheck_session', issued.token)
        headers = {'Origin': WEB, 'X-CSRF-Token': issued.csrf_token}
        yield a, client, runtime, issued, headers


def save(client, headers, revision=None, **changes):
    return client.put('/v1/profile', headers=headers,
        json={'expectedRevision': revision, 'profile': {**DATA['profile'], **changes}})


def test_initial_profile_normalization_noop_and_immutable_history(profile_http):
    a, client, _, issued, headers = profile_http
    assert client.get('/v1/profile').status_code == 404
    first = save(client, headers, skills=[' React ', 'react', 'TypeScript'])
    assert first.status_code == 200, first.text
    assert first.json() == {'revision': '1', 'profile': DATA['profile']}
    assert first.headers['cache-control'] == 'no-store'
    assert save(client, headers, '1').json()['revision'] == '1'
    changed = save(client, headers, '1', preferredRate=70, rateCurrency='RUB')
    assert changed.status_code == 200 and changed.json()['revision'] == '2'
    assert client.get('/v1/profile/revisions/1').json() == first.json()
    comparison = client.get('/v1/profile/revisions/1/comparison')
    assert comparison.status_code == 200, comparison.text
    assert comparison.json() == {'saved': first.json(), 'current': changed.json(),
        'changedFields': ['preferredRate', 'rateCurrency']}
    assert client.get('/v1/profile/revisions/2/comparison').json()['changedFields'] == []
    assert save(client, headers, '1').status_code == 409
    assert save(client, headers).status_code == 409
    assert client.get('/v1/profile').json() == changed.json()
    with unit_of_work(a.engine) as session:
        assert session.scalar(select(func.count()).select_from(ProfileRevision)
            .where(ProfileRevision.owner_id == issued.principal.owner_id)) == 2


@pytest.mark.parametrize('currency', ['USD', 'EUR', 'RUB'])
def test_skill_levels_and_currency_are_preserved(profile_http, currency):
    _, client, _, _, headers = profile_http
    result = save(client, headers, rateCurrency=currency, skills=['React', 'TypeScript', 'SQL'],
        skillLevels={'react': 'primary', 'typescript': 'confident', 'sql': 'basic'})
    assert result.status_code == 200, result.text
    assert client.get('/v1/profile').json() == result.json()
    assert result.json()['profile']['rateCurrency'] == currency
    assert result.json()['profile']['skillLevels'] == {'react': 'primary', 'typescript': 'confident', 'sql': 'basic'}


def test_preferences_and_draft_survive_login_from_other_device(profile_http):
    _, client, runtime, _, headers = profile_http
    assert client.get('/v1/preferences').json() == {'locale': 'en'}
    assert client.get('/v1/draft').json() is None
    assert client.put('/v1/preferences', headers=headers, json={'locale': 'ru'}).json() == {'locale': 'ru'}
    vacancy = {**DATA['vacancy'], 'hourlyRateMin': 10, 'hourlyRateMax': 20,
        'budgetCurrency': 'EUR'}
    draft = {'vacancy': vacancy, 'locale': 'ru'}
    assert client.put('/v1/draft', headers=headers, json=draft).json() == draft
    assert save(client, headers).status_code == 200
    second = runtime.auth.login('profile@example.com', 'correct horse battery', '127.0.0.2')
    with TestClient(create_app(runtime.settings, auth_runtime=runtime), base_url='https://api.example.com') as other:
        other.cookies.set('__Host-fitcheck_session', second.token)
        assert other.get('/v1/profile').json() == {'revision': '1', 'profile': DATA['profile']}
        assert other.get('/v1/preferences').json() == {'locale': 'ru'}
        assert other.get('/v1/draft').json() == draft


def test_draft_can_be_cleared_idempotently(profile_http):
    _, client, _, _, headers = profile_http
    draft = {'vacancy': DATA['vacancy'], 'locale': 'en'}
    assert client.put('/v1/draft', headers=headers, json=draft).status_code == 200
    cleared = client.put('/v1/draft', headers={**headers, 'Content-Type': 'application/json'}, content='null')
    assert cleared.status_code == 200 and cleared.json() is None
    assert client.get('/v1/draft').json() is None
    for _ in range(2):
        assert client.delete('/v1/draft', headers=headers).status_code == 204


def test_two_website_devices_concurrent_updates_conflict(profile_http):
    _, client, runtime, issued, headers = profile_http
    assert save(client, headers).status_code == 200
    second = runtime.auth.login('profile@example.com', 'correct horse battery', '127.0.0.2')
    barrier = Barrier(2)
    def write(index):
        with TestClient(create_app(runtime.settings, auth_runtime=runtime), base_url='https://api.example.com') as device:
            if index == 0:
                device.cookies.set('__Host-fitcheck_session', issued.token)
                mutation_headers = headers
            else:
                device.cookies.set('__Host-fitcheck_session', second.token)
                mutation_headers = {'Origin': WEB, 'X-CSRF-Token': second.csrf_token}
            barrier.wait(timeout=10)
            return save(device, mutation_headers, '1', specialization=f'Writer {index}')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [0, 1]))
    assert sorted(result.status_code for result in results) == [200, 409]
    conflict = next(result for result in results if result.status_code == 409)
    assert conflict.json()['error']['code'] == 'profile_revision_conflict'
    assert client.get('/v1/profile').json()['revision'] == '2'
    assert client.get('/v1/profile/revisions/1').json()['profile'] == DATA['profile']


@pytest.mark.parametrize('path', ['/v1/profile', '/v1/profile/revisions/1',
    '/v1/profile/revisions/1/comparison', '/v1/preferences', '/v1/draft'])
def test_reads_require_verified_account(profile_http, path):
    a, client, _, issued, _ = profile_http
    client.cookies.clear()
    assert client.get(path).status_code == 401
    client.cookies.set('__Host-fitcheck_session', issued.token)
    with unit_of_work(a.engine) as session:
        session.get(User, issued.principal.user_id).email_verified_at = None
    assert client.get(path).status_code == 403


def test_ownership_csrf_and_invalid_input(profile_http):
    a, client, _, issued, headers = profile_http
    assert save(client, {}).status_code == 403
    assert save(client, {**headers, 'Origin': 'https://evil.example.com'}).status_code == 403
    assert save(client, headers, desiredMonthlyIncome=1000).status_code == 400
    assert client.put('/v1/preferences', headers=headers, json={'locale': 'de'}).status_code == 400
    assert client.put('/v1/preferences', headers=headers, json={'locale': 'ru', 'ownerId': 'forged'}).status_code == 400
    assert save(client, headers).status_code == 200
    for revision in ['0', '01', 'r1', '2147483648']:
        assert save(client, headers, revision).status_code == 400
        assert client.get('/v1/profile/revisions/' + revision).status_code == 400
    assert client.get('/v1/profile/revisions/99').status_code == 404
    assert client.put('/v1/preferences', headers=headers, json={'locale': 'ru'}).status_code == 200
    draft = {'vacancy': DATA['vacancy'], 'locale': 'ru'}
    assert client.put('/v1/draft', headers=headers, json=draft).status_code == 200
    other = a.service.register('other@example.com', 'correct horse battery', '127.0.0.2')
    with unit_of_work(a.engine) as session:
        session.get(User, other.principal.user_id).email_verified_at = a.clock()
    client.cookies.set('__Host-fitcheck_session', other.token)
    other_headers = {'Origin': WEB, 'X-CSRF-Token': other.csrf_token}
    assert client.get('/v1/profile').status_code == 404
    assert client.get('/v1/profile/revisions/1').status_code == 404
    assert client.get('/v1/profile/revisions/1/comparison').status_code == 404
    assert client.get('/v1/preferences').json() == {'locale': 'en'}
    assert client.get('/v1/draft').json() is None
    assert save(client, other_headers, '1').status_code == 409
    assert save(client, other_headers).status_code == 200
    assert client.put('/v1/preferences', headers=other_headers, json={'locale': 'en'}).status_code == 200
    assert client.delete('/v1/draft', headers=other_headers).status_code == 204
    client.cookies.set('__Host-fitcheck_session', issued.token)
    assert client.get('/v1/preferences').json() == {'locale': 'ru'}
    assert client.get('/v1/draft').json() == draft


def test_parallel_profile_creation_only_creates_one_revision(profile_http):
    a, client, runtime, issued, headers = profile_http
    barrier = Barrier(2)
    def write(index):
        with TestClient(create_app(runtime.settings, auth_runtime=runtime), base_url='https://api.example.com') as device:
            device.cookies.set('__Host-fitcheck_session', issued.token)
            barrier.wait(timeout=10)
            return save(device, headers, specialization=f'Writer {index}').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, [0, 1])) == [200, 409]
    with unit_of_work(a.engine) as session:
        assert session.scalar(select(func.count()).select_from(ProfileRevision)) == 1


def test_null_and_missing_draft_body_are_distinct(profile_http):
    _, client, _, _, headers = profile_http
    assert client.put('/v1/draft', headers=headers).status_code == 400
    assert client.put('/v1/draft', headers=headers, json={}).status_code == 400
    assert client.put('/v1/draft', headers=headers, json={'vacancy': DATA['vacancy'], 'locale': 'de'}).status_code == 400


def test_legacy_import_payload_never_persists_income(profile_http):
    from fitcheck_backend.contracts.resources import LegacyProfile
    from fitcheck_backend.storage.profile_repository import create_profile
    a, client, _, issued, _ = profile_http
    legacy = LegacyProfile.model_validate({**DATA['profile'], 'desiredMonthlyIncome': 9000})
    with unit_of_work(a.engine) as session:
        create_profile(session, issued.principal.owner_id, legacy)
    assert client.get('/v1/profile').json()['profile'] == DATA['profile']
    with unit_of_work(a.engine) as session:
        payload = session.scalar(select(ProfileRevision.profile).where(ProfileRevision.owner_id == issued.principal.owner_id))
        assert 'desiredMonthlyIncome' not in payload


def test_revocation_between_resolution_and_mutation_is_rechecked(profile_http):
    from fitcheck_backend.auth.errors import AuthError
    from fitcheck_backend.contracts.resources import ProfileUpdate
    _, client, runtime, issued, _ = profile_http
    principal = runtime.auth.resolve(issued.token, 'web')
    runtime.auth.logout(principal)
    with pytest.raises(AuthError, match='unauthenticated'):
        runtime.profiles.update(principal, ProfileUpdate(expectedRevision=None, profile=DATA['profile']))


def test_bearer_credentials_cannot_authenticate_site_routes(profile_http):
    _, client, runtime, issued, headers = profile_http
    assert save(client, headers).status_code == 200
    with TestClient(create_app(runtime.settings, auth_runtime=runtime), base_url='https://api.example.com') as other:
        bearer = {'Authorization': 'Bearer ' + issued.token}
        assert other.get('/v1/profile', headers=bearer).status_code == 401
        other.cookies.set('__Host-fitcheck_session', issued.token)
        assert other.get('/v1/profile', headers=bearer).status_code == 403


def test_analysis_keeps_the_used_revision_after_profile_update(profile_http):
    from fitcheck_backend.contracts.resources import AnalysisSnapshot
    from fitcheck_backend.storage.models import AnalysisRecord, VacancyRecord
    from fitcheck_backend.storage.payloads import encode_snapshot
    a, client, _, issued, headers = profile_http
    assert save(client, headers).status_code == 200
    snapshot = encode_snapshot(AnalysisSnapshot(profileRevision='1', profile=DATA['profile'],
        vacancy=DATA['vacancy'], locale='en', promptVersion='p1',
        schemaVersion='fitcheck.analysis.v1', policyVersion='v1'))
    with unit_of_work(a.engine) as session:
        vacancy = VacancyRecord(owner_id=issued.principal.owner_id, vacancy=DATA['vacancy'])
        session.add(vacancy)
        session.flush()
        analysis = AnalysisRecord(owner_id=issued.principal.owner_id, vacancy_id=vacancy.id,
            profile_revision=1, snapshot=snapshot, analysis=DATA['analysis'])
        session.add(analysis)
        session.flush()
        analysis_id = analysis.id
    assert save(client, headers, '1', preferredRate=70).status_code == 200
    with unit_of_work(a.engine) as session:
        analysis = session.get(AnalysisRecord, analysis_id)
        assert analysis.profile_revision == 1
        assert analysis.snapshot == snapshot
    assert client.get('/v1/profile/revisions/1/comparison').json()['changedFields'] == ['preferredRate']

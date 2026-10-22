from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from test_profile_http import profile_http, save, DATA, WEB
from fitcheck_backend.contracts.resources import AnalysisSnapshot
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import AnalysisRecord, AnalysisAnnotation, VacancyRecord, Job, User
from fitcheck_backend.storage.payloads import encode_snapshot

pytestmark = pytest.mark.integration


def seed(fixture, *, count=1, verdict='GO', url=True, annotation=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)):
    a, client, runtime, issued, headers = fixture
    if client.get('/v1/profile').status_code == 404:
        assert save(client, headers).status_code == 200
    vacancy = dict(DATA['vacancy'])
    if not url:
        vacancy.pop('url', None)
    snapshot = encode_snapshot(AnalysisSnapshot(profileRevision='1', profile=DATA['profile'],
        vacancy=vacancy, locale='en', promptVersion='p1', schemaVersion='fitcheck.analysis.v1', policyVersion='v1'))
    ids = []
    with unit_of_work(a.engine) as s:
        for _ in range(count):
            v = VacancyRecord(owner_id=issued.principal.owner_id, vacancy=vacancy, source_url=vacancy.get('url'))
            s.add(v); s.flush()
            record = AnalysisRecord(owner_id=issued.principal.owner_id, vacancy_id=v.id,
                profile_revision=1, snapshot=snapshot, analysis={**DATA['analysis'], 'status': verdict},
                created_at=created_at)
            s.add(record); s.flush()
            if annotation:
                s.add(AnalysisAnnotation(owner_id=issued.principal.owner_id, analysis_id=record.id))
            ids.append(str(record.id))
    return ids


def test_detail_snapshot_url_and_revision_change(profile_http):
    _, c, _, _, h = profile_http
    identifier = seed(profile_http)[0]
    original = c.get('/v1/analyses/' + identifier)
    assert original.status_code == 200, original.text
    value = original.json()
    assert value['snapshot']['vacancy'] == DATA['vacancy']
    assert value['snapshot']['profileRevision'] == '1'
    assert value['profileChanged'] is False and value['currentProfileRevision'] == '1'
    assert save(c, h, '1', preferredRate=70).status_code == 200
    changed = c.get('/v1/analyses/' + identifier).json()
    assert changed['profileChanged'] is True and changed['currentProfileRevision'] == '2'
    assert changed['snapshot'] == value['snapshot']
    assert c.get('/v1/history').json()['items'] == [changed]


@pytest.mark.parametrize('sort', ['newest', 'oldest'])
def test_keyset_tied_dates_filters_and_missing_annotations(profile_http, sort):
    _, c, _, _, h = profile_http
    ids = seed(profile_http, count=5, annotation=False)
    seed(profile_http, count=2, verdict='NO_GO')
    assert c.put('/v1/analyses/' + ids[0] + '/application-status', json={'applicationStatus': 'applied'}, headers=h).status_code == 200
    page_ids, cursor = [], None
    while True:
        params = dict(limit=2, verdict='GO', applicationStatus='not_applied', sort=sort)
        if cursor:
            params['cursor'] = cursor
        result = c.get('/v1/history', params=params)
        assert result.status_code == 200, result.text
        page = result.json()
        page_ids.extend(item['analysisId'] for item in page['items'])
        assert page['hasMore'] == (page['nextCursor'] is not None)
        cursor = page['nextCursor']
        if not cursor:
            break
    assert page_ids == sorted(ids[1:], reverse=sort == 'newest')
    assert len(c.get('/v1/history', params={'verdict': 'NO_GO'}).json()['items']) == 2


def test_cursor_tampering_filter_reuse_and_deleted_position(profile_http):
    _, c, _, issued, _ = profile_http
    ids = seed(profile_http, count=3)
    page = c.get('/v1/history', params={'limit': 1}).json()
    cursor = page['nextCursor']
    assert c.get('/v1/history', params={'cursor': cursor + 'x'}).status_code == 400
    assert c.get('/v1/history', params={'cursor': cursor, 'sort': 'oldest'}).status_code == 400
    assert c.get('/v1/history', params={'cursor': cursor, 'verdict': 'GO'}).status_code == 400
    with unit_of_work(profile_http[0].engine) as s:
        s.delete(s.get(AnalysisRecord, UUID(page['items'][0]['analysisId'])))
    rest = c.get('/v1/history', params={'cursor': cursor}).json()
    assert len(rest['items']) == 2


def test_feedback_update_clear_and_independent_application_status(profile_http):
    a, c, _, issued, h = profile_http
    identifier = seed(profile_http, annotation=False)[0]
    base = '/v1/analyses/' + identifier
    feedback = {'correctedScore': 60, 'note': '  Needs experience  '}
    response = c.put(base + '/feedback', json=feedback, headers=h)
    assert response.status_code == 200, response.text
    assert response.json() == {'correctedScore': 60, 'note': 'Needs experience'}
    for status in ['applied', 'replied', 'interview', 'rejected', 'hired', 'not_applied']:
        response = c.put(base + '/application-status', json={'applicationStatus': status}, headers=h)
        assert response.status_code == 200, response.text
        assert c.get(base).json()['applicationStatus'] == status
    assert c.get(base).json()['feedback'] == {'correctedScore': 60, 'note': 'Needs experience'}
    cleared = c.put(base + '/feedback', content='null', headers={**h, 'Content-Type': 'application/json'})
    assert cleared.status_code == 200 and cleared.json() is None
    assert c.get(base).json()['feedback'] is None
    with unit_of_work(a.engine) as s:
        annotation = s.get(AnalysisAnnotation, UUID(identifier))
        assert annotation.feedback_created_at is None and annotation.note is None


@pytest.mark.parametrize('advance_profile_after_admission', [False, True])
def test_reanalysis_current_profile_frozen_memory_idempotency_and_previous_result(profile_http, advance_profile_after_admission):
    a, c, runtime, issued, h = profile_http
    c.app.state.settings.jobs_enabled = True
    identifier = seed(profile_http, url=False)[0]
    base = '/v1/analyses/' + identifier
    assert c.put(base + '/feedback', json={'correctedScore': 40}, headers=h).status_code == 200
    original = c.get(base).json()
    assert save(c, h, '1', preferredRate=70).status_code == 200
    response = c.post(base + '/reanalyses', headers={**h, 'Idempotency-Key': 'reanalysis-1'})
    assert response.status_code == 202, response.text
    job_id = UUID(response.json()['jobId'])
    with unit_of_work(a.engine) as s:
        job = s.get(Job, job_id)
        assert job.input['profileRevision'] == '2'
        assert job.input['profile']['preferredRate'] == 70
        assert 'url' not in job.input['vacancy']
        assert job.input['memory'][0]['correctedScore'] == 40
    if advance_profile_after_admission:
        assert save(c, h, '2', preferredRate=80).status_code == 200
    replay = c.post(base + '/reanalyses', headers={**h, 'Idempotency-Key': 'reanalysis-1'})
    assert replay.json() == response.json()
    assert c.get(base).json()['snapshot']['profileRevision'] == '1'
    # Complete the new job through the actual durable publication path.
    from fitcheck_backend.jobs.envelope import decode_envelope
    from fitcheck_backend.storage.job_queue import JobQueue
    from fitcheck_backend.storage.job_publication import JobPublication
    from fitcheck_backend.analysis.service import AnalysisResult
    from fitcheck_backend.contracts.domain import FitAnalysis
    lease = JobQueue(a.engine).claim()
    with unit_of_work(a.engine) as s:
        envelope = decode_envelope('analysis', s.get(Job, job_id).input)
    snapshot = AnalysisSnapshot(profileRevision='2', profile=envelope.profile, vacancy=envelope.request.vacancy,
        locale='en', promptVersion=envelope.versions.prompt_version,
        schemaVersion=envelope.versions.schema_version, policyVersion=envelope.versions.policy_version)
    analysis = FitAnalysis.model_validate({**DATA['analysis'], 'score': 62, 'status': 'NO_GO'})
    new_id = JobPublication(a.engine).succeed_analysis(lease, AnalysisResult(analysis, snapshot))
    assert new_id is not None
    history = {item['analysisId']: item for item in c.get('/v1/history').json()['items']}
    assert set(history) == {identifier, str(new_id)}
    assert history[identifier]['snapshot'] == original['snapshot']
    assert history[identifier]['analysis'] == original['analysis']
    assert history[identifier]['feedback'] == original['feedback']
    assert history[identifier]['profileChanged'] is True
    updated = c.get('/v1/analyses/' + str(new_id)).json()
    assert history[str(new_id)] == updated
    assert updated['snapshot']['profileRevision'] == '2'
    assert updated['snapshot']['profile']['preferredRate'] == 70
    assert updated['analysis']['score'] == 62
    assert updated['currentProfileRevision'] == ('3' if advance_profile_after_admission else '2')
    assert updated['profileChanged'] is advance_profile_after_admission
    assert c.get('/v1/jobs/' + str(job_id)).status_code == 200
    assert c.delete('/v1/history', headers=h).status_code == 204
    assert c.get('/v1/jobs/' + str(job_id)).status_code == 404
    # Admission replay survives history erasure; it cannot republish a deleted result.
    assert c.post(base + '/reanalyses', headers={**h, 'Idempotency-Key': 'reanalysis-1'}).json() == response.json()


def test_two_accounts_cannot_read_mutate_reanalyze_or_reuse_cursor(profile_http):
    a, c, _, issued, h = profile_http
    ids = seed(profile_http, count=2)
    cursor = c.get('/v1/history', params={'limit': 1}).json()['nextCursor']
    other = a.service.register('other-history@example.com', 'correct horse battery', '127.0.0.2')
    with unit_of_work(a.engine) as s:
        s.get(User, other.principal.user_id).email_verified_at = a.clock()
    c.cookies.set('__Host-fitcheck_session', other.token)
    other_h = {'Origin': WEB, 'X-CSRF-Token': other.csrf_token, 'Idempotency-Key': 'foreign'}
    c.app.state.settings.jobs_enabled = True
    base = '/v1/analyses/' + ids[0]
    assert c.get(base).status_code == 404
    assert c.get('/v1/history').json()['items'] == []
    assert c.get('/v1/history', params={'cursor': cursor}).status_code == 400
    assert c.put(base + '/feedback', json={'correctedScore': 10}, headers=other_h).status_code == 404
    assert c.put(base + '/application-status', json={'applicationStatus': 'hired'}, headers=other_h).status_code == 404
    assert c.post(base + '/reanalyses', headers=other_h).status_code == 404
    assert c.delete('/v1/history', headers=other_h).status_code == 204
    c.cookies.set('__Host-fitcheck_session', issued.token)
    assert len(c.get('/v1/history').json()['items']) == 2


@pytest.mark.parametrize('params', [{'limit': 0}, {'limit': 101}, {'limit': 'x'}, {'cursor': ''},
    {'cursor': 'garbage'}, {'sort': 'score'}, {'verdict': 'maybe'}, {'applicationStatus': 'won'}])
def test_invalid_query(profile_http, params):
    assert profile_http[1].get('/v1/history', params=params).status_code == 400


def test_auth_csrf_input_and_clear_preserves_profile(profile_http):
    a, c, runtime, issued, h = profile_http
    identifier = seed(profile_http)[0]
    base = '/v1/analyses/' + identifier
    assert c.put(base + '/feedback', json={'correctedScore': 10}, headers={'Origin': WEB}).status_code == 403
    assert c.delete('/v1/history', headers={**h, 'Origin': 'https://evil.example.com'}).status_code == 403
    for body in [{'correctedScore': True}, {'correctedScore': 101}, {'correctedScore': 10, 'note': None}, {'correctedScore': 10, 'ownerId': 'forged'}]:
        assert c.put(base + '/feedback', json=body, headers=h).status_code == 400
    assert c.put(base + '/feedback', headers=h).status_code == 400
    assert c.get('/v1/analyses/not-uuid').status_code == 400
    assert c.get('/v1/analyses/' + str(uuid4())).status_code == 404
    assert c.post(base + '/reanalyses', headers={**h, 'Idempotency-Key': 'one'}).status_code == 503
    for _ in range(2):
        assert c.delete('/v1/history', headers=h).status_code == 204
        assert c.get('/v1/history').json() == {'items': [], 'nextCursor': None, 'hasMore': False}
    assert c.get('/v1/profile').json()['revision'] == '1'
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(AnalysisAnnotation)) == 0
        assert s.scalar(select(func.count()).select_from(VacancyRecord)) == 0
    assert c.get(base).status_code == 404
    c.cookies.clear()
    assert c.get('/v1/history').status_code == 401
    c.cookies.set('__Host-fitcheck_session', issued.token)
    with unit_of_work(a.engine) as s:
        s.get(User, issued.principal.user_id).email_verified_at = None
    assert c.get('/v1/history').status_code == 403


def test_revoked_session_cannot_mutate_service(profile_http):
    from fitcheck_backend.auth.errors import AuthError
    _, c, runtime, issued, h = profile_http
    identifier = seed(profile_http)[0]
    principal = runtime.auth.resolve(issued.token, 'web')
    runtime.auth.logout(principal)
    with pytest.raises(AuthError, match='unauthenticated'):
        runtime.history.clear(principal)
    with pytest.raises(AuthError, match='unauthenticated'):
        runtime.jobs.reanalyze(principal=principal, analysis_id=UUID(identifier),
            idempotency_key='revoked', client_ip='127.0.0.1', clock=runtime.clock)


def test_concurrent_partial_annotations_preserve_both_fields(profile_http):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fitcheck_backend.contracts.resources import FeedbackUpdate
    _, _, runtime, issued, _ = profile_http
    identifier = UUID(seed(profile_http, annotation=False)[0])
    principal = runtime.auth.resolve(issued.token, 'web')
    barrier = Barrier(2)
    def update(index):
        barrier.wait(timeout=5)
        if index == 0:
            runtime.history.annotate(principal, identifier, feedback=FeedbackUpdate(correctedScore=55))
        else:
            runtime.history.annotate(principal, identifier, application_status='hired')
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update, [0, 1]))
    value = runtime.history.get(principal, identifier)
    assert value.feedback.corrected_score == 55 and value.application_status == 'hired'


def test_concurrent_reanalysis_replay_and_key_conflicts(profile_http):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fitcheck_backend.contracts.resources import AccountAnalysisStart
    from fitcheck_backend.jobs.errors import JobError
    a, _, runtime, issued, _ = profile_http
    ids = seed(profile_http, count=2)
    principal = runtime.auth.resolve(issued.token, 'web')
    barrier = Barrier(2)
    def admit(_):
        barrier.wait(timeout=5)
        return runtime.jobs.reanalyze(principal=principal, analysis_id=UUID(ids[0]),
            idempotency_key='same-key', client_ip='127.0.0.1', clock=runtime.clock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, [0, 1]))
    assert results[0].job_id == results[1].job_id
    with pytest.raises(JobError, match='conflict'):
        runtime.jobs.reanalyze(principal=principal, analysis_id=UUID(ids[1]),
            idempotency_key='same-key', client_ip='127.0.0.1', clock=runtime.clock)
    with pytest.raises(JobError, match='conflict'):
        runtime.jobs.start_analysis(owner_id=issued.principal.owner_id,
            request=AccountAnalysisStart(mode='account', profileRevision='1', vacancy=DATA['vacancy'], locale='en'),
            idempotency_key='same-key', client_ip='127.0.0.1')
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(Job)) == 1


def test_newer_insert_does_not_repeat_keyset_and_legacy_revision_unknown(profile_http):
    a, c, _, _, _ = profile_http
    ids = seed(profile_http, count=3, url=False)
    page = c.get('/v1/history', params={'limit': 1}).json()
    with unit_of_work(a.engine) as s:
        legacy = s.get(AnalysisRecord, UUID(ids[0]))
        legacy.profile_revision = None
    detail = c.get('/v1/analyses/' + ids[0]).json()
    assert detail['profileChanged'] is None
    assert 'url' not in detail['snapshot']['vacancy']
    seed(profile_http, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    rest = c.get('/v1/history', params={'cursor': page['nextCursor']}).json()
    assert {item['analysisId'] for item in rest['items']} == set(ids) - {page['items'][0]['analysisId']}

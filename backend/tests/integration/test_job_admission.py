from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from dataclasses import replace

import pytest
from sqlalchemy import select, func, delete
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job, Profile
from fitcheck_backend.contracts.resources import SkillSuggestionStart
from fitcheck_backend.jobs.errors import JobError
from job_fixtures import account, request
from analysis_fixtures import DATA

pytestmark = pytest.mark.integration


def service(engine, auth_components):
    from fitcheck_backend.jobs.admission import JobAdmission
    return JobAdmission(engine, auth_components.limiter)


def start(value, owner, key='one', req=None):
    return value.start_analysis(owner_id=owner.id, request=req or request(),
        idempotency_key=key, client_ip='127.0.0.1')


def test_same_key_concurrent_admission_creates_one_job(engine, auth_components):
    owner, _ = account(engine)
    value = service(engine, auth_components)
    barrier = Barrier(2)
    def run():
        barrier.wait(timeout=5)
        return start(value, owner)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert results[0].job_id == results[1].job_id
    with unit_of_work(engine) as s:
        assert s.scalar(select(func.count()).select_from(Job)) == 1
        assert s.get(Job, results[0].job_id).input['profile']['specialization'] == DATA['profile']['specialization']


def test_changed_input_same_key_conflicts(engine, auth_components):
    owner, _ = account(engine)
    value = service(engine, auth_components)
    start(value, owner)
    with pytest.raises(JobError) as exc:
        start(value, owner, req=request(locale='ru'))
    assert exc.value.code == 'conflict'


def test_new_key_creates_new_job(engine, auth_components):
    owner, _ = account(engine)
    value = service(engine, auth_components)
    assert start(value, owner).job_id != start(value, owner, 'two').job_id


def test_duplicate_ignores_changed_profile_memory_policy(engine, auth_components, monkeypatch):
    from fitcheck_backend.storage.profile_repository import update_profile
    from fitcheck_backend.contracts.domain import FreelancerProfile
    from analysis_fixtures import DATA
    owner, _ = account(engine)
    value = service(engine, auth_components)
    original = start(value, owner)
    with unit_of_work(engine) as s:
        saved = s.get(Job, original.job_id).input
        update_profile(s, owner.id, 1, FreelancerProfile.model_validate({**DATA['profile'], 'specialization': 'Changed'}))
        s.delete(s.get(Profile, owner.id))
    # Duplicate must not prepare new inputs or consume a new rate token.
    monkeypatch.setattr(value.limiter, 'enforce', lambda *_: pytest.fail('duplicate consumed rate'))
    monkeypatch.setattr('fitcheck_backend.jobs.admission.get_calibration', lambda *_: pytest.fail('duplicate refreshed memory'))
    monkeypatch.setattr('fitcheck_backend.jobs.admission.execution_versions', lambda *_: pytest.fail('duplicate refreshed policy'))
    assert start(value, owner).job_id == original.job_id
    with unit_of_work(engine) as s:
        assert s.get(Job, original.job_id).input == saved


def test_two_active_jobs_cap_is_atomic(engine, auth_components):
    owner, _ = account(engine)
    value = service(engine, auth_components)
    start(value, owner)
    barrier = Barrier(2)
    def run(key):
        barrier.wait(timeout=5)
        try:
            return start(value, owner, key).status
        except JobError as exc:
            return exc.code
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(run, k) for k in ('two','three')]
        assert sorted(f.result(timeout=10) for f in futures) == ['queued','rate_limited']
    with pytest.raises(JobError):
        value.start_suggestions(owner_id=owner.id, request=SkillSuggestionStart(specialization='Python', locale='en'),
            idempotency_key='suggest', client_ip='127.0.0.1')


def test_foreign_revision_rejected(engine, auth_components):
    owner, _ = account(engine)
    with pytest.raises(JobError) as exc:
        start(service(engine, auth_components), owner, req=request(profileRevision='2'))
    assert exc.value.code == 'not_found'


def test_admission_rollback_has_no_job(engine, auth_components, monkeypatch):
    owner, _ = account(engine)
    value = service(engine, auth_components)
    def fail(*_):
        raise JobError('service_unavailable')
    monkeypatch.setattr('fitcheck_backend.jobs.admission.get_calibration', fail)
    with pytest.raises(JobError):
        start(value, owner)
    with unit_of_work(engine) as s:
        assert s.scalar(select(func.count()).select_from(Job)) == 0

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select, func, update

from fitcheck_backend.contracts.domain import FreelancerProfile
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.models import ProfileRevision, Job, QuotaBucket, QuotaReservation
import json
from pathlib import Path

pytestmark = pytest.mark.integration


def profile():
    return FreelancerProfile.model_validate(json.loads((Path(__file__).parents[1]/"fixtures/domain.json").read_text())["profile"])


def concurrent(call):
    barrier = Barrier(2)
    def run(index):
        barrier.wait(timeout=10)
        return call(index)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, i) for i in range(2)]
        return [future.result(timeout=20) for future in futures]


def test_profile_compare_and_swap(engine, storage_factory):
    from fitcheck_backend.storage.profile_repository import create_profile, update_profile, ProfileRevisionConflict
    with unit_of_work(engine) as session:
        owner = storage_factory(session)[0].id
        create_profile(session, owner, profile())
    def write(index):
        try:
            with unit_of_work(engine) as session:
                return update_profile(session, owner, 1, profile().model_copy(update={"specialization": f"Writer {index}"})).revision
        except ProfileRevisionConflict:
            return "conflict"
    assert sorted(concurrent(write)) == ["2", "conflict"]
    with unit_of_work(engine) as session:
        revisions = session.scalars(select(ProfileRevision).where(ProfileRevision.owner_id==owner).order_by(ProfileRevision.revision)).all()
        assert [r.revision for r in revisions] == [1, 2]
        assert revisions[0].profile["specialization"] == "Frontend developer"


def test_job_idempotency_race(engine, storage_factory):
    from fitcheck_backend.storage.job_repository import get_or_create_job
    with unit_of_work(engine) as session:
        owner = storage_factory(session)[0].id
    def write(index):
        with unit_of_work(engine) as session:
            return get_or_create_job(session, owner, "skill_suggestions", "same-key", {"specialization":"Frontend", "locale":"ru"}).id
    ids = concurrent(write)
    assert ids[0] == ids[1]
    with unit_of_work(engine) as session:
        assert session.scalar(select(func.count()).select_from(Job).where(Job.idempotency_key=="same-key")) == 1


def test_hash_conflict(db_session, storage_factory):
    from fitcheck_backend.storage.job_repository import get_or_create_job, IdempotencyConflict
    owner = storage_factory(db_session)[0].id
    get_or_create_job(db_session, owner, "skill_suggestions", "same", {"specialization":"Frontend", "locale":"ru"})
    with pytest.raises(IdempotencyConflict):
        get_or_create_job(db_session, owner, "skill_suggestions", "same", {"specialization":"Frontend", "locale":"en"})
    # Conflict leaves the caller transaction usable.
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2


def test_quota_capacity_under_concurrent_writes(engine, storage_factory):
    with unit_of_work(engine) as session:
        graph = storage_factory(session)
        owner = graph[0].id
        jobs = [graph[2].id, uuid4()]
        session.add(Job(id=jobs[1], owner_id=owner, type="analysis", input={}, idempotency_key="second", request_hash="a"*64))
        bucket = QuotaBucket(id=uuid4(), owner_id=owner, policy_key="test", window_start=utcnow(), limit=1)
        session.add(bucket)
        session.flush()
        bucket_id = bucket.id
    def reserve(index):
        with unit_of_work(engine) as session:
            changed = session.execute(update(QuotaBucket).where(QuotaBucket.id==bucket_id, QuotaBucket.reserved+QuotaBucket.consumed < QuotaBucket.limit).values(reserved=QuotaBucket.reserved+1)).rowcount
            if changed:
                session.add(QuotaReservation(owner_id=owner, job_id=jobs[index], bucket_id=bucket_id, units=1, status="reserved"))
            return changed
    assert sorted(concurrent(reserve)) == [0, 1]
    with unit_of_work(engine) as session:
        assert session.get(QuotaBucket, bucket_id).reserved == 1
        assert session.scalar(select(func.count()).select_from(QuotaReservation)) == 1

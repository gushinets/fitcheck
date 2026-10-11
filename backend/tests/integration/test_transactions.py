from pathlib import Path
import json

import pytest
from sqlalchemy import select, func
from fitcheck_backend.contracts.domain import FreelancerProfile
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Profile, ProfileRevision, Job, QuotaBucket
from fitcheck_backend.storage.base import utcnow

pytestmark = pytest.mark.integration


def test_unit_of_work_rollback_has_no_partial_records(engine, storage_factory):
    from fitcheck_backend.storage.profile_repository import create_profile
    from fitcheck_backend.storage.job_repository import get_or_create_job
    with unit_of_work(engine) as session:
        owner = storage_factory(session)[0].id
    with pytest.raises(RuntimeError, match="abort"):
        with unit_of_work(engine) as session:
            profile = FreelancerProfile.model_validate(json.loads((Path(__file__).parents[1]/"fixtures/domain.json").read_text())["profile"])
            create_profile(session, owner, profile)
            get_or_create_job(session, owner, "skill_suggestions", "rollback", {"specialization":"Frontend", "locale":"en"})
            session.add(QuotaBucket(owner_id=owner, policy_key="rollback", window_start=utcnow(), limit=1))
            session.flush()
            raise RuntimeError("abort")
    with unit_of_work(engine) as session:
        for model in [Profile, ProfileRevision, QuotaBucket]:
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.scalar(select(func.count()).select_from(Job).where(Job.idempotency_key=="rollback")) == 0

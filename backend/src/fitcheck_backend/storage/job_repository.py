from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from fitcheck_backend.contracts.resources import AnalysisStart, SkillSuggestionStart, LegacyImportRequest
from .models import Job, Owner, Guest
from .payloads import canonical_hash


class IdempotencyConflict(RuntimeError):
    pass


class OwnerUnavailable(RuntimeError):
    pass


def get_or_create_job(session: Session, owner_id: UUID, job_type: Literal["analysis", "skill_suggestions", "import"], idempotency_key: str, input_payload: dict) -> Job:
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 200:
        raise ValueError("Invalid idempotency key")
    dto_types = {"analysis": AnalysisStart, "skill_suggestions": SkillSuggestionStart, "import": LegacyImportRequest}
    if job_type not in dto_types:
        raise ValueError("Unsupported job type")
    payload = dto_types[job_type].model_validate(input_payload).model_dump(mode="json", by_alias=True)
    # KEY SHARE permits concurrent inserts, but serializes with claim/delete's
    # owner FOR UPDATE so a waiter rechecks claim state before creating a job.
    owner = session.scalar(select(Owner).where(Owner.id==owner_id).with_for_update(read=True, key_share=True))
    if owner is None:
        raise OwnerUnavailable("Owner is unavailable")
    if owner.kind == "guest":
        guest = session.scalar(select(Guest).where(Guest.owner_id==owner_id).execution_options(populate_existing=True))
        if guest is None or guest.claimed_by_user_id is not None:
            raise OwnerUnavailable("Guest session has already been claimed")
    if job_type == "analysis" and payload["mode"] != ("guest" if owner.kind == "guest" else "account"):
        raise OwnerUnavailable("Analysis mode does not match owner")
    digest = canonical_hash({"type": job_type, "input": payload})
    inserted = session.scalar(insert(Job).values(owner_id=owner_id, type=job_type, input=payload, idempotency_key=idempotency_key, request_hash=digest).on_conflict_do_nothing(index_elements=[Job.owner_id, Job.type, Job.idempotency_key]).returning(Job.id))
    job = session.get(Job, inserted) if inserted is not None else session.scalar(select(Job).where(Job.owner_id==owner_id, Job.type==job_type, Job.idempotency_key==idempotency_key))
    if job.request_hash != digest:
        raise IdempotencyConflict("Idempotency key was used with different input")
    return job

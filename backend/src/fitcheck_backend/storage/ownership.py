"""Storage primitives only: callers must authenticate and authorize ownership."""
from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .base import utcnow
from .models import Owner, User, Guest, Job, AnalysisRecord, VacancyRecord, AnalysisAnnotation, ProviderCall, QuotaReservation, ImportEntry


class OwnershipConflict(RuntimeError):
    pass


_TRANSFER_CONSTRAINTS = ", ".join(sorted(
    constraint.name
    for model in [AnalysisRecord, AnalysisAnnotation, ProviderCall, ImportEntry]
    for constraint in model.__table__.constraints
    if isinstance(constraint, ForeignKeyConstraint) and constraint.deferrable
))


def transfer_guest_analyses(session: Session, guest_owner_id: UUID, user_owner_id: UUID) -> int:
    try:
        with session.begin_nested():
            owners = session.scalars(select(Owner).where(Owner.id.in_([guest_owner_id, user_owner_id])).order_by(Owner.id).with_for_update()).all()
            kinds = {owner.id: owner.kind for owner in owners}
            if kinds.get(guest_owner_id) != "guest" or kinds.get(user_owner_id) != "user":
                raise OwnershipConflict("Expected a guest and account owner")
            guest = session.scalar(select(Guest).where(Guest.owner_id==guest_owner_id).with_for_update().execution_options(populate_existing=True))
            user = session.scalar(select(User).where(User.owner_id==user_owner_id))
            if guest is None or user is None:
                raise OwnershipConflict("Identity is unavailable")
            if guest.claimed_by_user_id is not None:
                if guest.claimed_by_user_id == user.id:
                    return 0
                raise OwnershipConflict("Guest already belongs to another account")
            jobs = session.scalars(select(Job).where(Job.owner_id==guest_owner_id).with_for_update().execution_options(populate_existing=True)).all()
            if any(job.status not in {"succeeded", "failed"} for job in jobs):
                raise OwnershipConflict("Guest jobs are still active")
            if session.scalar(select(QuotaReservation.id).where(QuotaReservation.owner_id==guest_owner_id, QuotaReservation.status=="reserved").limit(1)) is not None:
                raise OwnershipConflict("Guest quota reservations are still active")
            analyses = session.scalars(select(AnalysisRecord).where(AnalysisRecord.owner_id==guest_owner_id).with_for_update()).all()
            vacancy_ids = {analysis.vacancy_id for analysis in analyses}
            session.execute(text(f"SET CONSTRAINTS {_TRANSFER_CONSTRAINTS} DEFERRED"))
            session.execute(delete(QuotaReservation).where(QuotaReservation.owner_id==guest_owner_id))
            session.execute(update(AnalysisRecord).where(AnalysisRecord.owner_id==guest_owner_id).values(profile_revision=None, owner_id=user_owner_id))
            if vacancy_ids:
                session.execute(update(VacancyRecord).where(VacancyRecord.id.in_(vacancy_ids)).values(owner_id=user_owner_id))
            for model in [Job, AnalysisAnnotation, ProviderCall, ImportEntry]:
                session.execute(update(model).where(model.owner_id==guest_owner_id).values(owner_id=user_owner_id))
            guest.claimed_by_user_id = user.id
            guest.claimed_at = utcnow()
            session.flush()
            # Force the FK graph validation before returning, without a commit.
            session.execute(text(f"SET CONSTRAINTS {_TRANSFER_CONSTRAINTS} IMMEDIATE"))
            return len(analyses)
    except IntegrityError:
        raise OwnershipConflict("Guest data conflicts with account data") from None


def delete_owner(session: Session, owner_id: UUID) -> None:
    # Claimed guest profiles remain private guest data and must disappear with
    # their account; their transferred analyses are owned by the account now.
    user = session.scalar(select(User).where(User.owner_id==owner_id))
    if user is not None:
        guest_owner_ids = session.scalars(select(Guest.owner_id).where(Guest.claimed_by_user_id==user.id)).all()
        ids = [owner_id, *guest_owner_ids]
    else:
        ids = [owner_id]
    session.scalars(select(Owner).where(Owner.id.in_(ids)).order_by(Owner.id).with_for_update()).all()
    for target in [value for value in ids if value != owner_id] + [owner_id]:
        session.execute(delete(Owner).where(Owner.id==target))
    session.flush()

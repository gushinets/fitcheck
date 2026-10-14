from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from fitcheck_backend.contracts.domain import FreelancerProfile
from fitcheck_backend.contracts.resources import ProfileResource
from .models import Profile, ProfileRevision
from .payloads import encode_profile, decode_profile
from ..metrics.lifecycle import append_domain_event, profile_key


class ProfileRevisionConflict(RuntimeError):
    pass


def get_profile(session: Session, owner_id: UUID, revision: int | None = None) -> ProfileResource | None:
    statement = select(ProfileRevision).where(ProfileRevision.owner_id == owner_id)
    if revision is None:
        statement = statement.join(Profile, (Profile.owner_id == ProfileRevision.owner_id)
            & (Profile.current_revision == ProfileRevision.revision))
    else:
        statement = statement.where(ProfileRevision.revision == revision)
    value = session.scalar(statement)
    if value is None:
        return None
    return ProfileResource(revision=str(value.revision), profile=decode_profile(value.profile))


def create_profile(session: Session, owner_id: UUID, profile: FreelancerProfile, *, metrics_environment=None) -> ProfileResource:
    payload = encode_profile(profile)
    inserted = session.scalar(insert(Profile).values(owner_id=owner_id, current_revision=1).on_conflict_do_nothing(index_elements=[Profile.owner_id]).returning(Profile.owner_id))
    if inserted is None:
        raise ProfileRevisionConflict("Profile already exists")
    value = ProfileRevision(owner_id=owner_id, revision=1, profile=payload)
    session.add(value)
    session.flush()
    append_domain_event(session, name="profile_revision_saved", owner_id=owner_id,
        domain_key=profile_key(owner_id, value.revision), occurred_at=value.created_at,
        properties={"revision":value.revision}, environment=metrics_environment)
    return ProfileResource(revision="1", profile=decode_profile(payload))


def update_profile(session: Session, owner_id: UUID, expected_revision: int, profile: FreelancerProfile, *, metrics_environment=None) -> ProfileResource:
    if type(expected_revision) is not int or expected_revision < 1:
        raise ProfileRevisionConflict("Invalid expected profile revision")
    payload = encode_profile(profile)
    # Lock before the no-op check so a concurrent change cannot succeed between
    # comparing the payload and returning the supposedly current revision.
    current = session.scalar(select(Profile).where(Profile.owner_id == owner_id)
        .with_for_update().execution_options(populate_existing=True))
    if current is None or current.current_revision != expected_revision:
        raise ProfileRevisionConflict('Profile revision changed')
    saved = get_profile(session, owner_id, expected_revision)
    if saved.profile.model_dump(mode='json', by_alias=True) == payload:
        return saved
    if expected_revision == 2_147_483_647:
        raise ProfileRevisionConflict('Profile revision counter exhausted')
    new_revision = expected_revision + 1
    changed = session.execute(update(Profile).where(Profile.owner_id==owner_id, Profile.current_revision==expected_revision).values(current_revision=new_revision)).rowcount
    if not changed:
        raise ProfileRevisionConflict("Profile revision changed")
    value = ProfileRevision(owner_id=owner_id, revision=new_revision, profile=payload)
    session.add(value)
    session.flush()
    append_domain_event(session, name="profile_revision_saved", owner_id=owner_id,
        domain_key=profile_key(owner_id, value.revision), occurred_at=value.created_at,
        properties={"revision":value.revision}, environment=metrics_environment)
    return ProfileResource(revision=str(new_revision), profile=decode_profile(payload))

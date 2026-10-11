from uuid import UUID

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from fitcheck_backend.contracts.domain import FreelancerProfile
from fitcheck_backend.contracts.resources import ProfileResource
from .models import Profile, ProfileRevision
from .payloads import encode_profile, decode_profile


class ProfileRevisionConflict(RuntimeError):
    pass


def create_profile(session: Session, owner_id: UUID, profile: FreelancerProfile) -> ProfileResource:
    payload = encode_profile(profile)
    inserted = session.scalar(insert(Profile).values(owner_id=owner_id, current_revision=1).on_conflict_do_nothing(index_elements=[Profile.owner_id]).returning(Profile.owner_id))
    if inserted is None:
        raise ProfileRevisionConflict("Profile already exists")
    session.add(ProfileRevision(owner_id=owner_id, revision=1, profile=payload))
    session.flush()
    return ProfileResource(revision="1", profile=decode_profile(payload))


def update_profile(session: Session, owner_id: UUID, expected_revision: int, profile: FreelancerProfile) -> ProfileResource:
    if type(expected_revision) is not int or expected_revision < 1:
        raise ProfileRevisionConflict("Invalid expected profile revision")
    payload = encode_profile(profile)
    new_revision = expected_revision + 1
    changed = session.execute(update(Profile).where(Profile.owner_id==owner_id, Profile.current_revision==expected_revision).values(current_revision=new_revision)).rowcount
    if not changed:
        raise ProfileRevisionConflict("Profile revision changed")
    session.add(ProfileRevision(owner_id=owner_id, revision=new_revision, profile=payload))
    session.flush()
    return ProfileResource(revision=str(new_revision), profile=decode_profile(payload))

from uuid import uuid4
from analysis_fixtures import DATA
from fitcheck_backend.contracts.domain import FreelancerProfile
from fitcheck_backend.contracts.resources import AccountAnalysisStart
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Owner, User
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.profile_repository import create_profile


def account(engine):
    with unit_of_work(engine) as s:
        owner = Owner(kind='user')
        s.add(owner); s.flush()
        user = User(owner_id=owner.id, normalized_email=f'{uuid4()}@example.com',
            password_hash='unused', email_verified_at=utcnow())
        s.add(user); s.flush()
        create_profile(s, owner.id, FreelancerProfile.model_validate(DATA['profile']))
    return owner, user


def request(**changes):
    return AccountAnalysisStart.model_validate(
        {**dict(mode='account', vacancy=DATA['vacancy'], profileRevision='1', locale='en'), **changes})

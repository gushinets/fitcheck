from contextlib import contextmanager

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .errors import ProfileError
from ..auth.errors import AuthError
from ..auth.access import require_verified
from ..auth.service import active_session
from ..contracts.resources import ProfileComparison, ProfileUpdate, Preferences, DraftResource
from ..storage.auth_repository import AuthRepository
from ..storage.database import unit_of_work
from ..storage.models import User
from ..storage.profile_repository import create_profile, update_profile, get_profile, ProfileRevisionConflict
from ..storage import preferences_repository as preferences


class ProfileService:
    def __init__(self, engine, clock):
        self.engine, self.clock = engine, clock

    @contextmanager
    def _transaction(self, principal, *, mutation=False):
        require_verified(principal)
        try:
            with unit_of_work(self.engine) as session:
                repo = AuthRepository(session)
                user = repo.lock_user(principal.user_id) if mutation else session.get(User, principal.user_id)
                if user is None or user.owner_id != principal.owner_id:
                    raise AuthError('unauthenticated')
                if user.email_verified_at is None:
                    raise AuthError('email_not_verified')
                active_session(repo, principal, self.clock())
                yield session
        except ProfileRevisionConflict:
            raise ProfileError('profile_revision_conflict') from None
        except (SQLAlchemyError, ValidationError):
            raise ProfileError('service_unavailable') from None

    @staticmethod
    def _required_profile(session, owner_id, revision=None):
        result = get_profile(session, owner_id, revision)
        if result is None:
            raise ProfileError('not_found')
        return result

    def get(self, principal, revision=None):
        with self._transaction(principal) as session:
            return self._required_profile(session, principal.owner_id, revision)

    def update(self, principal, value: ProfileUpdate):
        with self._transaction(principal, mutation=True) as session:
            if value.expected_revision is None:
                return create_profile(session, principal.owner_id, value.profile)
            return update_profile(session, principal.owner_id, int(value.expected_revision), value.profile)

    def compare(self, principal, revision):
        with self._transaction(principal) as session:
            saved = self._required_profile(session, principal.owner_id, revision)
            current = self._required_profile(session, principal.owner_id)
            before = saved.profile.model_dump(mode='json', by_alias=True)
            after = current.profile.model_dump(mode='json', by_alias=True)
            changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
            return ProfileComparison(saved=saved, current=current, changedFields=changed)

    def get_preferences(self, principal):
        with self._transaction(principal) as session:
            return preferences.get_preferences(session, principal.owner_id)

    def update_preferences(self, principal, value: Preferences):
        with self._transaction(principal, mutation=True) as session:
            return preferences.save_preferences(session, principal.owner_id, value)

    def get_draft(self, principal):
        with self._transaction(principal) as session:
            return preferences.get_draft(session, principal.owner_id)

    def update_draft(self, principal, value: DraftResource | None):
        with self._transaction(principal, mutation=True) as session:
            return preferences.save_draft(session, principal.owner_id, value)

from datetime import datetime
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from .identity import Owner, User, AuthSession, AuthToken


class AuthRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_user(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.normalized_email == email).execution_options(populate_existing=True))

    def create_user(self, email: str, password_hash: str) -> User:
        owner = Owner(kind='user')
        self.session.add(owner)
        self.session.flush()
        user = User(owner_id=owner.id, normalized_email=email, password_hash=password_hash)
        self.session.add(user)
        self.session.flush()
        return user

    def lock_user(self, user_id: UUID) -> User | None:
        owner_id = self.session.scalar(select(User.owner_id).where(User.id == user_id))
        if owner_id is None:
            return None
        owner = self.session.scalar(select(Owner.id).where(Owner.id == owner_id).with_for_update(read=True, key_share=True))
        if owner is None:
            return None
        return self.session.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))

    def create_session(self, user: User, kind: str, token_digest: str, csrf_digest: str | None, expires_at: datetime) -> AuthSession:
        value = AuthSession(user_id=user.id, kind=kind, token_digest=token_digest, csrf_digest=csrf_digest, expires_at=expires_at)
        self.session.add(value)
        self.session.flush()
        return value

    def session_by_digest(self, digest: str, kind: str, now: datetime) -> AuthSession | None:
        return self.session.scalar(select(AuthSession).join(User, User.id == AuthSession.user_id).where(
            AuthSession.token_digest == digest, AuthSession.kind == kind, AuthSession.expires_at > now,
            AuthSession.revoked_at.is_(None)).execution_options(populate_existing=True))

    def create_token(self, user: User, purpose: str, digest: str, expires_at: datetime) -> AuthToken:
        value = AuthToken(user_id=user.id, purpose=purpose, token_digest=digest, expires_at=expires_at)
        self.session.add(value)
        self.session.flush()
        return value

    def lock_token(self, digest: str, purpose: str) -> AuthToken | None:
        return self.session.scalar(select(AuthToken).where(AuthToken.token_digest == digest,
            AuthToken.purpose == purpose).with_for_update().execution_options(populate_existing=True))

    def invalidate_tokens(self, user_id: UUID, purpose: str, now: datetime) -> None:
        self.session.execute(update(AuthToken).where(AuthToken.user_id == user_id,
            AuthToken.purpose == purpose, AuthToken.consumed_at.is_(None)).values(consumed_at=now))

    def revoke_sessions(self, user_id: UUID, now: datetime, *, session_id: UUID | None = None) -> None:
        query = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        if session_id is not None:
            query = query.where(AuthSession.id == session_id)
        self.session.execute(query.values(revoked_at=now))

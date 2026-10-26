from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class AccessIdentity:
    mode: Literal['account','guest']
    owner_id: UUID
    session_id: UUID
    expires_at: datetime
    user_id: UUID | None = None


@dataclass(frozen=True)
class IssuedGuestSession:
    token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    identity: AccessIdentity

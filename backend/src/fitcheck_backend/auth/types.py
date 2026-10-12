from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    owner_id: UUID
    session_id: UUID
    kind: Literal['web', 'extension']
    email: str = field(repr=False)
    email_verified: bool


@dataclass(frozen=True)
class IssuedSession:
    principal: Principal
    token: str = field(repr=False)
    csrf_token: str | None = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class IssuedCode:
    value: str = field(repr=False)
    state: str
    expires_at: datetime


@dataclass(frozen=True)
class MailMessage:
    recipient: str = field(repr=False)
    purpose: Literal['verify_email', 'reset_password']
    token: str = field(repr=False)

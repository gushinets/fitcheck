from datetime import datetime
from pydantic import Field
from .domain import DTO, text
from typing import Annotated


class GuestSession(DTO):
    csrf_token: text(1024)
    expires_at: datetime
    demo_limit: int = 1


class GuestClaimResult(DTO):
    claimed_count: Annotated[int, Field(strict=True, ge=0)]
    profile_imported: bool = False

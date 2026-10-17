from datetime import datetime
from typing import Annotated, Literal
from pydantic import Field
from .domain import DTO

Count = Annotated[int,Field(strict=True,ge=0)]


class OperationQuota(DTO):
    limit: Count
    remaining: Count
    reserved: Count
    consumed: Count


class QuotaResource(DTO):
    remaining: Count
    resets_at: datetime | None
    mode: Literal['account','guest'] = 'account'
    expires_at: datetime | None = None
    registration_required: bool = False
    active_jobs: Count = 0
    max_active_jobs: Count = 2
    operations: dict[Literal['analysis','suggestions','extraction'],OperationQuota] = Field(default_factory=dict)

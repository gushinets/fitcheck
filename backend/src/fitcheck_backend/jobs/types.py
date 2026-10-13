from dataclasses import dataclass
from uuid import UUID
from typing import Literal


@dataclass(frozen=True)
class AdmissionResult:
    job_id: UUID
    type: str
    status: str


@dataclass(frozen=True)
class JobLease:
    job_id: UUID
    owner_id: UUID
    type: str
    execution_token: UUID
    attempts: int
    input: dict

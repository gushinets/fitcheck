from typing import Annotated, Literal
from pydantic import Field, StrictBool
from ..contracts.domain import DTO, Score, FitBreakdown, text


class RawFitAnalysis(DTO):
    score: Score
    status: Literal['GO', 'NO_GO']
    label: text(80)
    summary: text(800)
    strengths: Annotated[list[text(120)], Field(max_length=3)]
    risks: Annotated[list[text(240)], Field(max_length=3)]
    breakdown: FitBreakdown


class GroundingAudit(DTO):
    supported: StrictBool
    unsupported_claims: Annotated[list[text(500)], Field(max_length=10)]

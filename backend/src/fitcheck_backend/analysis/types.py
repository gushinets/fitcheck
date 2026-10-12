from dataclasses import dataclass
from ..contracts.domain import FreelancerProfile, Vacancy, Locale
from ..storage.calibration_repository import CalibrationEntry


@dataclass(frozen=True)
class AnalysisInput:
    profile: FreelancerProfile
    vacancy: Vacancy
    locale: Locale
    memory: list[CalibrationEntry]


@dataclass(frozen=True)
class StrengthFact:
    id: str
    text: str
    profile_fields: list[str]
    task_fields: list[str]


@dataclass(frozen=True)
class AnalysisPrompt:
    instructions: str
    input: str
    strength_facts: list[StrengthFact]

from typing import Annotated, Literal, get_args
from types import NoneType
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, StrictFloat, StrictInt, field_validator, model_validator, model_serializer
from pydantic.alias_generators import to_camel


def text(max_length: int, min_length: int = 1):
    return Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=min_length, max_length=max_length)]


def number(maximum: float):
    return Annotated[StrictFloat, Field(ge=0, le=maximum, allow_inf_nan=False)]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, serialize_by_alias=True)

    @model_serializer(mode="wrap")
    def omit_absent_fields(self, handler, info):
        result = handler(self)
        for name, field in type(self).model_fields.items():
            # A missing non-nullable field has a sentinel default of None. Explicitly
            # nullable resource fields must retain their null (clear/no next cursor).
            if field.default is None and NoneType not in get_args(field.annotation):
                key = (field.serialization_alias or field.alias or name) if info.by_alias is not False else name
                if result.get(key) is None:
                    result.pop(key, None)
        return result


Locale = Literal["en", "ru"]
Currency = Literal["USD", "EUR", "RUB"]
Skill = text(80)
Identifier = text(200)
Score = Annotated[StrictInt, Field(ge=0, le=100)]
Revision = text(200)
PublicUrl = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]


class FreelancerProfile(DTO):
    specialization: text(120)
    skills: Annotated[list[Skill], Field(min_length=1, max_length=50)]
    skill_levels: dict[Skill, Literal["primary", "confident", "basic"]] = None
    experience_years: number(60)
    preferred_rate: number(100_000_000)
    rate_currency: Currency = None
    work_formats: Annotated[list[Literal["remote", "office", "hybrid"]], Field(min_length=1, max_length=3)]
    english_level: Literal["Basic", "Intermediate", "Upper Intermediate", "Advanced", "Fluent"]

    @model_validator(mode="after")
    def profile_consistency(self):
        if len(set(self.work_formats)) != len(self.work_formats):
            raise ValueError("Work formats must be unique")
        names = {skill.lower() for skill in self.skills}
        if any(key != key.lower() or key not in names for key in self.skill_levels or {}):
            raise ValueError("Skill levels must refer to normalized profile skills")
        return self


class Vacancy(DTO):
    id: Identifier
    url: PublicUrl = None
    title: text(300)
    description: text(20_000)
    skills: Annotated[list[Skill], Field(max_length=100)]
    hourly_rate_min: number(100_000) = None
    hourly_rate_max: number(100_000) = None
    fixed_budget: number(100_000_000) = None
    fixed_budget_max: number(100_000_000) = None
    budget_currency: Currency = None
    experience_level: text(100) = None
    posted_ago: text(100) = None
    client_rating: number(5) = None
    client_spend: number(10_000_000_000) = None

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        # Current job schema accepts an absolute URL; extraction restricts to HTTP(S).
        parsed = urlsplit(value)
        if not parsed.scheme or (parsed.scheme in {"http", "https"} and not parsed.hostname):
            raise ValueError("Expected absolute URL")
        return value


class StrengthEvidence(DTO):
    id: text(120)
    profile_fields: Annotated[list[text(120)], Field(min_length=1)]
    task_fields: Annotated[list[text(120)], Field(min_length=1)]


class FitBreakdown(DTO):
    skills: Score
    experience: Score
    rate: Score
    english: Score
    requirements: Score


class FitAnalysis(DTO):
    score: Score
    status: Literal["GO", "NO_GO"]
    label: text(80)
    summary: text(800)
    strengths: Annotated[list[text(240)], Field(max_length=3)]
    strength_evidence: Annotated[list[StrengthEvidence], Field(max_length=3)] = None
    risks: Annotated[list[text(240)], Field(max_length=3)]
    breakdown: FitBreakdown

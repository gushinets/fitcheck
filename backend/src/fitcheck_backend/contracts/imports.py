"""Bounded local export contracts; row errors are isolated from the envelope."""
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator, field_validator
from .domain import DTO, FreelancerProfile, Vacancy, FitAnalysis, Identifier, Locale, Score


class ImportFeedback(DTO):
    corrected_score: Score
    note: Annotated[str, Field(strict=True, max_length=500)] = None
    created_at: AwareDatetime


class ImportRow(DTO):
    id: Identifier
    created_at: AwareDatetime
    job: Vacancy
    analysis: FitAnalysis
    profile: FreelancerProfile | None = None
    locale: Locale | None = None
    feedback: ImportFeedback | None = None

    @field_validator('profile', mode='before')
    @classmethod
    def legacy_profile(cls, value):
        return normalize_profile(value)


def normalize_profile(value):
    if isinstance(value, dict):
        value = value.copy()
        value.pop('desiredMonthlyIncome', None)
        value.setdefault('workFormats',['remote'])
    return value


def parse_import_row(raw: dict) -> ImportRow:
    return ImportRow.model_validate(raw)


class LocalImportRequest(DTO):
    version: Literal[1]
    source: Literal['website_indexeddb_v1']
    source_user_id: Identifier
    profile: dict | None = None
    locale: Locale | None = None
    history: Annotated[list[dict], Field(max_length=1000)]

    @model_validator(mode='after')
    def unique_ids(self):
        ids=[item['id'] for item in self.history if isinstance(item.get('id'),str)]
        if len(ids)!=len(set(ids)):
            raise ValueError('Duplicate source IDs')
        return self


class LegacyAnalysisSnapshot(DTO):
    origin: Literal['legacy_import'] = 'legacy_import'
    schema_version: Literal['fitcheck.legacy-analysis.v1'] = 'fitcheck.legacy-analysis.v1'
    profile_revision: None = None
    profile: FreelancerProfile | None = None
    vacancy: Vacancy
    locale: Locale | None = None
    prompt_version: None = None
    policy_version: None = None
    evidence_provenance: Literal['unverified_legacy'] = 'unverified_legacy'


ImportOutcome = Literal['imported','skipped','conflict','invalid']


class ImportItemOutcome(DTO):
    index: Annotated[int,Field(strict=True,ge=0)]
    external_id: Identifier | None = None
    outcome: ImportOutcome
    reason: Literal['created','identical','source_changed','invalid_record','invalid_profile','server_exists','absent']


class ImportReport(DTO):
    total_count: Annotated[int,Field(strict=True,ge=0,le=1000)]
    imported_count: Annotated[int,Field(strict=True,ge=0)] = 0
    skipped_count: Annotated[int,Field(strict=True,ge=0)] = 0
    conflict_count: Annotated[int,Field(strict=True,ge=0)] = 0
    invalid_count: Annotated[int,Field(strict=True,ge=0)] = 0
    profile_outcome: ImportOutcome | None = None
    preferences_outcome: ImportOutcome | None = None
    items: Annotated[list[ImportItemOutcome],Field(max_length=1000)] = Field(default_factory=list)

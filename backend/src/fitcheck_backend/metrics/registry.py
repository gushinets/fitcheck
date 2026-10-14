from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, StringConstraints
from ..contracts.domain import DTO, Locale, Score
from .errors import MetricsError

SafeCode = Annotated[str, StringConstraints(strict=True, pattern=r'^[a-z][a-z0-9_]{0,79}$')]
Version = Annotated[str, StringConstraints(strict=True, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,119}$')]
ModelName = Annotated[str, StringConstraints(strict=True, pattern=r'^[a-z][a-z0-9._-]{0,199}$')]
Duration = Annotated[StrictInt, Field(ge=0, le=86_400_000)]


class EmptyProperties(DTO):
    pass


class LocaleProperties(DTO):
    locale: Locale | None = None


class PageProperties(LocaleProperties):
    campaign: SafeCode | None = None


class ActivityProperties(DTO):
    active_ms: Annotated[StrictInt, Field(ge=0, le=30_000)]


class InputProperties(LocaleProperties):
    input_mode: Literal['url', 'text'] | None = None
    platform: Literal['freelancer', 'upwork', 'other', 'text'] | None = None


class ResultProperties(DTO):
    result_id: UUID
    predicted_score: Score | None = None


class FeedbackProperties(ResultProperties):
    predicted_score: Score
    corrected_score: Score


class SkillsProperties(LocaleProperties):
    count: Annotated[StrictInt, Field(ge=0, le=10)] | None = None


class TerminalProperties(DTO):
    outcome: Literal['succeeded', 'failed']
    duration_ms: Duration
    error_code: SafeCode | None = None


class RevisionProperties(DTO):
    revision: Annotated[StrictInt, Field(ge=1)]


class JobProperties(DTO):
    job_type: Literal['analysis', 'skill_suggestions', 'import']
    execution_token: UUID | None = None
    attempts: Annotated[StrictInt, Field(ge=0, le=2)] | None = None


class JobTerminalProperties(JobProperties, TerminalProperties):
    pass


CLIENT = {
    'page_viewed': PageProperties, 'session_started': EmptyProperties,
    'visible_activity': ActivityProperties,
    'local_registration_completed': LocaleProperties, 'local_login_completed': LocaleProperties,
    'profile_saved': LocaleProperties, 'vacancy_input_started': InputProperties,
    'extraction_requested': InputProperties, 'analysis_requested': InputProperties,
    'analysis_result_viewed': ResultProperties, 'skills_requested': LocaleProperties,
    'skills_accepted': SkillsProperties, 'history_viewed': EmptyProperties,
    'feedback_saved': FeedbackProperties, 'history_cleared': EmptyProperties,
    'local_account_deleted': EmptyProperties,
}
WEBSITE_SERVER = {name: TerminalProperties for name in (
    'extraction_finished', 'analysis_finished', 'suggestions_finished')}
BACKEND = {
    'account_registered': EmptyProperties, 'email_verified': EmptyProperties,
    'profile_revision_saved': RevisionProperties,
    'job_admitted': JobProperties, 'job_execution_started': JobProperties,
    'job_execution_recovered': JobProperties, 'job_finished': JobTerminalProperties,
    'account_deleted': EmptyProperties,
}
REGISTRY = CLIENT | WEBSITE_SERVER | BACKEND


def validate_event(event, *, source: str) -> None:
    allowed = {'website_client': CLIENT, 'website_server': WEBSITE_SERVER,
               'backend_server': BACKEND, 'reconstructed_backend': BACKEND}.get(source)
    if allowed is None or event.name not in allowed:
        raise MetricsError('invalid_request')
    expected_kind = 'visitor' if source.startswith('website_') else 'account'
    if event.subject_kind != expected_kind or source.startswith('website_') and event.domain_key is not None:
        raise MetricsError('invalid_request')

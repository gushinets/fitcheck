from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from pydantic import AfterValidator, Field, RootModel, StringConstraints, field_validator
from email_validator import validate_email, EmailNotValidError
from fitcheck_backend.contracts.domain import DTO, FreelancerProfile, Vacancy, FitAnalysis, Identifier, Revision, Locale, Score, Skill, PublicUrl, text


class ProfileResource(DTO):
    revision: Revision
    profile: FreelancerProfile


def valid_profile_revision(value: str) -> str:
    if int(value) > 2_147_483_647:
        raise ValueError('Profile revision exceeds the storage counter')
    return value


ProfileRevisionNumber = Annotated[str, StringConstraints(strict=True, max_length=10,
    pattern=r'^[1-9][0-9]*$'), AfterValidator(valid_profile_revision)]


class ProfileUpdate(DTO):
    expected_revision: ProfileRevisionNumber | None = Field(
        description='Required. Null creates the first profile; otherwise the current revision must match.')
    profile: FreelancerProfile


class ProfileComparison(DTO):
    saved: ProfileResource
    current: ProfileResource
    changed_fields: list[str]


class Preferences(DTO):
    locale: Locale


class DraftResource(DTO):
    vacancy: Vacancy
    locale: Locale


class DraftResponse(RootModel[DraftResource | None]):
    pass


class AccountAnalysisStart(DTO):
    mode: Literal["account"]
    vacancy: Vacancy
    profile_revision: Revision
    locale: Locale


class GuestAnalysisStart(DTO):
    mode: Literal["guest"]
    vacancy: Vacancy
    profile: FreelancerProfile
    locale: Locale


class AnalysisStart(RootModel[Annotated[AccountAnalysisStart | GuestAnalysisStart, Field(discriminator="mode")]]):
    pass


class SkillSuggestionStart(DTO):
    specialization: text(120)
    locale: Locale


ApplicationStatus = Literal["not_applied", "applied", "replied", "interview", "rejected", "hired"]


class FeedbackUpdate(DTO):
    corrected_score: Score
    note: text(500, 0) = None


class FeedbackResponse(RootModel[FeedbackUpdate | None]):
    pass


class ApplicationStatusUpdate(DTO):
    application_status: ApplicationStatus


class AnalysisSnapshot(DTO):
    profile_revision: Revision = Field(json_schema_extra={"readOnly": True})
    profile: FreelancerProfile = Field(json_schema_extra={"readOnly": True})
    vacancy: Vacancy = Field(json_schema_extra={"readOnly": True})
    locale: Locale = Field(json_schema_extra={"readOnly": True})
    prompt_version: text(120) = Field(json_schema_extra={"readOnly": True})
    schema_version: text(120) = Field(json_schema_extra={"readOnly": True})
    policy_version: text(120) = Field(json_schema_extra={"readOnly": True})


from .imports import LegacyAnalysisSnapshot, LocalImportRequest


class AnalysisResource(DTO):
    analysis_id: Identifier
    created_at: datetime
    analysis: FitAnalysis
    snapshot: AnalysisSnapshot | LegacyAnalysisSnapshot
    feedback: FeedbackUpdate | None = None
    application_status: ApplicationStatus = "not_applied"
    current_profile_revision: Revision | None = None
    profile_changed: bool | None = None


class HistoryPage(DTO):
    items: list[AnalysisResource]
    next_cursor: text(2000) | None
    has_more: bool


class ExtractionUrl(DTO):
    type: Literal["url"]
    url: PublicUrl

    @field_validator("url")
    @classmethod
    def http_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Expected public HTTP(S) URL")
        return value


class ExtractionText(DTO):
    type: Literal["text"]
    text: text(20_000)


class ExtractionRequest(RootModel[Annotated[ExtractionUrl | ExtractionText, Field(discriminator="type")]]):
    pass


class ExtractionResponse(DTO):
    vacancy: Vacancy


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid email address')
    try:
        validate_email(value, check_deliverability=False)
    except EmailNotValidError:
        raise ValueError('Invalid email address') from None
    return value


class LoginCredentials(DTO):
    email: text(254)
    password: Annotated[str, Field(strict=True, min_length=1, max_length=128, json_schema_extra={"writeOnly": True})]

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        return normalize_email(value)


class RegistrationCredentials(LoginCredentials):
    password: Annotated[str, Field(strict=True, min_length=15, max_length=128, json_schema_extra={"writeOnly": True})]


class Credentials(RegistrationCredentials):
    """Legacy planned-contract alias; operations switch to distinct DTOs at HTTP integration."""


class PasswordConfirmation(DTO):
    password: Annotated[str, Field(strict=True, min_length=1, max_length=128, json_schema_extra={"writeOnly": True})]


class EmailRequest(DTO):
    email: text(254)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        return normalize_email(value)


class TokenRequest(DTO):
    token: text(1024)


class PasswordResetConfirm(TokenRequest):
    password: Annotated[str, Field(strict=True, min_length=15, max_length=128, json_schema_extra={"writeOnly": True})]


class UserResource(DTO):
    id: Identifier
    email: text(254)
    email_verified: bool


class SessionResource(DTO):
    user: UserResource
    csrf_token: text(1024)


class CsrfResource(DTO):
    csrf_token: text(1024)


from .guests import GuestSession, GuestClaimResult
from .quotas import QuotaResource


class LegacyProfile(FreelancerProfile):
    desired_monthly_income: object = Field(default=None, exclude=True, deprecated=True,
                                          description="Legacy import only; ignored, never persisted")


class LegacyFeedback(FeedbackUpdate):
    created_at: datetime


class LegacyHistoryEntry(DTO):
    id: Identifier
    job_title: text(300)
    score: Score
    status: Literal["GO", "NO_GO"]
    timestamp: text(200)
    created_at: datetime
    analysis: FitAnalysis
    job: Vacancy
    feedback: LegacyFeedback = None


LegacyImportRequest = LocalImportRequest


class EmptyRequest(DTO):
    pass

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from pydantic import Field, RootModel, field_validator
from fitcheck_backend.contracts.domain import DTO, FreelancerProfile, Vacancy, FitAnalysis, Identifier, Revision, Locale, Score, Skill, PublicUrl, text


class ProfileResource(DTO):
    revision: Revision
    profile: FreelancerProfile


class ProfileUpdate(DTO):
    expected_revision: Revision
    profile: FreelancerProfile


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


class AnalysisResource(DTO):
    analysis_id: Identifier
    created_at: datetime
    analysis: FitAnalysis
    snapshot: AnalysisSnapshot
    feedback: FeedbackUpdate | None = None
    application_status: ApplicationStatus = "not_applied"


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


class Credentials(DTO):
    email: text(254)
    password: Annotated[str, Field(strict=True, min_length=8, max_length=128, json_schema_extra={"writeOnly": True})]

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if value.count("@") != 1 or not all(value.split("@")) or any(c.isspace() for c in value):
            raise ValueError("Expected email address")
        return value


class EmailRequest(DTO):
    email: text(254)


class TokenRequest(DTO):
    token: text(1024)


class PasswordResetConfirm(TokenRequest):
    password: Annotated[str, Field(strict=True, min_length=8, max_length=128, json_schema_extra={"writeOnly": True})]


class UserResource(DTO):
    id: Identifier
    email: text(254)
    email_verified: bool


class SessionResource(DTO):
    user: UserResource
    csrf_token: text(1024)


class ExtensionAuthorize(DTO):
    redirect_uri: PublicUrl
    code_challenge: Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{43}$")]
    code_challenge_method: Literal["S256"]
    state: text(200)


class ExtensionCode(DTO):
    code: text(1024)
    state: text(200)
    expires_in: Annotated[int, Field(strict=True, ge=1)]


class ExtensionTokenRequest(DTO):
    code: text(1024)
    code_verifier: Annotated[str, Field(strict=True, min_length=43, max_length=128, pattern=r"^[A-Za-z0-9._~-]+$")]
    redirect_uri: PublicUrl


class ExtensionToken(DTO):
    access_token: text(4096)
    token_type: Literal["Bearer"]
    expires_in: Annotated[int, Field(strict=True, ge=1)]


class GuestSession(DTO):
    csrf_token: text(1024)
    expires_at: datetime


class QuotaResource(DTO):
    remaining: Annotated[int, Field(strict=True, ge=0)]
    resets_at: datetime | None


class GuestClaimResult(DTO):
    claimed_count: Annotated[int, Field(strict=True, ge=0)]


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


class LegacyImportRequest(DTO):
    version: Literal[1]
    profile: LegacyProfile = None
    history: Annotated[list[LegacyHistoryEntry], Field(max_length=1000)]


class EmptyRequest(DTO):
    pass

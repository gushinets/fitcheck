from dataclasses import dataclass
from pydantic import BaseModel
from fitcheck_backend.contracts import resources as r
from fitcheck_backend.contracts import jobs as j


@dataclass(frozen=True)
class OperationSpec:
    method: str
    path: str
    operation_id: str
    owner: str
    response: type[BaseModel] | None = None
    request: type[BaseModel] | None = None
    status: int = 200
    access: str = "account"
    idempotent: bool = False


PLANNED_OPERATIONS = [
    OperationSpec("post", "/v1/auth/register", "register", "ANY-645", r.SessionResource, r.Credentials, 201, "public"),
    OperationSpec("post", "/v1/auth/login", "login", "ANY-645", r.SessionResource, r.Credentials, access="public"),
    OperationSpec("post", "/v1/auth/logout", "logout", "ANY-645", status=204, access="web"),
    OperationSpec("post", "/v1/auth/verify-email", "verifyEmail", "ANY-645", request=r.TokenRequest, status=204, access="public"),
    OperationSpec("post", "/v1/auth/password-reset/request", "requestPasswordReset", "ANY-645", request=r.EmailRequest, status=204, access="public"),
    OperationSpec("post", "/v1/auth/password-reset/confirm", "confirmPasswordReset", "ANY-645", request=r.PasswordResetConfirm, status=204, access="public"),
    OperationSpec("get", "/v1/me", "getMe", "ANY-645", r.UserResource),
    OperationSpec("delete", "/v1/me", "deleteMe", "ANY-645", status=204),
    OperationSpec("post", "/v1/auth/extension/authorize", "authorizeExtension", "ANY-645", r.ExtensionCode, r.ExtensionAuthorize, access="web"),
    OperationSpec("post", "/v1/auth/extension/token", "exchangeExtensionCode", "ANY-645", r.ExtensionToken, r.ExtensionTokenRequest, access="public"),
    OperationSpec("post", "/v1/auth/extension/revoke", "revokeExtensionToken", "ANY-645", status=204, access="extension"),
    OperationSpec("get", "/v1/profile", "getProfile", "ANY-646", r.ProfileResource),
    OperationSpec("put", "/v1/profile", "updateProfile", "ANY-646", r.ProfileResource, r.ProfileUpdate),
    OperationSpec("get", "/v1/preferences", "getPreferences", "ANY-646", r.Preferences),
    OperationSpec("put", "/v1/preferences", "updatePreferences", "ANY-646", r.Preferences, r.Preferences),
    OperationSpec("get", "/v1/draft", "getDraft", "ANY-646", r.DraftResponse),
    OperationSpec("put", "/v1/draft", "updateDraft", "ANY-646", r.DraftResponse, r.DraftResponse),
    OperationSpec("delete", "/v1/draft", "deleteDraft", "ANY-646", status=204),
    OperationSpec("post", "/v1/extractions", "extractVacancy", "ANY-647", r.ExtractionResponse, r.ExtractionRequest, access="identity"),
    OperationSpec("post", "/v1/skill-suggestion-jobs", "startSkillSuggestions", "ANY-648/649", j.JobReference, r.SkillSuggestionStart, 202, "identity", True),
    OperationSpec("post", "/v1/analysis-jobs", "startAnalysis", "ANY-649", j.JobReference, r.AnalysisStart, 202, "identity", True),
    OperationSpec("get", "/v1/jobs/{jobId}", "getJob", "ANY-649", j.JobState, access="identity"),
    OperationSpec("get", "/v1/analyses/{analysisId}", "getAnalysis", "ANY-650", r.AnalysisResource, access="identity"),
    OperationSpec("get", "/v1/history", "getHistory", "ANY-650", r.HistoryPage),
    OperationSpec("put", "/v1/analyses/{analysisId}/feedback", "updateFeedback", "ANY-650", r.FeedbackResponse, r.FeedbackResponse),
    OperationSpec("put", "/v1/analyses/{analysisId}/application-status", "updateApplicationStatus", "ANY-650", r.ApplicationStatusUpdate, r.ApplicationStatusUpdate),
    OperationSpec("post", "/v1/analyses/{analysisId}/reanalyses", "reanalyze", "ANY-650", j.JobReference, status=202, idempotent=True),
    OperationSpec("delete", "/v1/history", "clearHistory", "ANY-650", status=204),
    OperationSpec("post", "/v1/guest-sessions", "createGuestSession", "ANY-651", r.GuestSession, status=201, access="public"),
    OperationSpec("get", "/v1/quota", "getQuota", "ANY-651", r.QuotaResource, access="identity"),
    OperationSpec("post", "/v1/guest-claims", "claimGuestData", "ANY-651", r.GuestClaimResult, access="claim", idempotent=True),
    OperationSpec("post", "/v1/import-jobs", "startImport", "ANY-652", j.ImportReference, r.LegacyImportRequest, 202, idempotent=True),
    OperationSpec("get", "/v1/import-jobs/{importId}", "getImport", "ANY-652", j.ImportState),
]

# Preserve UI-localized error codes while assigning stable HTTP semantics during migration.
LEGACY_ERROR_STATUS = {
    "rate_limit": 429, "timeout": 504, "invalid_output": 502, "upstream": 502,
    "invalid_url": 400, "blocked_address": 403, "redirect_limit": 502,
    "unsupported_content": 415, "response_too_large": 413, "fetch_failed": 502,
}

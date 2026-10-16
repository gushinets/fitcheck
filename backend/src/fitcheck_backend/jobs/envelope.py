from copy import deepcopy
from typing import Literal
from pydantic import ValidationError, Field
from ..contracts.domain import DTO, FreelancerProfile, text
from ..contracts.resources import AccountAnalysisStart, SkillSuggestionStart
from ..storage.calibration_repository import CalibrationEntry
from ..llm.policy import analysis_policy, suggestion_policy
from ..analysis.prompt import PROMPT_VERSION, AUDIT_PROMPT_VERSION
from ..skill_suggestions.prompt import PROMPT_VERSION as SKILLS_PROMPT_VERSION
from .errors import JobError


class ExecutionVersions(DTO):
    provider: text(120)
    model: text(200)
    prompt_version: text(120)
    schema_version: text(120)
    policy_version: text(120)
    audit_prompt_version: text(120) | None = None
    audit_schema_version: text(120) | None = None


class AnalysisEnvelope(DTO):
    envelope_version: Literal[1]
    request: AccountAnalysisStart
    profile: FreelancerProfile
    memory: list[CalibrationEntry] = Field(max_length=10)
    versions: ExecutionVersions


class SuggestionsEnvelope(DTO):
    envelope_version: Literal[1]
    request: SkillSuggestionStart
    versions: ExecutionVersions


def execution_versions(job_type: str, *, model: str = 'gpt-6-luna') -> ExecutionVersions:
    if job_type not in {'analysis', 'skill_suggestions'}:
        raise JobError('invalid_request')
    policy = analysis_policy(model) if job_type == 'analysis' else suggestion_policy(model)
    return ExecutionVersions(provider=policy.provider, model=policy.model,
        promptVersion=PROMPT_VERSION if job_type == 'analysis' else SKILLS_PROMPT_VERSION,
        schemaVersion=policy.schema_version, policyVersion=policy.policy_version,
        auditPromptVersion=AUDIT_PROMPT_VERSION if job_type == 'analysis' else None,
        auditSchemaVersion=policy.audit_schema_version if job_type == 'analysis' else None)


def decode_envelope(job_type: str, payload: dict) -> AnalysisEnvelope | SuggestionsEnvelope:
    kind = {'analysis': AnalysisEnvelope, 'skill_suggestions': SuggestionsEnvelope}.get(job_type)
    if kind is None:
        raise JobError('invalid_request')
    try:
        return kind.model_validate(deepcopy(payload))
    except (ValidationError, ValueError, TypeError):
        raise JobError('invalid_request') from None


def validate_supported_versions(envelope: AnalysisEnvelope | SuggestionsEnvelope, *, model: str = 'gpt-6-luna') -> None:
    job_type = 'analysis' if isinstance(envelope, AnalysisEnvelope) else 'skill_suggestions'
    if envelope.versions != execution_versions(job_type, model=model):
        raise JobError('service_unavailable')

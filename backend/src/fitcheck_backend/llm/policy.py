from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPolicy:
    name: str
    provider: str = 'deepseek'
    model: str = 'deepseek-v4-flash'
    gateway_model: str = 'deepseek/deepseek-v4-flash'
    schema_version: str = 'fitcheck.analysis.v1'
    policy_version: str = 'fitcheck.llm.policy.v1'
    transport_attempts: int = 2
    semantic_attempts: int = 2
    max_calls: int = 8
    deadline_seconds: float = 120
    attempt_seconds: float = 45
    max_tokens: int = 1200
    audit_max_tokens: int = 1000
    audit_schema_version: str = 'fitcheck.grounding.v1'


def analysis_policy() -> ProviderPolicy:
    return ProviderPolicy('analysis')


def suggestion_policy() -> ProviderPolicy:
    return ProviderPolicy('skill_suggestions', schema_version='fitcheck.skills.v1',
        max_calls=4, deadline_seconds=60, max_tokens=500)

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPolicy:
    name: str
    provider: str = 'openai'
    model: str = 'gpt-6-luna'
    gateway_model: str = 'openai/gpt-6-luna'
    schema_version: str = 'fitcheck.analysis.v1'
    policy_version: str = 'fitcheck.llm.policy.v2'
    transport_attempts: int = 2
    semantic_attempts: int = 2
    max_calls: int = 8
    deadline_seconds: float = 120
    attempt_seconds: float = 45
    max_tokens: int = 1200
    audit_max_tokens: int = 1000
    audit_schema_version: str = 'fitcheck.grounding.v1'


def resolve_model(model: str) -> str:
    if model != 'gpt-6-luna':
        raise ValueError('Unsupported provider model')
    return model


def analysis_policy(model: str = 'gpt-6-luna') -> ProviderPolicy:
    return ProviderPolicy('analysis', model=resolve_model(model), gateway_model=f'openai/{model}')


def suggestion_policy(model: str = 'gpt-6-luna') -> ProviderPolicy:
    return ProviderPolicy('skill_suggestions', model=resolve_model(model), gateway_model=f'openai/{model}', schema_version='fitcheck.skills.v1',
        max_calls=4, deadline_seconds=60, max_tokens=500)

from datetime import datetime, UTC
from uuid import uuid4

import pytest
from pydantic import ValidationError

from fitcheck_backend.metrics.contracts import MetricEvent, WebsiteAttempt
from fitcheck_backend.metrics.registry import validate_event


def event(name='profile_saved', **overrides):
    return dict(eventId=str(uuid4()), name=name, schemaVersion=1,
                occurredAt='2026-10-14T10:00:00Z', subjectId=str(uuid4()),
                properties={}) | overrides


def test_registry_rejects_pii_unknown_names_and_forged_fact_properties():
    for properties in ({'ownerId': str(uuid4())}, {'cost': 1}, {'note': 'private'},
                       {'utmSource': 'private@example.com'}):
        with pytest.raises(ValidationError):
            MetricEvent.model_validate(event(properties=properties))
    with pytest.raises(ValidationError):
        MetricEvent.model_validate(event(name='arbitrary_event'))
    for score in (0, 100):
        value = MetricEvent.model_validate(event(name='feedback_saved', properties={
            'resultId': str(uuid4()), 'predictedScore': score, 'correctedScore': score}))
        validate_event(value, source='website_client')
    for score in (-1, 101, True):
        with pytest.raises(ValidationError):
            MetricEvent.model_validate(event(name='feedback_saved', properties={
                'resultId': str(uuid4()), 'predictedScore': 50, 'correctedScore': score}))


def test_client_cannot_assert_server_fact_or_account_identity():
    from fitcheck_backend.metrics.errors import MetricsError
    value = MetricEvent.model_validate(event(name='analysis_finished', properties={
        'outcome': 'succeeded', 'durationMs': 10}))
    with pytest.raises(MetricsError):
        validate_event(value, source='website_client')
    value = MetricEvent.model_validate(event(subjectKind='account'))
    with pytest.raises(MetricsError):
        validate_event(value, source='website_client')


def test_event_requires_aware_time_and_supported_schema():
    for overrides in ({'occurredAt': '2026-10-14T10:00:00'}, {'schemaVersion': 2}, {'schemaVersion': True}):
        with pytest.raises(ValidationError):
            MetricEvent.model_validate(event(**overrides))


def test_attempt_requires_safe_usage_and_matching_currency():
    values = dict(callId=str(uuid4()), operationId=str(uuid4()), subjectId=str(uuid4()),
                  purpose='analysis.generate', ordinal=1, provider='openai', model='gpt-6-luna',
                  startedAt='2026-10-14T10:00:00Z', state='started',
                  promptVersion='prompt.v1', policyVersion='policy.v2')
    assert WebsiteAttempt.model_validate(values).input_tokens is None
    for overrides in ({'inputTokens': -1}, {'inputTokens': True}, {'cost': '0.01'},
                      {'state': 'succeeded'}, {'model': 'private@example.com'},
                      {'startedAt': '2026-10-14T10:00:00'}):
        with pytest.raises(ValidationError):
            WebsiteAttempt.model_validate(values | overrides)


def test_metrics_error_never_exposes_unsafe_content():
    from fitcheck_backend.metrics.errors import MetricsError
    error = MetricsError('private@example.com credentials')
    assert error.code == str(error) == 'invalid_request'

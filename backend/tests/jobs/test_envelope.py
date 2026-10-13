from copy import deepcopy

import pytest
from pydantic import ValidationError
from analysis_fixtures import DATA


def payload():
    return dict(envelopeVersion=1,
        request=dict(mode='account', vacancy=deepcopy(DATA['vacancy']), profileRevision='1', locale='en'),
        profile=deepcopy(DATA['profile']), memory=[],
        versions=dict(provider='deepseek', model='deepseek-v4-flash',
            promptVersion='fitcheck.analysis.prompt.v1', auditPromptVersion='fitcheck.analysis.audit.v1',
            schemaVersion='fitcheck.analysis.v1', auditSchemaVersion='fitcheck.grounding.v1',
            policyVersion='fitcheck.llm.policy.v1'))


def test_envelope_rejects_unknown_version():
    from fitcheck_backend.jobs.envelope import decode_envelope, validate_supported_versions
    from fitcheck_backend.jobs.errors import JobError
    value = payload()
    value['versions']['policyVersion'] = 'unknown'
    with pytest.raises(JobError):
        validate_supported_versions(decode_envelope('analysis', value))
    value['envelopeVersion'] = 2
    with pytest.raises(JobError):
        decode_envelope('analysis', value)


def test_envelope_copies_inputs():
    from fitcheck_backend.jobs.envelope import decode_envelope
    value = payload()
    envelope = decode_envelope('analysis', value)
    value['request']['vacancy']['title'] = 'Changed'
    value['profile']['specialization'] = 'Changed'
    assert envelope.request.vacancy.title == DATA['vacancy']['title']
    assert envelope.profile.specialization == DATA['profile']['specialization']


def test_legacy_payload_fails_before_http():
    from fitcheck_backend.jobs.envelope import decode_envelope
    from fitcheck_backend.jobs.errors import JobError
    with pytest.raises(JobError):
        decode_envelope('analysis', payload()['request'])


def test_extra_envelope_fields_rejected():
    from fitcheck_backend.jobs.envelope import decode_envelope
    from fitcheck_backend.jobs.errors import JobError
    with pytest.raises(JobError):
        decode_envelope('analysis', {**payload(), 'secretOverride': True})

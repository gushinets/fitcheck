import pytest
from pydantic import ValidationError
from fitcheck_backend.contracts.jobs import JobState


def test_analysis_success_requires_embedded_result():
    with pytest.raises(ValidationError):
        JobState.model_validate(dict(jobId='job-1',type='analysis',status='succeeded',analysisId='analysis-1'))


def test_failed_job_has_no_input_or_snapshot():
    value = dict(jobId='job-1',type='analysis',status='failed',error=dict(code='timeout',message='Timeout',requestId='job-1',details=[]))
    assert set(JobState.model_validate(value).model_dump()) == {'jobId','type','status','error'}
    with pytest.raises(ValidationError): JobState.model_validate({**value,'snapshot':{}})

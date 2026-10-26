import pytest
from pydantic import ValidationError


@pytest.mark.parametrize('changes', [{'heartbeat_seconds':150},{'lease_seconds':149},
    {'poll_interval':float('nan')},{'drain_seconds':float('inf')},{'poll_interval':0}])
def test_invalid_worker_timing_rejected(changes):
    from fitcheck_backend.worker.settings import WorkerSettings
    with pytest.raises(ValidationError): WorkerSettings(**changes)

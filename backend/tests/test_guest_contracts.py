import pytest
from pydantic import ValidationError


def test_quota_distinguishes_reserved_and_consumed():
    from fitcheck_backend.contracts.quotas import OperationQuota, QuotaResource
    resource = QuotaResource(mode='guest',remaining=0,resetsAt=None,expiresAt='2026-10-18T00:00:00Z',
        registrationRequired=True,activeJobs=1,maxActiveJobs=1,
        operations={'analysis':OperationQuota(limit=1,remaining=0,reserved=1,consumed=0)})
    assert resource.model_dump(mode='json')['operations']['analysis'] == dict(limit=1,remaining=0,reserved=1,consumed=0)
    with pytest.raises(ValidationError):
        OperationQuota(limit=1,remaining=-1,reserved=0,consumed=0)


def test_guest_profile_import_is_explicit():
    from fitcheck_backend.contracts.guests import GuestClaimResult
    assert GuestClaimResult(claimedCount=1,profileImported=True).profile_imported is True


def test_unlimited_quota_is_explicit_null_with_usage_preserved():
    from fitcheck_backend.contracts.quotas import OperationQuota, QuotaResource
    quota = OperationQuota(limit=None, remaining=None, reserved=2, consumed=25)
    resource = QuotaResource(remaining=None, resetsAt=None, operations={'analysis': quota})
    assert resource.model_dump(mode='json')['operations']['analysis'] == dict(limit=None, remaining=None, reserved=2, consumed=25)
    assert resource.remaining is None and not resource.registration_required
    with pytest.raises(ValidationError):
        OperationQuota(limit=None, remaining=None, reserved=-1, consumed=0)

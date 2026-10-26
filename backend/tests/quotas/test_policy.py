from decimal import Decimal
import pytest
from pydantic import ValidationError
from fitcheck_backend.config import Settings


def test_approved_defaults():
    from fitcheck_backend.quotas.policy import QuotaPolicy
    policy = QuotaPolicy.from_settings(Settings())
    assert policy.limits('guest').analysis == 1
    assert policy.limits('guest').suggestions == 5
    assert policy.limits('guest').extraction == 10
    assert policy.limits('guest').max_active_jobs == 1
    assert policy.limits('account').analysis == 20
    assert policy.limits('account').suggestions == 50
    assert policy.limits('account').extraction == 100
    assert policy.limits('account').max_active_jobs == 2
    assert policy.guest_ttl_seconds == 86400
    assert policy.analysis_calls == 8 and policy.suggestions_calls == 4
    assert policy.analysis_tokens == 40000 and policy.suggestions_tokens == 10000
    assert policy.analysis_usd == Decimal('0.02')
    assert policy.suggestions_usd == Decimal('0.005')
    assert policy.guest_usd == Decimal('0.05') and policy.account_daily_usd == Decimal('0.50')
    assert policy.deployment_daily_usd == Decimal('10.00')


@pytest.mark.parametrize('name,value', [('guest_demo_limit',0),('guest_ttl_seconds',-1),
    ('guest_demo_limit',True),('budget_analysis_usd','NaN'),('budget_analysis_usd','Infinity'),
    ('budget_deployment_daily_usd',0),('budget_analysis_calls',True),('guest_create_daily_limit',-1)])
def test_invalid_policy_fails_at_configuration(name,value):
    with pytest.raises(ValidationError):
        Settings(**{name:value})


def test_policy_overrides_are_validated_and_used():
    from fitcheck_backend.quotas.policy import QuotaPolicy
    p = QuotaPolicy.from_settings(Settings(guest_demo_limit=3, budget_guest_usd='0.10'))
    assert p.limits('guest').analysis == 3 and p.guest_usd == Decimal('0.10')

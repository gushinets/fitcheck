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
    ('budget_analysis_usd',0),('budget_analysis_calls',True),('guest_create_daily_limit',-1)])
def test_invalid_policy_fails_at_configuration(name,value):
    with pytest.raises(ValidationError):
        Settings(**{name:value})


def test_policy_overrides_are_validated_and_used():
    from fitcheck_backend.quotas.policy import QuotaPolicy
    p = QuotaPolicy.from_settings(Settings(guest_demo_limit=3, budget_guest_usd='0.10'))
    assert p.limits('guest').analysis == 3 and p.guest_usd == Decimal('0.10')


@pytest.mark.parametrize('value', [None, 0, '0'])
def test_explicit_unlimited_daily_policy_preserves_guest_and_job_limits(value):
    from fitcheck_backend.quotas.policy import QuotaPolicy
    p = QuotaPolicy.from_settings(Settings(account_analysis_daily_limit=value,
        budget_account_daily_usd=value, budget_deployment_daily_usd=value))
    assert p.account.analysis is None
    assert p.account_daily_usd is None and p.deployment_daily_usd is None
    assert p.guest.analysis == 1 and p.guest_usd == Decimal('0.05')
    assert p.account.max_active_jobs == 2 and p.analysis_calls == 8
    assert p.analysis_usd == Decimal('0.02')


@pytest.mark.parametrize('name', ['account_analysis_daily_limit', 'budget_account_daily_usd', 'budget_deployment_daily_usd'])
@pytest.mark.parametrize('value', [-1, True, False, '', 'none', 'unlimited'])
def test_unlimited_settings_reject_ambiguous_or_invalid_limits(name, value):
    with pytest.raises(ValidationError):
        Settings(**{name: value})


def test_unlimited_environment_values(monkeypatch):
    for name in ('ACCOUNT_ANALYSIS_DAILY_LIMIT', 'BUDGET_ACCOUNT_DAILY_USD', 'BUDGET_DEPLOYMENT_DAILY_USD'):
        monkeypatch.setenv('FITCHECK_' + name, '0')
    settings = Settings()
    assert settings.account_analysis_daily_limit is None
    assert settings.budget_account_daily_usd is None and settings.budget_deployment_daily_usd is None

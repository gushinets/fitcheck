import json
from decimal import Decimal
from pathlib import Path

import pytest
from fitcheck_backend.llm.pricing import ProviderUsage, estimate_openai_cost, RATE_VERSION


def estimate(usage=ProviderUsage(100, 20, 40, 10, 5), **kwargs):
    return estimate_openai_cost(usage, **({'model':'gpt-6-luna', 'rate_version':RATE_VERSION,
        'service_tier':'default', 'processing_region':'global'} | kwargs))


def test_cached_input_not_charged_as_uncached():
    assert estimate().amount == Decimal('0.00001665')


def test_reasoning_output_not_double_counted():
    assert estimate().amount == estimate(ProviderUsage(100,20,40,10,0)).amount


@pytest.mark.parametrize('usage,kwargs,reason', [
    (ProviderUsage(1,1,None,0), {}, 'missing_cache_usage'),
    (ProviderUsage(1,1,0,None), {}, 'missing_cache_usage'),
    (ProviderUsage(1,1,0,0), {'service_tier':None}, 'unsupported_service_tier'),
    (ProviderUsage(1,1,0,0), {'service_tier':'auto'}, 'unsupported_service_tier'),
    (ProviderUsage(1,1,0,0), {'processing_region':'eu'}, 'unsupported_processing_region'),
    (ProviderUsage(272001,1,0,0), {}, 'unsupported_large_context'),
    (ProviderUsage(True,1,0,0), {}, 'invalid_usage'),
    (ProviderUsage(1,1,1,1), {}, 'invalid_usage'),
    (ProviderUsage(1,1,0,0,2), {}, 'invalid_usage'),
    (ProviderUsage(1,1,0,0), {'model':'gpt-6.1-luna'}, 'unsupported_model'),
    (ProviderUsage(1,1,0,0), {'rate_version':'future'}, 'unsupported_rate_version'),
])
def test_unknown_cache_or_tier_returns_unknown_not_zero(usage,kwargs,reason):
    result = estimate(usage,**kwargs)
    assert result.amount is None and result.currency is None and result.basis == 'unknown'
    assert result.reason == reason


def test_ts_python_price_fixture_parity():
    cases=json.loads((Path(__file__).parents[1]/'fixtures/openai_pricing.json').read_text())
    for case in cases:
        result=estimate(ProviderUsage(**case['usage']), **case.get('options',{}))
        assert (format(result.amount,'f') if result.amount is not None else None) == case['amount'], case['name']
        assert result.reason == case.get('reason'), case['name']

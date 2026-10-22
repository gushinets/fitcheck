import asyncio
import json

import pytest

from analysis_fixtures import DATA, input_value
from llm_fakes import components
from fitcheck_backend.analysis.executor import AnalysisExecutor
from fitcheck_backend.analysis.normalize import normalize_analysis
from fitcheck_backend.analysis.schemas import RawFitAnalysis
from fitcheck_backend.llm.errors import LlmError
from fitcheck_backend.llm.types import ProviderReply

RISK = 'The client requires Spanish calls; Spanish proficiency is not established by the profile.'
CLAUSE = 'the client agrees to communicate in English'
CONDITION = {'clause': CLAUSE, 'riskIndex': 0}


def raw(**changes):
    return {**DATA['analysis'], 'score': 80, 'strengths': [], 'risks': [RISK], 'fitCondition': CONDITION, **changes}


def reply(value):
    return ProviderReply(json.dumps(value), 12, 4, None, None)


def execute(values, *, locale='en'):
    gateway, context, ledger, adapter = components([reply(value) for value in values])
    value = input_value(locale=locale, vacancy={'description': 'Build a React dashboard. Client communication requires Spanish calls.'})
    result = asyncio.run(AnalysisExecutor(gateway).run(context, value))
    return result, ledger, adapter


@pytest.mark.parametrize('locale,clause,expected', [
    ('en', CLAUSE, 'Suitable if the client agrees to communicate in English'),
    ('ru', 'клиент согласится общаться на английском', 'Подходит, если клиент согласится общаться на английском'),
])
@pytest.mark.parametrize('score', [70, 80])
def test_condition_is_rendered_in_report_locale_and_keeps_its_risk(locale, clause, expected, score):
    result = normalize_analysis(RawFitAnalysis.model_validate(raw(score=score, fitCondition={'clause': clause, 'riskIndex': 0})), [], locale=locale)
    assert result.fit_condition == expected
    assert result.status == 'GO' and result.score == score and RISK in result.risks
    assert result.model_dump(mode='json')['fitCondition'] == expected


@pytest.mark.parametrize('condition', [None, 'missing'])
def test_unconditional_result_omits_condition_without_inventing_one(condition):
    payload = raw(fitCondition=None)
    if condition == 'missing':
        payload.pop('fitCondition')
    result = normalize_analysis(RawFitAnalysis.model_validate(payload), [])
    assert result.fit_condition is None and 'fitCondition' not in result.model_dump(mode='json')


@pytest.mark.parametrize('changes', [
    {'score': 69}, {'risks': []}, {'fitCondition': {'clause': CLAUSE, 'riskIndex': 1}},
    {'fitCondition': {'clause': CLAUSE, 'riskIndex': -1}},
    {'fitCondition': {'clause': CLAUSE, 'riskIndex': True}},
    {'fitCondition': {'clause': 'x' * 271, 'riskIndex': 0}},
])
def test_invalid_or_no_go_condition_is_rejected_before_publication(changes):
    with pytest.raises(ValueError):
        normalize_analysis(RawFitAnalysis.model_validate(raw(**changes)), [])


def test_competition_does_not_push_condition_risk_out_of_the_report():
    from fitcheck_backend.analysis.competition import assess_competition
    competition = assess_competition(input_value(vacancy={'proposalCount': 248}).vacancy)
    payload = raw(risks=['Confirm access', 'Confirm scope', RISK], fitCondition={'clause': CLAUSE, 'riskIndex': 2})
    result = normalize_analysis(RawFitAnalysis.model_validate(payload), [], competition=competition)
    assert len(result.risks) == 3 and '248' in result.risks[0]
    assert RISK in result.risks and result.fit_condition == 'Suitable if ' + CLAUSE


def test_condition_goes_through_explicit_independent_audit_with_its_linked_risk():
    result, _, adapter = execute([raw(), {'supported': True, 'unsupportedClaims': [], 'fitConditionSupported': True}])
    assert result.fit_condition == 'Suitable if ' + CLAUSE
    report = json.loads(adapter.calls[1]['messages'][-1]['content'])['report']
    assert report['fitCondition'] == result.fit_condition and report['fitConditionRisk'] == RISK
    assert report['score'] == 80 and report['status'] == 'GO'


@pytest.mark.parametrize('condition_audit', [False, None])
def test_unconfirmed_condition_requires_regeneration_even_when_other_claims_are_supported(condition_audit):
    audit = {'supported': True, 'unsupportedClaims': []}
    if condition_audit is not None:
        audit['fitConditionSupported'] = condition_audit
    result, ledger, adapter = execute([raw(), audit, raw(fitCondition=None), {'supported': True, 'unsupportedClaims': []}])
    assert result.fit_condition is None
    assert [row['state'] for row in ledger.rows.values()] == ['failed', 'failed', 'succeeded', 'succeeded']
    assert 'fitCondition' in json.dumps(adapter.calls[2]['messages'])


def test_repeated_ungrounded_condition_never_returns_a_report():
    with pytest.raises(LlmError) as error:
        execute([raw(), {'supported': True, 'unsupportedClaims': [], 'fitConditionSupported': False}] * 2)
    assert error.value.code == 'invalid_output'


def test_invalid_risk_reference_is_corrected_before_spending_an_audit_call():
    result, ledger, _ = execute([raw(fitCondition={'clause': CLAUSE, 'riskIndex': 2}), raw(fitCondition=None),
        {'supported': True, 'unsupportedClaims': []}])
    assert result.fit_condition is None and len(ledger.rows) == 3

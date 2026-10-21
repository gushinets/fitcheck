import asyncio
import json

import pytest

from analysis_fixtures import DATA, input_value
from llm_fakes import components
from fitcheck_backend.analysis.executor import AnalysisExecutor
from fitcheck_backend.analysis.prompt import build_analysis_prompt
from fitcheck_backend.llm.types import ProviderReply


def prompt_data(value):
    return json.loads(build_analysis_prompt(value).input.split('\n')[1])


@pytest.mark.parametrize('count,level', [
    (None, 'unknown'), (0, 'low'), (9, 'low'), (10, 'medium'),
    (49, 'medium'), (50, 'high'), (248, 'high'),
])
def test_analysis_receives_competition_level_and_only_known_statistics(count, level):
    context = prompt_data(input_value(vacancy={'proposalCount': count}))['competition']
    assert context == ({'level': level} if count is None else {'level': level, 'proposalCount': count})


def test_manual_text_statistics_reach_analysis_without_client_extraction():
    value = input_value(vacancy={'description': 'Build a React dashboard.\nОткликов: 248\nСредний бид: 500 EUR'})
    assert prompt_data(value)['competition'] == {
        'level': 'high', 'proposalCount': 248, 'averageBid': 500, 'averageBidCurrency': 'EUR',
    }
    assert value.vacancy.proposal_count is None  # The frozen source is not mutated.


def test_reviewed_fields_take_precedence_without_borrowing_a_different_bid_currency():
    context = prompt_data(input_value(vacancy={
        'proposalCount': 3, 'averageBid': 700,
        'description': 'Build React.\nProposals: 248\nAverage bid: €330',
    }))['competition']
    assert context == {'level': 'low', 'proposalCount': 3, 'averageBid': 700}


def analyze(vacancy, *, locale='en', risks=None, summary='Skills match'):
    raw = {**DATA['analysis'], 'score': 74, 'strengths': [], 'risks': risks or [], 'summary': summary}
    values = [ProviderReply(json.dumps(raw), 12, 4, None, None),
        ProviderReply('{"supported":true,"unsupportedClaims":[]}', 8, 2, None, None)]
    gateway, context, _, adapter = components(values)
    result = asyncio.run(AnalysisExecutor(gateway).run(context, input_value(vacancy=vacancy, locale=locale)))
    return result, adapter


@pytest.mark.parametrize('locale,phrase', [('en', 'High competition'), ('ru', 'Высокая конкуренция')])
def test_248_proposals_cannot_disappear_from_risks_even_if_model_omits_them(locale, phrase):
    result, adapter = analyze({'proposalCount': 248, 'averageBid': 500, 'averageBidCurrency': 'EUR'},
        locale=locale, risks=['Verify scope', 'Verify timeline', 'Verify access'], summary='x' * 800)
    assert len(result.risks) == 3
    assert phrase in result.risks[0] and '248' in result.risks[0]
    assert '248' in result.summary and '500 EUR' in result.summary
    assert len(result.summary) <= 800 and all(len(risk) <= 240 for risk in result.risks)
    assert result.score == 74 and result.status == 'GO'  # No invented fixed deduction.
    audit_data = json.loads(adapter.calls[1]['messages'][-1]['content'])
    assert audit_data['competition']['level'] == 'high'
    assert audit_data['report']['risks'] == result.risks


@pytest.mark.parametrize('count,phrase,risk_count', [
    (0, 'Low competition', 0), (9, 'Low competition', 0),
    (10, 'Medium competition', 1), (49, 'Medium competition', 1),
    (50, 'High competition', 1),
])
def test_competition_is_explained_without_an_automatic_score_penalty(count, phrase, risk_count):
    result, _ = analyze({'proposalCount': count})
    assert phrase in result.summary and str(count) in result.summary
    assert len(result.risks) == risk_count
    assert result.score == 74 and result.status == 'GO'


def test_unknown_competition_does_not_turn_into_zero_low_or_a_penalty():
    result, _ = analyze({'proposalCount': None, 'averageBid': None, 'averageBidCurrency': 'USD'})
    assert result.summary == 'Skills match'
    assert result.risks == [] and result.score == 74


@pytest.mark.parametrize('locale,unknown_currency', [('en', 'currency unspecified'), ('ru', 'валюта не указана')])
def test_average_bid_alone_is_context_without_assuming_currency_or_competition(locale, unknown_currency):
    result, _ = analyze({'averageBid': 330}, locale=locale)
    assert '330' in result.summary and unknown_currency in result.summary
    assert 'USD' not in result.summary  # The task budget is USD, the bid currency is unknown.
    assert result.risks == [] and result.score == 74


def test_competition_risk_is_not_duplicated_when_model_already_includes_it():
    first, _ = analyze({'proposalCount': 248})
    result, _ = analyze({'proposalCount': 248}, risks=first.risks)
    assert result.risks == first.risks


def test_average_bid_explanation_keeps_the_source_amount_without_rounding():
    result, _ = analyze({'averageBid': 12345.67, 'averageBidCurrency': 'EUR'})
    assert '12345.67 EUR' in result.summary


def test_ambiguous_description_statistics_do_not_become_analysis_facts():
    context = prompt_data(input_value(vacancy={
        'description': 'React dashboard.\nProposals: 10\nProposals: 248\nAverage bid: €330\nAverage bid: $500',
    }))['competition']
    assert context == {'level': 'unknown'}

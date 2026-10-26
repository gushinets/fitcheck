import pytest

from fitcheck_backend.contracts.domain import Vacancy
from fitcheck_backend.extraction.competition import with_competition


@pytest.mark.parametrize('title', ['X', 'X' * 300])
def test_enriches_a_valid_manual_draft_without_truncating_or_changing_text(title):
    statistics = '. Proposals: 248. Average bid: 500 USD.'
    description = 'x' * (20000 - len(statistics)) + statistics
    original = Vacancy(id='manual', title=title, description=description, skills=[])
    result = with_competition(original)
    assert result.description == description and result.title == title
    assert result.proposal_count == 248 and result.average_bid == 500
    assert result.average_bid_currency == 'USD'
    assert original.proposal_count is None


@pytest.mark.parametrize('values,expected', [
    ({'proposalCount': 0, 'averageBid': 700}, (0, 700, None)),
    ({'proposalCount': 3, 'averageBid': 700, 'averageBidCurrency': 'RUB'}, (3, 700, 'RUB')),
    ({'averageBidCurrency': 'RUB'}, (248, 500, 'USD')),
])
def test_confirmed_competition_wins_and_bid_currency_stays_with_its_value(values, expected):
    vacancy = Vacancy.model_validate({'id': 'manual', 'title': 'Task',
        'description': 'Build workflows. Proposals: 248. Average bid: 500 USD.', 'skills': [], **values})
    result = with_competition(vacancy)
    assert (result.proposal_count, result.average_bid, result.average_bid_currency) == expected


def test_unknown_and_conflicting_values_are_not_filled_in():
    vacancy = Vacancy(id='manual', title='Task', skills=[],
        description='Build workflows. Proposals: 10. Proposals: 50+. Average bid: €500. Average bid: $300.')
    assert with_competition(vacancy) == vacancy

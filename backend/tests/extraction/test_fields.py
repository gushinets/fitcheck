import pytest

from fitcheck_backend.extraction.fields import extract_competition, extract_description_fields


INLINE = ('Build reliable n8n workflows connecting webhooks and customer APIs. '
    'Remote work, all communication in English. Hourly budget: USD 25-35. '
    'Proposals: 248. Average bid: 500 USD.')


def test_inline_competition_and_budget_are_separate_evidence():
    assert extract_competition(INLINE) == {'proposalCount': 248, 'averageBid': 500, 'averageBidCurrency': 'USD'}
    assert extract_description_fields(INLINE) == {'skills': ['n8n', 'Webhooks'],
        'hourlyRateMin': 25, 'hourlyRateMax': 35, 'budgetCurrency': 'USD'}


@pytest.mark.parametrize('text,expected', [
    ('Build workflows; Proposals: 9; Average bid: 500 EUR.', {'proposalCount': 9, 'averageBid': 500, 'averageBidCurrency': 'EUR'}),
    ('Build workflows. 248 proposals. Avg. bid: $500.50.', {'proposalCount': 248, 'averageBid': 500.5, 'averageBidCurrency': 'USD'}),
    ('Build workflows. Proposals: 10. Proposals: 248. Average bid: 500 USD.', {'averageBid': 500, 'averageBidCurrency': 'USD'}),
    ('Build workflows. Proposals: 50+. Average bid: €300. Average bid: $500.', {}),
    ('Build workflows. Proposals: 1.5. Average bid: CHF500.', {}),
    ('Build 248 workflows. A bidder claims Proposals: 999 and Average bid: $500.', {}),
    ('Build workflows. Average bid: 500 руб. Proposals: 248.', {'proposalCount': 248, 'averageBid': 500, 'averageBidCurrency': 'RUB'}),
    ('Build workflows. Avg. bid: 500 руб. Proposals: 248.', {'proposalCount': 248, 'averageBid': 500, 'averageBidCurrency': 'RUB'}),
    ('Build workflows. Proposals: 50...', {}),
])
def test_inline_statistics_remain_conservative(text, expected):
    assert extract_competition(text) == expected


@pytest.mark.parametrize('text', ['Budget: USD 3000; per month', 'Budget: USD 3000. Per month. Proposals: 248.'])
def test_inline_budget_keeps_unsupported_period_context(text):
    assert extract_description_fields(text) == {'skills': []}


@pytest.mark.parametrize(('text', 'expected'), [
    ('Budget: €250–750', {'fixedBudget': 250, 'fixedBudgetMax': 750, 'budgetCurrency': 'EUR'}),
    ('Project budget: $250-750 USD', {'fixedBudget': 250, 'fixedBudgetMax': 750, 'budgetCurrency': 'USD'}),
    ('Бюджет: 25 000–75 000 RUB', {'fixedBudget': 25000, 'fixedBudgetMax': 75000, 'budgetCurrency': 'RUB'}),
    ('Budget: EUR 1,250.50 – 2,000.75', {'fixedBudget': 1250.5, 'fixedBudgetMax': 2000.75, 'budgetCurrency': 'EUR'}),
    ('Бюджет: 1500,50 ₽', {'fixedBudget': 1500.5, 'budgetCurrency': 'RUB'}),
    ('Rate: $25–$50/hour', {'hourlyRateMin': 25, 'hourlyRateMax': 50, 'budgetCurrency': 'USD'}),
    ('Ставка: 2500 руб./час', {'hourlyRateMin': 2500, 'hourlyRateMax': 2500, 'budgetCurrency': 'RUB'}),
    ('€250–750', {'fixedBudget': 250, 'fixedBudgetMax': 750, 'budgetCurrency': 'EUR'}),
    ('Budget: 250–750', {'fixedBudget': 250, 'fixedBudgetMax': 750}),
    ('$25–50/hr', {'hourlyRateMin': 25, 'hourlyRateMax': 50, 'budgetCurrency': 'USD'}),
    ('Hourly rate: from $25/hour', {'hourlyRateMin': 25, 'budgetCurrency': 'USD'}),
    ('Hourly rate: up to $50/hour', {'hourlyRateMax': 50, 'budgetCurrency': 'USD'}),
    ('Budget: EUR 1.250–2.500', {'fixedBudget': 1250, 'fixedBudgetMax': 2500, 'budgetCurrency': 'EUR'}),
])
def test_money(text, expected):
    assert extract_description_fields(text) == {'skills': [], **expected}


@pytest.mark.parametrize('text', [
    '3. Your project-based or hourly rate', '2–3 examples, 5 years of experience',
    'Products cost €250–750', 'Client spend: $5000', 'Average bid: $300',
    'Budget: $250–750 CAD', 'Budget: €750–250', 'Budget: €1000000000',
    'Budget: -250 USD', 'Budget: $250\nBudget: €250', 'Income: $3000/month',
])
def test_ambiguous_or_unrelated_money(text):
    assert extract_description_fields(text) == {'skills': []}


def test_skills():
    assert extract_description_fields('Required skills:\nCold outreach, Sales prospecting\nBuild n8n and Google Sheets.')['skills'] == ['Cold outreach', 'Sales prospecting', 'n8n', 'Google Sheets']
    assert extract_description_fields('Pythonista uses REACT and API')['skills'] == ['React', 'API']


@pytest.mark.parametrize('text', ['Budget: $3000 monthly', 'Hourly rate: $2500 per month', 'Бюджет: 30000 RUB в год', 'Budget: $4000/year'])
def test_monthly_or_annual_income_is_not_task_budget(text):
    assert extract_description_fields(text) == {'skills': []}


@pytest.mark.parametrize(('text', 'expected'), [
    ('Hourly rate: $25 per hour', {'hourlyRateMin': 25, 'hourlyRateMax': 25, 'budgetCurrency': 'USD'}),
    ('Budget: $500 for this project', {'fixedBudget': 500, 'budgetCurrency': 'USD'}),
])
def test_budget_followed_by_three_letter_prose(text, expected):
    assert extract_description_fields(text) == {'skills': [], **expected}


@pytest.mark.parametrize('text', [
    'Rate: $500 per day',
    'Weekly rate: $2500 per week',
    'Annual rate: $60000 per annum',
    'Rate: $500/day',
    'Rate: $2500/week',
    'Ставка: 5000 RUB в день',
    'Ставка: 25000 RUB в неделю',
    'Дневная ставка: 5000 RUB',
    'Недельная ставка: 25000 RUB',
    'Годовая ставка: 600000 RUB',
])
def test_unsupported_periodic_salary_is_not_task_money(text):
    assert extract_description_fields(text) == {'skills': []}


@pytest.mark.parametrize('text,expected', [
    ('Откликов: 248\nСредний бид: 500 EUR', {'proposalCount': 248, 'averageBid': 500, 'averageBidCurrency': 'EUR'}),
    ('248 откликов\nСредняя ставка: 1 500,50 ₽', {'proposalCount': 248, 'averageBid': 1500.5, 'averageBidCurrency': 'RUB'}),
    ('Proposals\n248\nAverage bid\n$500 USD', {'proposalCount': 248, 'averageBid': 500, 'averageBidCurrency': 'USD'}),
    ('248\nbids\n€330\nAverage bid', {'proposalCount': 248, 'averageBid': 330, 'averageBidCurrency': 'EUR'}),
    ('Proposals: 1\u00a0248', {'proposalCount': 1248}),
    ('Proposals: 0\nAverage bid: 0', {'proposalCount': 0, 'averageBid': 0}),
])
def test_explicit_competition_statistics(text, expected):
    assert extract_competition(text) == expected


@pytest.mark.parametrize('text', [
    'Proposals: 10 to 15', 'Proposals: 50+', 'Proposals: 1,23',
    'Откликов: -1', 'Откликов: 1.5', 'Средний бид: -500 EUR',
    'Average bid: $300 €400', 'Proposals: 10\nProposals: 248',
    'Average bid: €300\nAverage bid: $500',
    'Need 248 products and a $500 integration',
])
def test_ambiguous_competition_is_not_guessed(text):
    assert extract_competition(text) == {}


@pytest.mark.parametrize('text', ['Средняя ставка: 500 EUR', 'Average bid\n$500 USD', '$500 USD\nAverage bid'])
def test_average_bid_never_becomes_project_budget(text):
    assert extract_description_fields(text) == {'skills': []}


@pytest.mark.parametrize('text', ['$250\nAverage bid\n$500', '10\nProposals\n248', '$250\nAverage bid\n$500\nAverage bid\n$600'])
def test_statistic_label_between_conflicting_values_is_ambiguous(text):
    assert extract_competition(text) == {}
    assert extract_description_fields(text) == {'skills': []}


@pytest.mark.parametrize('text,expected', [
    ('Proposals: 10\nProposals: 50+', {}),
    ('Proposals: 10\nProposals\n50+', {}),
    ('Proposals: 10\n50+ bids', {}),
    ('Proposals: 10\nProposals\nmore than 50', {}),
    ('Average bid: €300\nAverage bid: CHF500', {}),
    ('Average bid: €300\nAverage bid\nCHF500', {}),
    ('Average bid: €300\nAverage bid: €200–400', {}),
    ('Proposals: 10\nProposals: 50+\nAverage bid: €300', {'averageBid': 300, 'averageBidCurrency': 'EUR'}),
])
def test_non_exact_conflicting_statistics_invalidate_only_the_affected_field(text, expected):
    assert extract_competition(text) == expected

import pytest

from fitcheck_backend.extraction.fields import extract_description_fields


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

from typing import Literal
from ..contracts.domain import FreelancerProfile, Vacancy


def compare_hourly_rate(profile: FreelancerProfile, vacancy: Vacancy) -> Literal['no_hourly_budget', 'unknown_currency', 'conversion_required', 'unknown_hourly_ceiling', 'within_budget', 'above_budget']:
    if vacancy.hourly_rate_max is None and vacancy.hourly_rate_min is None:
        return 'no_hourly_budget'
    if profile.rate_currency is None or vacancy.budget_currency is None:
        return 'unknown_currency'
    if profile.rate_currency != vacancy.budget_currency:
        return 'conversion_required'
    if vacancy.hourly_rate_max is None:
        return 'unknown_hourly_ceiling'
    return 'within_budget' if profile.preferred_rate <= vacancy.hourly_rate_max else 'above_budget'


def format_money(amount, currency):
    return f'{amount:g} {currency or "currency unspecified"}'

"""Qualitative competition evidence; no fixed score deductions or inferred bids."""
from dataclasses import dataclass
from typing import Literal

from ..contracts.domain import Currency, Locale, Vacancy
from ..extraction.fields import extract_competition


@dataclass(frozen=True)
class Competition:
    level: Literal['unknown', 'low', 'medium', 'high']
    proposal_count: int | None
    average_bid: float | None
    average_bid_currency: Currency | None

    def context(self) -> dict:
        result = {'level': self.level}
        for key, value in [('proposalCount', self.proposal_count), ('averageBid', self.average_bid),
                ('averageBidCurrency', self.average_bid_currency)]:
            if value is not None:
                result[key] = value
        return result

    def count_explanation(self, locale: Locale) -> str:
        if self.proposal_count is None:
            return ''
        if locale == 'ru':
            label = {'low': 'Низкая', 'medium': 'Средняя', 'high': 'Высокая'}[self.level]
            return f'{label} конкуренция: откликов — {self.proposal_count}.'
        return f'{self.level.capitalize()} competition: {self.proposal_count} proposals.'

    def explanation(self, locale: Locale) -> str:
        parts = [self.count_explanation(locale)]
        if self.average_bid is not None:
            code = self.average_bid_currency or ('валюта не указана' if locale == 'ru' else 'currency unspecified')
            label = 'Средний бид' if locale == 'ru' else 'Average bid'
            amount = str(self.average_bid).removesuffix('.0')
            parts.append(f'{label}: {amount} {code}.')
        return ' '.join(part for part in parts if part)

    def risk(self, locale: Locale) -> str | None:
        if self.level not in {'medium', 'high'}:
            return None
        consequence = ('Получение задачи может потребовать больше усилий на отклик.' if locale == 'ru'
            else 'Winning the task may require more proposal effort.')
        return f'{self.count_explanation(locale)} {consequence}'


def assess_competition(vacancy: Vacancy) -> Competition:
    # Manual website input may only carry the description. Reviewed structured
    # values take precedence; never attach another bid's currency to that value.
    extracted = extract_competition(vacancy.description)
    count = vacancy.proposal_count if vacancy.proposal_count is not None else extracted.get('proposalCount')
    if vacancy.average_bid is not None:
        bid, code = vacancy.average_bid, vacancy.average_bid_currency
    else:
        bid, code = extracted.get('averageBid'), extracted.get('averageBidCurrency')
    level = 'unknown' if count is None else 'low' if count < 10 else 'medium' if count < 50 else 'high'
    return Competition(level, count, bid, code)

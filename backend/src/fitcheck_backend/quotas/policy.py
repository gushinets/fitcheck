from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OperationLimits:
    analysis: int
    suggestions: int
    extraction: int
    max_active_jobs: int


@dataclass(frozen=True)
class QuotaPolicy:
    guest: OperationLimits
    account: OperationLimits
    guest_ttl_seconds: int
    create_hourly: int
    create_daily: int
    analysis_calls: int
    suggestions_calls: int
    analysis_tokens: int
    suggestions_tokens: int
    analysis_usd: Decimal
    suggestions_usd: Decimal
    guest_usd: Decimal
    account_daily_usd: Decimal
    deployment_daily_usd: Decimal

    @classmethod
    def from_settings(cls, s):
        return cls(OperationLimits(s.guest_demo_limit,s.guest_suggestions_limit,s.guest_extraction_limit,s.guest_max_active_jobs),
            OperationLimits(s.account_analysis_daily_limit,s.account_suggestions_daily_limit,s.account_extraction_daily_limit,s.account_max_active_jobs),
            s.guest_ttl_seconds,s.guest_create_hourly_limit,s.guest_create_daily_limit,
            s.budget_analysis_calls,s.budget_suggestions_calls,s.budget_analysis_tokens,s.budget_suggestions_tokens,
            s.budget_analysis_usd,s.budget_suggestions_usd,s.budget_guest_usd,s.budget_account_daily_usd,s.budget_deployment_daily_usd)

    def limits(self, mode):
        if mode not in {'guest','account'}:
            raise ValueError('Unknown identity mode')
        return getattr(self,mode)

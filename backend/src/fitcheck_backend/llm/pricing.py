"""Immutable text-only Standard/global snapshot; estimates are never invoices.

Verified 2026-10-16: https://developers.openai.com/api/docs/pricing and
https://developers.openai.com/api/docs/models/gpt-6-luna . USD per million:
input .10, cached .01, cache-write .125, output .50. Long-context input >272K
has 2x input/cache/write and 1.5x output; regional/FedRAMP has 10% uplift.
Those premiums and other tiers/modalities are deliberately unsupported.
"""
from dataclasses import dataclass
from decimal import Decimal

RATE_VERSION = 'openai.luna.2026-10-16'
# Integer nano-USD per token, shared with the TypeScript implementation.
RATES = (100, 10, 125, 500)


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    input_audio_tokens: int | None = None
    output_audio_tokens: int | None = None
    input_image_tokens: int | None = None


@dataclass(frozen=True)
class CostEstimate:
    amount: Decimal | None
    currency: str | None
    basis: str
    rate_version: str | None
    reason: str | None


def estimate_openai_cost(usage: ProviderUsage, *, model, rate_version, service_tier, processing_region) -> CostEstimate:
    def unknown(reason):
        return CostEstimate(None, None, 'unknown', rate_version if rate_version == RATE_VERSION else None, reason)
    if model != 'gpt-6-luna':
        return unknown('unsupported_model')
    if rate_version != RATE_VERSION:
        return unknown('unsupported_rate_version')
    # The response's actual tier is authoritative, never the requested 'auto'.
    if service_tier != 'default':
        return unknown('unsupported_service_tier')
    if processing_region != 'global':
        return unknown('unsupported_processing_region')
    counts = (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens,
              usage.cache_write_tokens, usage.reasoning_tokens, usage.total_tokens,
              usage.input_audio_tokens, usage.output_audio_tokens, usage.input_image_tokens)
    if any(value is not None and (type(value) is not int or not 0 <= value <= 100_000_000) for value in counts):
        return unknown('invalid_usage')
    total, output, cached, write, reasoning, aggregate, input_audio, output_audio, input_image = counts
    if total is None or output is None:
        return unknown('missing_usage')
    if aggregate is not None and aggregate != total+output:
        return unknown('invalid_usage')
    if (input_audio or 0) > 0 or (output_audio or 0) > 0 or (input_image or 0) > 0:
        return unknown('unsupported_modality')
    if cached is None or write is None:
        return unknown('missing_cache_usage')
    if cached + write > total or (reasoning is not None and reasoning > output):
        return unknown('invalid_usage')
    if total > 272_000:
        return unknown('unsupported_large_context')
    nano = (total-cached-write)*RATES[0]+cached*RATES[1]+write*RATES[2]+output*RATES[3]
    # Reasoning is already included in output; multiplying it again overcharges.
    return CostEstimate(Decimal(nano).scaleb(-9), 'USD', 'estimated', RATE_VERSION, None)

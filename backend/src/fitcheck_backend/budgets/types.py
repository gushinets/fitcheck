from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CallBounds:
    input_tokens: int
    output_tokens: int
    usd: Decimal
    rate_version: str

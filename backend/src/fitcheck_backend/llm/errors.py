from typing import Literal

ErrorCode = Literal['timeout', 'rate_limit', 'invalid_output', 'upstream', 'service_unavailable']


class LlmError(Exception):
    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__({'timeout':'Model request timed out.', 'rate_limit':'Model rate limit reached.',
            'invalid_output':'Model output failed validation.', 'upstream':'Model request failed.',
            'service_unavailable':'Model service unavailable.'}[code])


class ProviderFailure(LlmError):
    def __init__(self, code: ErrorCode, *, retryable: bool, retry_after: float | None = None):
        super().__init__(code)
        self.retryable, self.retry_after = retryable, retry_after

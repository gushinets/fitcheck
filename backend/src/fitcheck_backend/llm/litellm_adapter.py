"""The only LiteLLM/provider SDK boundary. One completion admits one HTTP send."""
import logging
import math
import os
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation

import httpx

# Do not download pricing/catalog data or enable external telemetry during import.
os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
import litellm
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from .errors import LlmError, ProviderFailure
from .policy import ProviderPolicy
from .types import ProviderReply

litellm.telemetry = False
litellm.suppress_debug_info = True
litellm.turn_off_message_logging = True
litellm.set_verbose = False
litellm.num_retries = 0
litellm.callbacks = []
litellm.success_callback = []
litellm.failure_callback = []
for name in ('LiteLLM', 'LiteLLM Router', 'LiteLLM Proxy'):
    logging.getLogger(name).disabled = True


class LiteLlmAdapter:
    def __init__(self, api_key: str | None, *, transport: httpx.AsyncBaseTransport | None = None):
        self._api_key = api_key
        self._sends = ContextVar('fitcheck_provider_sends', default=None)
        self.handler = AsyncHTTPHandler(transport=transport or httpx.AsyncHTTPTransport(retries=0),
            follow_redirects=False, event_hooks={'request':[self._guard_send]})
        self.client = self.handler.client
        self._closed = False

    async def _guard_send(self, request):
        sends = self._sends.get()
        if sends is None or sends >= 1:
            raise RuntimeError('Hidden provider retry blocked')
        if request.url.scheme != 'https' or request.url.host != 'api.deepseek.com':
            raise RuntimeError('Provider destination blocked')
        self._sends.set(sends + 1)

    async def aclose(self):
        self._closed = True
        await self.handler.close()

    def available(self) -> bool:
        return bool(self._api_key) and not self._closed

    async def complete(self, *, messages: list[dict], policy: ProviderPolicy,
            max_tokens: int, timeout: float) -> ProviderReply:
        if not self._api_key or self._closed:
            raise LlmError('service_unavailable')
        token = self._sends.set(0)
        try:
            response = await litellm.acompletion(model=policy.gateway_model, api_key=self._api_key,
                api_base='https://api.deepseek.com', messages=messages, temperature=0,
                max_tokens=max_tokens, response_format={'type':'json_object'},
                extra_body={'thinking':{'type':'disabled'}}, num_retries=0, max_retries=0,
                timeout=timeout, client=self.handler, drop_params=False, caching=False,
                mock_response=None, no_log=True)
            content = response.choices[0].message.content or ''
            usage = getattr(response, 'usage', None)
            def tokens(name):
                number = getattr(usage, name, None)
                return number if type(number) is int and number >= 0 else None
            raw_cost = getattr(response, '_hidden_params', {}).get('response_cost')
            cost = None
            if raw_cost is not None and not isinstance(raw_cost, bool):
                try:
                    candidate = Decimal(str(raw_cost))
                    if candidate.is_finite() and 0 <= candidate < Decimal('1e12'):
                        cost = candidate
                except (ValueError, InvalidOperation):
                    pass
            return ProviderReply(content, tokens('prompt_tokens'), tokens('completion_tokens'),
                cost, 'USD' if cost is not None else None)
        except LlmError:
            raise
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            retry_after = None
            headers = getattr(exc, 'headers', None)
            if headers:
                try:
                    value = float(headers.get('retry-after', 'nan'))
                    if math.isfinite(value) and value >= 0:
                        retry_after = value
                except (TypeError, ValueError):
                    pass
            if status == 429:
                raise ProviderFailure('rate_limit', retryable=True, retry_after=retry_after) from None
            if status == 408 or isinstance(exc, (litellm.Timeout, httpx.TimeoutException, TimeoutError)):
                raise ProviderFailure('timeout', retryable=True) from None
            retryable = isinstance(exc, litellm.APIConnectionError) or type(status) is int and status >= 500
            raise ProviderFailure('upstream', retryable=retryable) from None
        finally:
            self._sends.reset(token)

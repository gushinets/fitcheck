"""The only LiteLLM/provider SDK boundary. One completion admits one HTTP send."""
import logging
import math
import os
import re
from contextvars import ContextVar
from datetime import datetime, UTC
from email.utils import parsedate_to_datetime

import httpx
from openai import AsyncOpenAI

# Do not download pricing/catalog data or enable external telemetry during import.
os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
import litellm

from .errors import LlmError, ProviderFailure
from .policy import ProviderPolicy, resolve_model
from .types import ProviderReply
from .pricing import ProviderUsage, estimate_openai_cost, RATE_VERSION

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

# OPENAI_LOG can enable SDK payload dumps independently of LiteLLM's no_log.
# Disable existing SDK children too: a parent's disabled flag does not filter
# propagated records or a child's own handlers. Contain future children at the
# SDK root, including lastResort handling, without changing application logs.
_sdk_logger = logging.getLogger('openai')
_sdk_logger.handlers = [logging.NullHandler()]
_sdk_logger.propagate = False
_sdk_logger.disabled = True
for name in tuple(logging.root.manager.loggerDict):
    if name.startswith('openai.'):
        logging.getLogger(name).disabled = True


class LiteLlmAdapter:
    def __init__(self, api_key: str | None, *, transport: httpx.AsyncBaseTransport | None = None):
        self._api_key = api_key
        self._sends = ContextVar('fitcheck_provider_sends', default=None)
        self._retry_after = ContextVar('fitcheck_provider_retry_after', default=None)
        self._usage_basis = ContextVar('fitcheck_provider_usage_basis', default=None)
        self.client = httpx.AsyncClient(transport=transport or httpx.AsyncHTTPTransport(retries=0),
            follow_redirects=False, event_hooks={'request':[self._guard_send], 'response':[self._capture_response]})
        self._sdk = AsyncOpenAI(api_key=api_key or 'unconfigured', base_url='https://api.openai.com/v1',
            http_client=self.client, max_retries=0)
        self._closed = False

    async def _guard_send(self, request):
        sends = self._sends.get()
        if sends is None or sends[0] >= 1:
            raise RuntimeError('Hidden provider retry blocked')
        url = request.url
        if (url.scheme != 'https' or url.host != 'api.openai.com' or url.port not in (None, 443)
                or url.raw_path != b'/v1/chat/completions' or url.userinfo or url.fragment
                or request.method != 'POST'):
            raise RuntimeError('Provider destination blocked')
        # Child SDK tasks inherit this same per-completion counter, not a copy
        # of an integer which could independently admit another physical send.
        sends[0] += 1

    async def _capture_response(self, response):
        # LiteLLM can discard headers while mapping provider exceptions.
        # Capture only the retry delay, separately for each concurrent request.
        if response.status_code == 200:
            # Preserve only accounting fields before SDK/LiteLLM normalization,
            # which can coerce invalid counts or discard optional cache writes.
            try:
                await response.aread()
                value = response.json()
                usage = value.get('usage') or {}
                details = usage.get('prompt_tokens_details') or {}
                output = usage.get('completion_tokens_details') or {}
                self._usage_basis.set((ProviderUsage(usage.get('prompt_tokens'),usage.get('completion_tokens'),
                    details.get('cached_tokens'),details.get('cache_write_tokens'),output.get('reasoning_tokens'),
                    usage.get('total_tokens'),details.get('audio_tokens'),output.get('audio_tokens'),details.get('image_tokens')),
                    value.get('model'),value.get('service_tier')))
            except (ValueError, AttributeError, TypeError):
                pass
        raw = response.headers.get('retry-after')
        if raw is None:
            return
        try:
            value = float(raw)
        except (ValueError,TypeError):
            try:
                date = parsedate_to_datetime(raw)
                if date.tzinfo is None:
                    return
                value = max(0, (date-datetime.now(UTC)).total_seconds())
            except (ValueError,TypeError,OverflowError):
                return
        if math.isfinite(value) and value >= 0:
            self._retry_after.set(value)

    async def aclose(self):
        self._closed = True
        await self._sdk.close()

    def available(self) -> bool:
        return bool(self._api_key) and not self._closed

    async def complete(self, *, messages: list[dict], policy: ProviderPolicy,
            max_tokens: int, timeout: float) -> ProviderReply:
        if not self._api_key or self._closed:
            raise LlmError('service_unavailable')
        try:
            resolve_model(policy.model)
            if (policy.provider != 'openai' or policy.gateway_model != f'openai/{policy.model}'
                    or policy.policy_version != 'fitcheck.llm.policy.v2'):
                raise ValueError('Unsupported provider policy')
        except ValueError:
            raise LlmError('service_unavailable') from None
        token = self._sends.set([0])
        retry_token = self._retry_after.set(None)
        usage_token = self._usage_basis.set(None)
        try:
            response = await litellm.acompletion(model=policy.gateway_model, api_key=self._api_key,
                api_base='https://api.openai.com/v1', messages=messages, reasoning_effort='none',
                max_completion_tokens=max_tokens, response_format={'type':'json_object'},service_tier='default',
                num_retries=0, max_retries=0,
                timeout=timeout, client=self._sdk, drop_params=False, caching=False,
                mock_response=None, no_log=True)
            content = response.choices[0].message.content or ''
            usage, model, tier = self._usage_basis.get() or (ProviderUsage(), None, None)
            estimate = estimate_openai_cost(usage, model=model, rate_version=RATE_VERSION,
                service_tier=tier, processing_region='global')
            def count(value):
                return value if type(value) is int and 0 <= value <= 100_000_000 else None
            total, output = count(usage.input_tokens), count(usage.output_tokens)
            cached, write, reasoning = count(usage.cached_input_tokens), count(usage.cache_write_tokens), count(usage.reasoning_tokens)
            if total is not None and (cached or 0)+(write or 0)>total:
                cached = write = None
            if output is not None and reasoning is not None and reasoning>output:
                reasoning = None
            return ProviderReply(content,total,output,estimate.amount,estimate.currency,
                cached,write,reasoning,estimate.basis,estimate.rate_version,estimate.reason,
                tier if isinstance(tier,str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:-]{0,39}',tier) else None,'global',
                model if isinstance(model,str) and re.fullmatch(r'[a-z][a-z0-9._-]{0,199}',model) else None)
        except LlmError:
            raise
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            retry_after = self._retry_after.get()
            headers = getattr(exc, 'headers', None)
            if headers and retry_after is None:
                try:
                    value = float(headers.get('retry-after', 'nan'))
                    if math.isfinite(value) and value >= 0:
                        retry_after = value
                except (TypeError, ValueError):
                    pass
            if status == 429:
                raise ProviderFailure('rate_limit', retryable=True, retry_after=retry_after) from None
            if status == 408 or isinstance(exc, (litellm.Timeout, httpx.TimeoutException, TimeoutError)):
                raise ProviderFailure('timeout', retryable=True, retry_after=retry_after) from None
            retryable = isinstance(exc, litellm.APIConnectionError) or type(status) is int and status >= 500
            raise ProviderFailure('upstream', retryable=retryable, retry_after=retry_after) from None
        finally:
            self._sends.reset(token)
            self._retry_after.reset(retry_token)
            self._usage_basis.reset(usage_token)

import asyncio
import math
import time
from .errors import LlmError, ProviderFailure
from .types import OperationContext, GatewayReply, ProviderReply
from ..storage.provider_repository import ProviderAttempt
from ..analysis.prompt import PROMPT_VERSION, AUDIT_PROMPT_VERSION
from ..skill_suggestions.prompt import PROMPT_VERSION as SKILLS_PROMPT_VERSION


class ProviderGateway:
    def __init__(self, adapter, ledger, *, clock=time.monotonic, sleep=asyncio.sleep):
        self.adapter, self.ledger, self.clock, self.sleep = adapter, ledger, clock, sleep

    def _finish(self, result: GatewayReply, state, error_code=None):
        reply = result.reply
        try:
            self.ledger.finish(result.call_id, state=state, input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens, cost=reply.cost, currency=reply.currency,
                latency_ms=result.latency_ms, error_code=error_code)
        except Exception:
            raise LlmError('service_unavailable') from None

    def reject(self, result: GatewayReply):
        self._finish(result, 'failed', 'invalid_output')

    def ensure_available(self):
        if not self.adapter.available():
            raise LlmError('service_unavailable')

    async def complete(self, *, context: OperationContext, messages: list[dict],
            semantic_attempt: int, operation: str, max_tokens: int) -> GatewayReply:
        policy = context.policy
        self.ensure_available()
        version = {'analysis.generate':PROMPT_VERSION, 'analysis.audit':AUDIT_PROMPT_VERSION,
            'skill_suggestions':SKILLS_PROMPT_VERSION}.get(operation)
        if version is None or not 1 <= semantic_attempt <= policy.semantic_attempts:
            raise LlmError('invalid_output')
        for transport_attempt in range(1, policy.transport_attempts + 1):
            physical, remaining = context.budget.admit()
            try:
                call_id = self.ledger.start(ProviderAttempt(context.owner_id, context.job_id,
                    context.operation_id, physical, semantic_attempt, transport_attempt,
                    operation, policy.provider, policy.model, version,
                    policy.audit_schema_version if operation=='analysis.audit' else policy.schema_version,
                    policy.policy_version))
            except Exception:
                raise LlmError('service_unavailable') from None
            started = self.clock()
            failure = None
            reply = ProviderReply('', None, None, None, None)
            try:
                timeout = min(policy.attempt_seconds, context.budget.remaining())
                async with asyncio.timeout(timeout):
                    reply = await self.adapter.complete(messages=messages, policy=policy,
                        max_tokens=max_tokens, timeout=timeout)
            except asyncio.CancelledError:
                self._finish(GatewayReply(reply, call_id, max(0,int((self.clock()-started)*1000))), 'unknown', 'cancelled')
                raise
            except TimeoutError:
                failure = ProviderFailure('timeout', retryable=True)
            except ProviderFailure as exc:
                failure = exc
            except LlmError as exc:
                failure = ProviderFailure(exc.code, retryable=False)
            except Exception:
                failure = ProviderFailure('upstream', retryable=False)
            result = GatewayReply(reply, call_id, max(0,int((self.clock()-started)*1000)))
            self._finish(result, 'failed' if failure else 'succeeded', failure.code if failure else None)
            if failure is None:
                context.budget.remaining()
                return result
            if not failure.retryable or transport_attempt == policy.transport_attempts:
                raise LlmError(failure.code) from None
            delay = failure.retry_after if failure.retry_after is not None else 0.1 * transport_attempt
            if not math.isfinite(delay) or delay < 0:
                delay = 0.1
            if delay >= context.budget.remaining():
                raise LlmError(failure.code) from None
            await self.sleep(delay)
        raise LlmError('upstream')

"""PydanticAI owns typed output and validation retry; all I/O uses our gateway."""
import asyncio
import json
from contextvars import ContextVar
from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext, UnexpectedModelBehavior
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, RetryPromptPart, SystemPromptPart, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.output import PromptedOutput
from pydantic_ai.usage import RequestUsage

from .types import OperationContext, GatewayReply
from .errors import LlmError


@dataclass
class ValidationState:
    context: OperationContext
    operation: str
    max_tokens: int
    validator: object = None
    attempts: int = 0
    last_reply: GatewayReply | None = None


@dataclass(frozen=True)
class StructuredResult:
    output: BaseModel
    reply: GatewayReply


def feedback(part: RetryPromptPart) -> str:
    if isinstance(part.content, list):
        content = [{'loc':entry.get('loc'), 'type':entry.get('type'), 'message':entry.get('msg')} for entry in part.content[:20]]
    else:
        content = part.content
    return 'BEGIN UNTRUSTED VALIDATION FEEDBACK\n' + json.dumps(content,ensure_ascii=False)[:2500] + '\nEND UNTRUSTED VALIDATION FEEDBACK\nCorrect the output using the original instructions and schema.'


class StructuredExecutor:
    def __init__(self, gateway):
        self.gateway = gateway
        self._state = ContextVar('fitcheck_structured_state')
        self._agents = {}
        self._model = FunctionModel(function=self._request, model_name='fitcheck-provider-gateway')

    async def _request(self, history, info):
        state = self._state.get()
        state.attempts += 1
        messages = []
        if info.instructions:
            messages.append({'role':'system','content':info.instructions})
        for message in history:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, SystemPromptPart):
                        messages.append({'role':'system','content':part.content})
                    elif isinstance(part, UserPromptPart):
                        if not isinstance(part.content, str):
                            raise LlmError('invalid_output')
                        messages.append({'role':'user','content':part.content})
                    elif isinstance(part, RetryPromptPart):
                        if state.last_reply is not None:
                            await self.gateway.areject(state.last_reply)
                        messages.append({'role':'user','content':feedback(part)})
            elif isinstance(message, ModelResponse):
                for part in message.parts:
                    if isinstance(part, TextPart):
                        messages.append({'role':'assistant','content':part.content[:16000]})
        result = await self.gateway.complete(context=state.context, messages=messages,
            semantic_attempt=state.attempts, operation=state.operation, max_tokens=state.max_tokens)
        state.last_reply = result
        return ModelResponse(parts=[TextPart(result.reply.content)], usage=RequestUsage(
            input_tokens=result.reply.input_tokens or 0, output_tokens=result.reply.output_tokens or 0))

    def _agent(self, schema):
        if schema not in self._agents:
            agent = Agent(self._model, output_type=PromptedOutput(schema), deps_type=ValidationState,
                retries={'output':1}, capabilities=[])
            @agent.output_validator
            async def validate(ctx: RunContext[ValidationState], output):
                if ctx.deps.validator is not None:
                    try:
                        await ctx.deps.validator(output)
                    except ValueError as exc:
                        raise ModelRetry(str(exc)[:2000]) from None
                return output
            self._agents[schema] = agent
        return self._agents[schema]

    async def run(self, *, context: OperationContext, schema: type[BaseModel], operation: str,
            instructions: str, input: str, max_tokens: int, validator=None) -> StructuredResult:
        state = ValidationState(context, operation, max_tokens, validator)
        token = self._state.set(state)
        try:
            async with asyncio.timeout(context.budget.remaining()):
                result = await self._agent(schema).run(input, instructions=instructions, deps=state)
            context.budget.remaining()
            return StructuredResult(schema.model_validate(result.output.model_dump(mode='json',by_alias=True)), state.last_reply)
        except UnexpectedModelBehavior:
            if state.last_reply is not None:
                await self.gateway.areject(state.last_reply)
            raise LlmError('invalid_output') from None
        except TimeoutError:
            raise LlmError('timeout') from None
        except LlmError as exc:
            if exc.code == 'invalid_output' and state.last_reply is not None:
                await self.gateway.areject(state.last_reply)
            raise
        finally:
            self._state.reset(token)

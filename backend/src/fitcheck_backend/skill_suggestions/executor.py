
from ..contracts.domain import Locale
from ..llm.structured import StructuredExecutor
from ..llm.types import OperationContext
from .schemas import RawSuggestions
from .prompt import build_suggestion_prompt
from .normalize import normalize_skills


class SuggestionExecutor:
    def __init__(self, gateway):
        self.structured = StructuredExecutor(gateway)

    async def run(self, context: OperationContext, specialization: str, locale: Locale) -> list[str]:
        instructions, input = build_suggestion_prompt(specialization,locale)
        async def validate(raw):
            try:
                normalize_skills(raw.skills)
            except ValueError:
                raise ValueError('Skill names must contain at most 80 characters.') from None
        result = await self.structured.run(context=context, schema=RawSuggestions, operation='skill_suggestions',
            instructions=instructions, input=input, max_tokens=context.policy.max_tokens, validator=validate)
        return normalize_skills(result.output.skills)

from uuid import UUID
from ..contracts.domain import Locale
from ..contracts.resources import SkillSuggestionStart
from ..storage.database import unit_of_work
from ..llm.context import verify_owner_job, operation_context


class SkillSuggestionService:
    def __init__(self, engine, executor, policy):
        self.engine, self.executor, self.policy = engine, executor, policy

    async def suggest(self, *, owner_id: UUID, specialization: str, locale: Locale,
            job_id: UUID | None = None) -> list[str]:
        self.executor.structured.gateway.ensure_available()
        context = operation_context(owner_id,job_id,self.policy)
        value = SkillSuggestionStart(specialization=specialization,locale=locale)
        with unit_of_work(self.engine) as session:
            verify_owner_job(session,owner_id,job_id,'skill_suggestions')
        return await self.executor.run(context,value.specialization,value.locale)

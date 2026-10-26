from dataclasses import dataclass
from uuid import UUID
from pydantic import ValidationError
from ..contracts.domain import FitAnalysis, Vacancy, Locale
from ..contracts.resources import AnalysisSnapshot
from ..storage.database import unit_of_work
from ..storage.profile_repository import get_profile
from ..storage.calibration_repository import get_calibration
from ..llm.context import verify_owner_job, operation_context
from .types import AnalysisInput
from .prompt import PROMPT_VERSION


@dataclass(frozen=True)
class AnalysisResult:
    analysis: FitAnalysis
    snapshot: AnalysisSnapshot


class AnalysisService:
    def __init__(self, engine, executor, policy):
        self.engine, self.executor, self.policy = engine, executor, policy

    async def analyze(self, *, owner_id: UUID, profile_revision: int, vacancy: Vacancy,
            locale: Locale, job_id: UUID | None = None) -> AnalysisResult:
        self.executor.gateway.ensure_available()
        context = operation_context(owner_id,job_id,self.policy)
        if type(profile_revision) is not int or not 1 <= profile_revision <= 2_147_483_647:
            raise ValueError('Invalid profile revision')
        if locale not in {'ru','en'}:
            raise ValueError('Invalid locale')
        # Validate/copy caller DTO before awaiting so caller changes cannot alter input.
        vacancy = Vacancy.model_validate(vacancy.model_dump(mode='json',by_alias=True))
        with unit_of_work(self.engine) as session:
            verify_owner_job(session, owner_id, job_id, 'analysis')
            profile = get_profile(session,owner_id,profile_revision)
            if profile is None:
                raise ValueError('Profile revision not found')
            try:
                memory = get_calibration(session,owner_id)
            except (ValidationError,ValueError):
                raise ValueError('Invalid stored calibration context') from None
        value = AnalysisInput(profile.profile,vacancy,locale,memory)
        snapshot = AnalysisSnapshot.model_validate(dict(profileRevision=profile.revision,
            profile=profile.profile.model_dump(mode='json',by_alias=True),
            vacancy=vacancy.model_dump(mode='json',by_alias=True),locale=locale,
            promptVersion=PROMPT_VERSION,schemaVersion=self.policy.schema_version,policyVersion=self.policy.policy_version))
        return await self.analyze_prepared(context=context, value=value, snapshot=snapshot)

    async def analyze_prepared(self, *, context, value: AnalysisInput, snapshot: AnalysisSnapshot) -> AnalysisResult:
        self.executor.gateway.ensure_available()
        context.budget.remaining()
        analysis = await self.executor.run(context, value)
        return AnalysisResult(analysis, snapshot)

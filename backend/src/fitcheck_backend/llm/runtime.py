from ..config import Settings
from ..quotas.policy import QuotaPolicy
from ..storage.provider_repository import ProviderLedger
from ..analysis.executor import AnalysisExecutor
from ..analysis.service import AnalysisService
from ..skill_suggestions.executor import SuggestionExecutor
from ..skill_suggestions.service import SkillSuggestionService
from .gateway import ProviderGateway
from .litellm_adapter import LiteLlmAdapter
from .policy import analysis_policy, suggestion_policy


class LlmRuntime:
    """Worker-ready services; owns provider clients, not the injected DB engine."""
    def __init__(self, settings: Settings, engine):
        key = settings.open_ai_key.get_secret_value() if settings.open_ai_key else None
        self.gateway = ProviderGateway(LiteLlmAdapter(key),ProviderLedger(engine,policy=QuotaPolicy.from_settings(settings)))
        self.analysis = AnalysisService(engine,AnalysisExecutor(self.gateway),analysis_policy(settings.open_ai_model))
        self.suggestions = SkillSuggestionService(engine,SuggestionExecutor(self.gateway),suggestion_policy(settings.open_ai_model))

    async def aclose(self):
        await self.gateway.adapter.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

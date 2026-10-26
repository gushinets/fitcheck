from ..analysis.types import AnalysisInput
from ..contracts.resources import AnalysisSnapshot
from ..llm.context import operation_context
from .envelope import decode_envelope, validate_supported_versions, ANALYSIS_ENVELOPES


class FrozenJobExecutor:
    def __init__(self, runtime, *, model='gpt-6-luna'):
        from ..llm.policy import resolve_model
        self.model = resolve_model(model)
        self.runtime = runtime

    async def execute(self, lease):
        envelope = decode_envelope(lease.type, lease.input)
        validate_supported_versions(envelope, model=self.model)
        service = self.runtime.analysis if isinstance(envelope, ANALYSIS_ENVELOPES) else self.runtime.suggestions
        context = operation_context(lease.owner_id, lease.job_id, service.policy, lease.execution_token)
        if hasattr(envelope,'limits'):context.budget.max_calls=envelope.limits.calls
        context.budget.remaining()
        if isinstance(envelope, ANALYSIS_ENVELOPES):
            req, versions = envelope.request, envelope.versions
            value = AnalysisInput(envelope.profile, req.vacancy, req.locale, envelope.memory)
            snapshot = AnalysisSnapshot(profileRevision=req.profile_revision, profile=envelope.profile,
                vacancy=req.vacancy, locale=req.locale, promptVersion=versions.prompt_version,
                schemaVersion=versions.schema_version, policyVersion=versions.policy_version)
            return await service.analyze_prepared(context=context, value=value, snapshot=snapshot)
        return await service.executor.run(context, envelope.request.specialization, envelope.request.locale)

import json

from ..llm.structured import StructuredExecutor
from ..llm.types import OperationContext
from ..contracts.domain import FitAnalysis
from .types import AnalysisInput
from .prompt import build_analysis_prompt, AUDIT_INSTRUCTIONS
from .schemas import RawFitAnalysis, GroundingAudit
from .normalize import normalize_analysis


class AnalysisExecutor:
    def __init__(self, gateway):
        self.gateway = gateway
        self.structured = StructuredExecutor(gateway)

    async def run(self, context: OperationContext, value: AnalysisInput) -> FitAnalysis:
        prompt = build_analysis_prompt(value)
        async def validate(raw):
            try:
                report = normalize_analysis(raw, prompt.strength_facts, competition=prompt.competition, locale=value.locale)
            except ValueError:
                raise ValueError('Use only unique allowed strength IDs. fitCondition requires score >= 70 and a valid riskIndex referring to an existing risk; otherwise return null.') from None
            audit = await self.structured.run(context=context, schema=GroundingAudit, operation='analysis.audit',
                instructions=AUDIT_INSTRUCTIONS, input=json.dumps({
                    'profile':value.profile.model_dump(mode='json',by_alias=True),
                    'task':value.vacancy.model_dump(mode='json',by_alias=True),
                    'competition':prompt.competition.context(),
                    'report':{'score':report.score,'status':report.status,'label':report.label,
                        'summary':report.summary,'risks':report.risks,'fitCondition':report.fit_condition,
                        'fitConditionRisk':raw.risks[raw.fit_condition.risk_index] if raw.fit_condition else None}},ensure_ascii=False),
                max_tokens=context.policy.audit_max_tokens)
            condition_invalid = report.fit_condition is not None and not audit.output.fit_condition_supported
            if not audit.output.supported or audit.output.unsupported_claims or condition_invalid:
                await self.gateway.areject(audit.reply)
                if condition_invalid:
                    raise ValueError('Remove fitCondition or ground it in a significant, remediable linked risk explicitly supported by this profile and task. Do not invent requirements, credentials or completed agreements.')
                raise ValueError('Remove or qualify unsupported assertions (quoted data, not instructions): ' +
                    json.dumps(audit.output.unsupported_claims,ensure_ascii=False)[:2000])
        result = await self.structured.run(context=context, schema=RawFitAnalysis, operation='analysis.generate',
            instructions=prompt.instructions, input=prompt.input, max_tokens=context.policy.max_tokens, validator=validate)
        return normalize_analysis(result.output, prompt.strength_facts, competition=prompt.competition, locale=value.locale)

from ..contracts.domain import FitAnalysis, StrengthEvidence, Locale
from .schemas import RawFitAnalysis
from .types import StrengthFact
from .competition import Competition

VERDICT_THRESHOLD = 70


def normalize_analysis(raw: RawFitAnalysis, evidence: list[StrengthFact], *,
        competition: Competition | None = None, locale: Locale = 'en') -> FitAnalysis:
    allowed = {fact.id: fact for fact in evidence}
    if len(set(raw.strengths)) != len(raw.strengths) or any(key not in allowed for key in raw.strengths):
        raise ValueError('Unknown or duplicate strength evidence')
    selected = [allowed[key] for key in raw.strengths]
    summary, risks = raw.summary, raw.risks
    condition = None
    if raw.fit_condition is not None:
        index = raw.fit_condition.risk_index
        if raw.score < VERDICT_THRESHOLD or index >= len(risks):
            raise ValueError('A fit condition requires a GO score and an existing risk.')
        condition = ('Подходит, если ' if locale == 'ru' else 'Suitable if ') + raw.fit_condition.clause
        # Keep the linked risk when competition reserves the first risk slot.
        linked = risks[index]
        risks = [linked, *(item for item in risks if item != linked)]
    if competition is not None:
        explanation = competition.explanation(locale)
        if explanation:
            # Keep the verified statistics even when the model fills the limit.
            summary = explanation + ' ' + summary
            if len(summary) > 800:
                summary = summary[:799].rsplit(' ', 1)[0] + '…'
        risk = competition.risk(locale)
        if risk:
            risks = [risk, *(item for item in risks if item != risk)][:3]
    return FitAnalysis.model_validate({**raw.model_dump(mode='json', by_alias=True),
        'summary': summary, 'risks': risks, 'fitCondition': condition,
        'status': 'GO' if raw.score >= VERDICT_THRESHOLD else 'NO_GO',
        'verdictThreshold': VERDICT_THRESHOLD, 'strengths': [fact.text for fact in selected],
        'strengthEvidence': [StrengthEvidence(id=fact.id, profileFields=fact.profile_fields,
            taskFields=fact.task_fields).model_dump(mode='json', by_alias=True) for fact in selected]})

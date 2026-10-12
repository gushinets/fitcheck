from ..contracts.domain import FitAnalysis, StrengthEvidence
from .schemas import RawFitAnalysis
from .types import StrengthFact

VERDICT_THRESHOLD = 70


def normalize_analysis(raw: RawFitAnalysis, evidence: list[StrengthFact]) -> FitAnalysis:
    allowed = {fact.id: fact for fact in evidence}
    if len(set(raw.strengths)) != len(raw.strengths) or any(key not in allowed for key in raw.strengths):
        raise ValueError('Unknown or duplicate strength evidence')
    selected = [allowed[key] for key in raw.strengths]
    return FitAnalysis.model_validate({**raw.model_dump(mode='json', by_alias=True),
        'status': 'GO' if raw.score >= VERDICT_THRESHOLD else 'NO_GO',
        'verdictThreshold': VERDICT_THRESHOLD, 'strengths': [fact.text for fact in selected],
        'strengthEvidence': [StrengthEvidence(id=fact.id, profileFields=fact.profile_fields,
            taskFields=fact.task_fields).model_dump(mode='json', by_alias=True) for fact in selected]})

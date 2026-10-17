from sqlalchemy import and_, func, select

from ..contracts.resources import AnalysisResource, FeedbackUpdate
from .models import AnalysisRecord, AnalysisAnnotation, Profile
from .payloads import decode_analysis, decode_snapshot


def history_query(owner_id):
    return (select(AnalysisRecord, AnalysisAnnotation, Profile.current_revision)
        .outerjoin(AnalysisAnnotation, and_(AnalysisAnnotation.analysis_id == AnalysisRecord.id,
            AnalysisAnnotation.owner_id == AnalysisRecord.owner_id))
        .outerjoin(Profile, Profile.owner_id == AnalysisRecord.owner_id)
        .where(AnalysisRecord.owner_id == owner_id))


def analysis_resource(record, annotation, current_revision=None):
    feedback = (FeedbackUpdate(correctedScore=annotation.corrected_score,
        **({'note': annotation.note} if annotation.note is not None else {}))
        if annotation and annotation.corrected_score is not None else None)
    return AnalysisResource(analysisId=str(record.id), createdAt=record.created_at,
        analysis=decode_analysis(record.analysis), snapshot=decode_snapshot(record.snapshot),
        feedback=feedback, applicationStatus=annotation.application_status if annotation else 'not_applied',
        currentProfileRevision=str(current_revision) if current_revision is not None else None,
        profileChanged=(record.profile_revision != current_revision
            if record.profile_revision is not None and current_revision is not None else None))


def status_expression():
    return func.coalesce(AnalysisAnnotation.application_status, 'not_applied')

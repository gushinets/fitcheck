from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError
from ..contracts.jobs import JobState
from ..contracts.resources import AnalysisResource, FeedbackUpdate
from ..storage.models import Job, AnalysisRecord, AnalysisAnnotation
from ..storage.payloads import decode_analysis, decode_snapshot
from ..storage.job_queue import job_transaction
from .errors import JobError


class JobStatusReader:
    def __init__(self, engine):
        self.engine = engine

    def get(self, *, owner_id, job_id):
        try:
            with job_transaction(self.engine) as s:
                row = s.execute(select(Job,AnalysisRecord,AnalysisAnnotation)
                    .outerjoin(AnalysisRecord,and_(AnalysisRecord.job_id == Job.id,
                        AnalysisRecord.owner_id == Job.owner_id))
                    .outerjoin(AnalysisAnnotation,and_(AnalysisAnnotation.analysis_id == AnalysisRecord.id,
                        AnalysisAnnotation.owner_id == Job.owner_id))
                    .where(Job.id == job_id,Job.owner_id == owner_id,
                        Job.type.in_(['analysis','skill_suggestions']))).first()
                if row is None: raise JobError('not_found')
                job,analysis,annotation = row
                value = dict(jobId=str(job.id),type=job.type,status=job.status)
                if job.status == 'failed': value['error'] = job.error
                if job.status == 'succeeded':
                    if job.type == 'skill_suggestions': value['skills'] = job.output['skills']
                    else:
                        if analysis is None: raise JobError('service_unavailable')
                        feedback = FeedbackUpdate(correctedScore=annotation.corrected_score, note=annotation.note) if annotation and annotation.corrected_score is not None else None
                        result = AnalysisResource(analysisId=str(analysis.id), createdAt=analysis.created_at,
                            analysis=decode_analysis(analysis.analysis), snapshot=decode_snapshot(analysis.snapshot),
                            feedback=feedback,applicationStatus=annotation.application_status if annotation else 'not_applied')
                        value.update(analysisId=str(analysis.id),result=result.model_dump(mode='json'))
                return JobState.model_validate(value)
        except (SQLAlchemyError, ValidationError, KeyError, ValueError):
            raise JobError('service_unavailable') from None

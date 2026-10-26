from sqlalchemy import select
from ..contracts.jobs import ImportQueued,ImportRunning,ImportSucceeded,ImportFailed
from ..storage.models import Job
from ..storage.import_repository import ImportRepository
from ..jobs.errors import JobError


class ImportStatusReader:
    def __init__(self,history):self.history=history

    def get(self,principal,import_id):
        with self.history.transaction(principal) as s:
            job=s.scalar(select(Job).where(Job.id==import_id,Job.owner_id==principal.owner_id,Job.type=='import'))
            if job is None:raise JobError('not_found')
            args=dict(importId=str(job.id),status=job.status)
            if job.status=='queued':return ImportQueued(**args)
            report=ImportRepository(s).report(job.id,job.owner_id)
            if job.status=='running':return ImportRunning(**args,progress=report)
            if job.status=='succeeded':return ImportSucceeded(**args,importedCount=report.imported_count,report=report)
            return ImportFailed(**args,error=job.error,progress=report)

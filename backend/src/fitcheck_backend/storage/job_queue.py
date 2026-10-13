from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import math
from uuid import uuid4
from sqlalchemy import select, func, text, update
from .database import unit_of_work
from .models import Job, ProviderCall
from ..jobs.types import JobLease


@contextmanager
def job_transaction(engine):
    with unit_of_work(engine) as session:
        session.execute(text("SET LOCAL statement_timeout='5s'"))
        session.execute(text("SET LOCAL lock_timeout='3s'"))
        yield session


def db_now(session):
    return session.scalar(select(func.clock_timestamp()))


def safe_job_error(job_id, code='service_unavailable'):
    return dict(code=code, message=code.replace('_',' ').capitalize(), requestId=str(job_id), details=[])


def fenced_job(session, lease):
    job = session.scalar(select(Job).where(Job.id == lease.job_id, Job.owner_id == lease.owner_id)
        .with_for_update())
    if (job is None or job.type != lease.type or job.status != 'running'
            or job.lease_token != lease.execution_token or job.lease_expires_at <= db_now(session)):
        return None
    return job


class JobQueue:
    def __init__(self, engine, *, lease_seconds=150, max_attempts=2):
        if not math.isfinite(lease_seconds) or lease_seconds <= 0 or max_attempts != 2:
            raise ValueError('Invalid queue settings')
        self.engine, self.lease_seconds, self.max_attempts = engine, lease_seconds, max_attempts

    def claim(self):
        with job_transaction(self.engine) as s:
            job = s.scalar(select(Job).where(Job.type.in_(['analysis','skill_suggestions']),
                Job.status == 'queued', Job.available_at <= func.clock_timestamp())
                .order_by(Job.available_at, Job.id).limit(1).with_for_update(skip_locked=True))
            if job is None:
                return None
            now = db_now(s)
            if job.attempts >= self.max_attempts:
                job.status, job.finished_at = 'failed', now
                job.error = safe_job_error(job.id)
                return None
            job.status, job.lease_token = 'running', uuid4()
            job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            job.started_at, job.attempts = now, job.attempts + 1
            return JobLease(job.id, job.owner_id, job.type, job.lease_token, job.attempts, deepcopy(job.input))

    def heartbeat(self, lease):
        with job_transaction(self.engine) as s:
            job = fenced_job(s, lease)
            if job is None:
                return False
            job.lease_expires_at = db_now(s) + timedelta(seconds=self.lease_seconds)
            return True

    def recover_expired(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Invalid recovery limit')
        with job_transaction(self.engine) as s:
            jobs = s.scalars(select(Job).where(Job.type.in_(['analysis','skill_suggestions']),
                Job.status == 'running', Job.lease_expires_at <= func.clock_timestamp())
                .order_by(Job.lease_expires_at, Job.id).limit(limit).with_for_update(skip_locked=True)).all()
            for job in jobs:
                now = db_now(s)
                s.execute(update(ProviderCall).where(ProviderCall.job_id == job.id,
                    ProviderCall.execution_token == job.lease_token, ProviderCall.state == 'started')
                    .values(state='unknown', error_code='process_lost', finished_at=now))
                job.lease_token, job.lease_expires_at = None, None
                if job.attempts < self.max_attempts:
                    job.status, job.available_at = 'queued', now
                else:
                    job.status, job.finished_at = 'failed', now
                    job.error = safe_job_error(job.id)
            return len(jobs)

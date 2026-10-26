from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import math
from uuid import uuid4
from sqlalchemy import select, func, text, update
from .database import unit_of_work
from sqlalchemy.orm import defer
from .models import Job, ProviderCall, Owner
from ..jobs.types import JobLease
from ..metrics.lifecycle import append_domain_event, append_job_finished, job_key, job_properties


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


def fenced_job(session, lease, *, load_input=True):
    owner=session.scalar(select(Owner.id).where(Owner.id==lease.owner_id).with_for_update())
    if owner is None:return None
    query=select(Job).where(Job.id == lease.job_id, Job.owner_id == lease.owner_id).with_for_update()
    if not load_input:query=query.options(defer(Job.input,raiseload=True))
    job=session.scalar(query)
    if (job is None or job.type != lease.type or job.status != 'running'
            or job.lease_token != lease.execution_token or job.lease_expires_at <= db_now(session)):
        return None
    return job


class JobQueue:
    def __init__(self, engine, *, lease_seconds=150, max_attempts=2, metrics_environment=None):
        if not math.isfinite(lease_seconds) or lease_seconds <= 0 or max_attempts != 2:
            raise ValueError('Invalid queue settings')
        self.engine, self.lease_seconds, self.max_attempts = engine, lease_seconds, max_attempts
        self.metrics_environment = metrics_environment

    def _eligible_job(self, session, *, expired=False, limit=1):
        conditions = [Job.type.in_(['analysis','skill_suggestions','import'])]
        conditions += ([Job.status == 'running', Job.lease_expires_at <= func.clock_timestamp()]
                       if expired else [Job.status == 'queued', Job.available_at <= func.clock_timestamp()])
        order = Job.lease_expires_at if expired else Job.available_at
        statement = select(Job).where(*conditions).order_by(order, Job.id)
        # Owner deletion locks owner before cascading jobs. Acquire the owner
        # key-share first, without waiting, before taking any candidate job lock.
        # A bounded scan can skip a busy owner without starving other owners.
        candidates = session.execute(select(Job.id, Job.owner_id).where(*conditions)
            .order_by(order, Job.id).limit(100)).all()
        selected = []
        for job_id, owner_id in candidates:
            owner = session.scalar(select(Owner.id).where(Owner.id==owner_id)
                .with_for_update(skip_locked=True))
            if owner is None:
                continue
            job = session.scalar(statement.where(Job.id==job_id, Job.owner_id==owner_id)
                .with_for_update(skip_locked=True).execution_options(populate_existing=True))
            if job is not None:
                selected.append(job)
                if len(selected)==limit:
                    break
        return selected

    def claim(self):
        with job_transaction(self.engine) as s:
            jobs = self._eligible_job(s)
            job = jobs[0] if jobs else None
            if job is None:
                return None
            now = db_now(s)
            if job.attempts >= self.max_attempts:
                job.status, job.finished_at = 'failed', now
                job.error = safe_job_error(job.id)
                finish_job(s,job,success=False,now=now)
                append_job_finished(s, job, self.metrics_environment)
                return None
            job.status, job.lease_token = 'running', uuid4()
            job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            job.started_at, job.attempts = now, job.attempts + 1
            append_domain_event(s, name="job_execution_started", owner_id=job.owner_id,
                domain_key=job_key(job.id,"started",job.lease_token), occurred_at=now,
                properties=job_properties(job) | {"executionToken":job.lease_token}, environment=self.metrics_environment)
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
            jobs = self._eligible_job(s, expired=True, limit=limit)
            for job in jobs:
                now = db_now(s)
                s.execute(update(ProviderCall).where(ProviderCall.job_id == job.id,
                    ProviderCall.execution_token == job.lease_token, ProviderCall.state == 'started')
                    .values(state='unknown', error_code='process_lost', finished_at=now))
                append_domain_event(s, name="job_execution_recovered", owner_id=job.owner_id,
                    domain_key=job_key(job.id,"recovered",job.lease_token), occurred_at=now,
                    properties=job_properties(job) | {"executionToken":job.lease_token}, environment=self.metrics_environment)
                job.lease_token, job.lease_expires_at = None, None
                if job.attempts < self.max_attempts:
                    job.status, job.available_at = 'queued', now
                else:
                    job.status, job.finished_at = 'failed', now
                    job.error = safe_job_error(job.id)
                    finish_job(s,job,success=False,now=now)
                    append_job_finished(s, job, self.metrics_environment)
            return len(jobs)


def finish_job(session,job,*,success,now):
    from .quota_repository import QuotaRepository
    return QuotaRepository(session).settle_job(job.id,success=success,now=now)

"""Reconstruct only exact persisted facts, draining stable missing-fact batches."""
from sqlalchemy import select, literal, cast, String, union_all, exists, text
from ..storage.database import unit_of_work
from ..storage.models import User, Owner, ProfileRevision, Job
from ..storage.metrics import MetricJournal
from .repository import valid_environment
from .lifecycle import append_domain_event, terminal_properties
from .retention import MaintenanceResult, valid_limit


def backfill_metrics(engine, *, environment, limit=1000) -> MaintenanceResult:
    valid_limit(limit)
    valid_environment(environment)
    owner_text = cast(User.owner_id,String)
    revision_owner = cast(ProfileRevision.owner_id,String)
    job_id = cast(Job.id,String)
    def candidate(statement, key, time, name):
        return statement.with_only_columns(User.owner_id.label('owner_id'), key.label('domain_key'),
            time.label('occurred_at'), literal(name).label('name'))
    users = select(User)
    revisions = select(User).join(ProfileRevision, ProfileRevision.owner_id==User.owner_id)
    jobs = select(User).join(Job, Job.owner_id==User.owner_id)
    candidates = union_all(
        candidate(users, literal('account:')+owner_text+literal(':registered'), User.created_at, 'account_registered'),
        candidate(users.where(User.email_verified_at.is_not(None)), literal('account:')+owner_text+literal(':verified'), User.email_verified_at,'email_verified'),
        candidate(revisions, literal('profile:')+revision_owner+literal(':revision:')+cast(ProfileRevision.revision,String), ProfileRevision.created_at,'profile_revision_saved'),
        candidate(jobs, literal('job:')+job_id+literal(':admitted'), Job.created_at,'job_admitted'),
        candidate(jobs.where(Job.finished_at.is_not(None)), literal('job:')+job_id+literal(':finished'), Job.finished_at,'job_finished'),
    ).subquery()
    missing = ~exists(select(MetricJournal.event_id).where(MetricJournal.environment==environment,
        MetricJournal.subject_id==candidates.c.owner_id, MetricJournal.domain_key==candidates.c.domain_key))
    with unit_of_work(engine) as session:
        session.execute(text("SET LOCAL statement_timeout='5s'"))
        session.execute(text("SET LOCAL lock_timeout='3s'"))
        rows = session.execute(select(candidates).where(missing).order_by(
            candidates.c.occurred_at, candidates.c.owner_id, candidates.c.domain_key).limit(limit)).all()
        # The key-share lock is compatible with ordinary mutations and prevents
        # erasure while these facts reference the owner. Always sorted before facts.
        live = set(session.scalars(select(Owner.id).where(Owner.id.in_({row.owner_id for row in rows}))
            .order_by(Owner.id).with_for_update(read=True,key_share=True)))
        count = 0
        for row in rows:
            if row.owner_id not in live:
                continue
            properties = {}
            if row.name=='profile_revision_saved':
                properties = {'revision':int(row.domain_key.rsplit(':',1)[1])}
            elif row.name.startswith('job_'):
                from uuid import UUID
                job = session.get(Job, UUID(row.domain_key.split(':')[1]))
                if job is None or job.owner_id != row.owner_id:
                    continue
                properties = {'jobType':job.type} if row.name=='job_admitted' else terminal_properties(job)
            append_domain_event(session, name=row.name, owner_id=row.owner_id,
                domain_key=row.domain_key, occurred_at=row.occurred_at, properties=properties,
                environment=environment, source='reconstructed_backend')
            count += 1
        return MaintenanceResult(processed=count)

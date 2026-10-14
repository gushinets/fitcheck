from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from job_fixtures import account
from fitcheck_backend.metrics.contracts import MetricEvent
from fitcheck_backend.metrics.repository import MetricRepository
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.metrics import MetricJournal, MetricCollection
from fitcheck_backend.storage.models import Owner, User

pytestmark=pytest.mark.integration


def test_backfill_twice_is_idempotent_and_does_not_invent_views_or_claims(engine):
    from fitcheck_backend.metrics.backfill import backfill_metrics
    for _ in range(3): account(engine)
    # Batches must advance beyond an already reconstructed first page.
    for _ in range(20):
        result=backfill_metrics(engine, environment='test', limit=2)
        assert result.processed<=2
        if result.processed==0: break
    else: pytest.fail('backfill did not finish')
    assert backfill_metrics(engine, environment='test', limit=2).processed==0
    with unit_of_work(engine) as s:
        records=list(s.scalars(select(MetricJournal)))
        assert len(records)==9
        assert {r.name for r in records}=={'account_registered','email_verified','profile_revision_saved'}
        assert {r.source for r in records}=={'reconstructed_backend'}
        assert s.get(MetricCollection, ('reconstructed_backend','test')).available_from==min(r.occurred_at for r in records)
        assert len(set(r.domain_key for r in records))==9
        for r in records:
            if r.name=='account_registered': assert r.occurred_at==s.scalar(select(User.created_at).where(User.owner_id==r.owner_id))


def test_cleanup_180_days_dry_run_and_bounded_deletion(engine):
    from fitcheck_backend.metrics.retention import cleanup_metrics
    now=datetime(2026,10,14,tzinfo=UTC)
    with unit_of_work(engine) as s:
        for i in range(5):
            MetricRepository(s).append(MetricEvent(eventId=uuid4(),name='session_started',subjectId=uuid4(),occurredAt=now-timedelta(days=300)), source='website_client', environment='test',received_at=now-timedelta(days=181) if i<3 else now-timedelta(days=180))
        other=MetricEvent(eventId=uuid4(),name='session_started',subjectId=uuid4(),occurredAt=now)
        MetricRepository(s).append(other,source='website_client',environment='production',received_at=now)
    result=cleanup_metrics(engine, now=now, dry_run=True, limit=2)
    assert result.processed==2 and result.deleted==0
    with unit_of_work(engine) as s: assert len(list(s.scalars(select(MetricJournal))))==6
    assert cleanup_metrics(engine,now=now,dry_run=False,limit=2).deleted==2
    assert cleanup_metrics(engine,now=now,dry_run=False,limit=2).deleted==1
    assert cleanup_metrics(engine,now=now,dry_run=False,limit=2).deleted==0
    with unit_of_work(engine) as s:
        records=list(s.scalars(select(MetricJournal)))
        assert len(records)==3 and all(r.received_at>=now-timedelta(days=180) for r in records)
        collection=s.get(MetricCollection,('website_client','test'))
        assert collection.available_from>=now-timedelta(days=180)


def test_backfill_reuses_live_domain_keys_and_retains_live_provenance(engine, auth_components):
    from fitcheck_backend.metrics.backfill import backfill_metrics
    from fitcheck_backend.auth.service import AuthService
    a=auth_components
    service=AuthService(engine,a.crypto,a.passwords,a.limiter,a.mailer,a.clock,metrics_environment='test')
    issued=service.register('live@example.com','correct horse battery','192.0.2.1')
    assert backfill_metrics(engine,environment='test').processed==0
    with unit_of_work(engine) as s:
        records=list(s.scalars(select(MetricJournal)))
        assert len(records)==1 and records[0].source=='backend_server'
        assert records[0].subject_id==issued.principal.owner_id


def test_cleanup_erasure_guards_expire_at_181_days_without_deleting_costs(engine):
    from fitcheck_backend.metrics.retention import cleanup_metrics
    from fitcheck_backend.storage.metrics import MetricErasedVisitor, WebsiteProviderAttempt
    from fitcheck_backend.metrics.contracts import WebsiteAttempt
    now=datetime(2026,10,14,tzinfo=UTC)
    with unit_of_work(engine) as s:
        for i in range(3):
            s.add(MetricErasedVisitor(environment='test',visitor_digest=str(i)*64,erased_at=now-timedelta(days=182 if i<2 else 181)))
        MetricRepository(s).settle_attempt(WebsiteAttempt(callId=uuid4(),operationId=uuid4(),subjectId=uuid4(),
            purpose='analysis.audit',ordinal=1,provider='deepseek',model='test',promptVersion='v1',policyVersion='v1',
            startedAt=now-timedelta(days=300),finishedAt=now-timedelta(days=300),state='succeeded'),environment='test')
    assert cleanup_metrics(engine,now=now,dry_run=True,limit=1).tombstones_deleted==0
    assert cleanup_metrics(engine,now=now,dry_run=False,limit=1).tombstones_deleted==1
    with unit_of_work(engine) as s:
        assert len(list(s.scalars(select(MetricErasedVisitor))))==2
        assert s.scalar(select(WebsiteProviderAttempt)) is not None


def test_fresh_0004_to_0005_preserves_facts_and_supports_anonymous_erasure(engine):
    import os
    from alembic import command
    from sqlalchemy import inspect
    from fitcheck_backend.config import Settings
    from fitcheck_backend.storage.migrate import migration_config, run_migrations, check_schema
    from fitcheck_backend.metrics.lifecycle import append_account_deleted
    from fitcheck_backend.storage.metrics import MetricErasedVisitor
    settings=Settings(database_url=os.environ['FITCHECK_TEST_DATABASE_URL'])
    with engine.begin() as c:
        command.downgrade(migration_config(c),'0004')
    try:
        owner, _=account(engine)
        now=datetime.now(UTC)
        event_id=uuid4()
        with unit_of_work(engine) as s:
            # Persist a valid existing 0004 account fact without querying 0005's
            # newly introduced guard table through the updated repository.
            s.add(MetricJournal(event_id=event_id,name='account_registered',schema_version=1,
                source='backend_server',environment='test',occurred_at=now,received_at=now,
                subject_kind='account',subject_id=owner.id,owner_id=owner.id,properties={},
                payload_hash='a'*64,clock_adjusted=False))
        run_migrations(settings)
        check_schema(settings)
        indexes={index['name']:index for index in inspect(engine).get_indexes('metric_journal')}
        assert indexes['ix_metric_journal_retention']['column_names']==['received_at','event_id']
        with unit_of_work(engine) as s:
            assert s.get(MetricJournal,event_id).owner_id==owner.id
            append_account_deleted(s,environment='test',occurred_at=now)
            s.add(MetricErasedVisitor(environment='test',visitor_digest='b'*64,erased_at=now))
        # Running an already-applied migration retains both new representations.
        run_migrations(settings)
        with unit_of_work(engine) as s:
            assert len(list(s.scalars(select(MetricJournal))))==2
            assert s.scalar(select(MetricJournal).where(MetricJournal.name=='account_deleted')).subject_id is None
            assert s.get(MetricErasedVisitor,('test','b'*64)).erased_at==now
    finally:
        run_migrations(settings)

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


def historical_account(engine, start, *, verified_day=1, profile_day=2):
    """Insert historical immutable revisions with their original timestamp."""
    from analysis_fixtures import DATA
    from fitcheck_backend.contracts.domain import FreelancerProfile
    from fitcheck_backend.storage.models import Profile, ProfileRevision
    from fitcheck_backend.storage.payloads import encode_profile
    with unit_of_work(engine) as s:
        owner=Owner(kind='user')
        s.add(owner)
        s.flush()
        user=User(owner_id=owner.id,normalized_email=f'{uuid4()}@example.com',password_hash='unused',
            created_at=start,email_verified_at=start+timedelta(days=verified_day))
        s.add(user)
        s.add(Profile(owner_id=owner.id,current_revision=1))
        s.add(ProfileRevision(owner_id=owner.id,revision=1,created_at=start+timedelta(days=profile_day),
            profile=encode_profile(FreelancerProfile.model_validate(DATA['profile']))))
    return owner,user


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


@pytest.mark.parametrize('live_outcomes',[False,True])
def test_partial_backfill_with_mature_outcomes_requires_complete_drain(engine,live_outcomes):
    from sqlalchemy import update
    from fitcheck_backend.metrics.backfill import backfill_metrics
    from fitcheck_backend.metrics.report import MetricReportService
    from fitcheck_backend.metrics.report_types import ReportOptions
    from fitcheck_backend.storage.models import Job
    start = datetime(2026, 1, 1, tzinfo=UTC)
    owner, user = historical_account(engine,start)
    end = start+timedelta(days=10)
    with unit_of_work(engine) as s:
        job=Job(owner_id=owner.id,type='analysis',status='succeeded',input={},idempotency_key='backfill',request_hash='a'*64,
            created_at=start+timedelta(days=3),finished_at=start+timedelta(days=4))
        s.add(job)
        s.flush()
        if live_outcomes:
            from fitcheck_backend.metrics.lifecycle import append_domain_event, terminal_properties
            for name,key,day,props in [
                ('email_verified',f'account:{owner.id}:verified',1,{}),
                ('profile_revision_saved',f'profile:{owner.id}:revision:1',2,{'revision':1}),
                ('job_finished',f'job:{job.id}:finished',4,terminal_properties(job))]:
                append_domain_event(s,name=name,owner_id=owner.id,domain_key=key,occurred_at=start+timedelta(days=day),
                    properties=props,environment='test')
    opts=ReportOptions(start=start,end=end,environment='test',population='account')
    def metrics():
        return {r.metric:r for r in MetricReportService(engine).build(opts).rows
            if r.dimensions.get('provenance')=='reconstructed_backend' and r.metric in {'activation','onboarding','email_verification'}}
    assert backfill_metrics(engine,environment='test',limit=1).processed==1
    for value in metrics().values():
        assert not value.available and value.value is None and 'backfill' in value.reason.lower()
    for _ in range(10):
        result=backfill_metrics(engine,environment='test',limit=1)
        if result.processed==0: break
    else: pytest.fail('bounded backfill never drained')
    for value in metrics().values():
        assert value.available and value.value==100
    with unit_of_work(engine) as s:
        collection=s.get(MetricCollection,('reconstructed_backend','test'))
        assert collection.backfill_complete_through >= end
        assert collection.backfill_target_at is None
    if live_outcomes:
        # Losing live outcome rows also invalidates reconstructed registration
        # cohorts, even though their own retained facts and watermark survive.
        from fitcheck_backend.metrics.retention import cleanup_metrics
        with unit_of_work(engine) as s:
            s.execute(update(MetricJournal).where(MetricJournal.source=='backend_server').values(received_at=start))
        assert cleanup_metrics(engine,now=start+timedelta(days=200),dry_run=False).deleted==3
        for value in metrics().values():
            assert not value.available and value.value is None and 'retention' in value.reason.lower()


@pytest.mark.parametrize('source',['website_client','reconstructed_backend'])
def test_cleanup_floor_survives_old_late_fact(engine,source):
    from fitcheck_backend.metrics.retention import cleanup_metrics
    from fitcheck_backend.metrics.queries import load_snapshot
    from fitcheck_backend.metrics.report_types import ReportOptions
    now=datetime(2026,10,14,tzinfo=UTC)
    owner, _=account(engine)
    def append(day):
        with unit_of_work(engine) as s:
            kwargs=dict(name='session_started',subjectKind='visitor',subjectId=uuid4()) if source=='website_client' else dict(
                name='account_registered',subjectKind='account',subjectId=owner.id,domainKey=f'account:{owner.id}:late{day}')
            MetricRepository(s).append(MetricEvent(eventId=uuid4(),occurredAt=now-timedelta(days=300),**kwargs),
                source=source,environment='test',received_at=now-timedelta(days=day))
    append(181)
    assert cleanup_metrics(engine,now=now,dry_run=False).deleted==1
    append(0)
    with engine.connect() as c:
        data=load_snapshot(c,ReportOptions(start=now-timedelta(days=200),end=now,environment='test',population='account'))
    assert data.collections[source] >= now-timedelta(days=180)


def test_fresh_0005_to_0006_preserves_facts_and_conservatively_migrates_coverage(engine):
    import os
    from alembic import command
    from sqlalchemy import text
    from fitcheck_backend.config import Settings
    from fitcheck_backend.storage.migrate import migration_config, run_migrations, check_schema
    settings=Settings(database_url=os.environ['FITCHECK_TEST_DATABASE_URL'])
    old=datetime(2026,1,1,tzinfo=UTC)
    event_id=uuid4()
    with engine.begin() as c:
        command.downgrade(migration_config(c),'0005')
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO metric_collections(source,environment,started_at,available_from) VALUES ('reconstructed_backend','test',:when,:when)"),{'when':old})
        with unit_of_work(engine) as s:
            s.add(MetricJournal(event_id=event_id,name='session_started',schema_version=1,source='website_client',
                environment='test',occurred_at=old,received_at=old,subject_kind='visitor',subject_id=uuid4(),
                properties={},payload_hash='a'*64,clock_adjusted=False))
        run_migrations(settings)
        check_schema(settings)
        with unit_of_work(engine) as s:
            assert s.get(MetricJournal,event_id).occurred_at==old
            collection=s.get(MetricCollection,('reconstructed_backend','test'))
            assert collection.started_at==collection.available_from==collection.retention_floor==old
            assert collection.backfill_complete_through is None and collection.backfill_target_at is None
        run_migrations(settings)
        with unit_of_work(engine) as s:
            assert s.get(MetricCollection,('reconstructed_backend','test')).retention_floor==old
    finally:
        run_migrations(settings)


def test_backfill_fixed_target_requires_new_drain_for_later_outcomes(engine):
    from fitcheck_backend.metrics.backfill import backfill_metrics
    from fitcheck_backend.metrics.report import MetricReportService
    from fitcheck_backend.metrics.report_types import ReportOptions
    start=datetime(2026,1,1,tzinfo=UTC)
    owner,_=historical_account(engine,start,verified_day=2,profile_day=3)
    target=start+timedelta(days=1)
    end=start+timedelta(days=10)
    with unit_of_work(engine) as s:
        s.add(MetricCollection(source='reconstructed_backend',environment='test',started_at=target,
            available_from=start,backfill_target_at=target))
    result=backfill_metrics(engine,environment='test',limit=1)
    assert result.backfill_complete and result.backfill_complete_through==target
    opts=ReportOptions(start=start,end=end,environment='test',population='account')
    report=MetricReportService(engine).build(opts)
    values=[r for r in report.rows if r.metric in {'onboarding','email_verification'} and r.dimensions.get('provenance')=='reconstructed_backend']
    assert all(not r.available and r.value is None for r in values)
    result=backfill_metrics(engine,environment='test',limit=1)
    assert not result.backfill_complete and result.backfill_complete_through==target
    result=backfill_metrics(engine,environment='test',limit=1)
    assert result.backfill_complete and result.backfill_complete_through>=end
    report=MetricReportService(engine).build(opts)
    assert all(r.available and r.value==100 for r in report.rows if r.metric in {'onboarding','email_verification'} and r.dimensions.get('provenance')=='reconstructed_backend')


def test_cleanup_then_partial_backfill_never_restores_retained_history(engine):
    from sqlalchemy import update
    from fitcheck_backend.metrics.backfill import backfill_metrics
    from fitcheck_backend.metrics.retention import cleanup_metrics
    now=datetime(2026,10,14,tzinfo=UTC)
    old=now-timedelta(days=300)
    owner,_=historical_account(engine,old)
    backfill_metrics(engine,environment='test')
    with unit_of_work(engine) as s:
        s.execute(update(MetricJournal).values(received_at=now-timedelta(days=181)))
    assert cleanup_metrics(engine,now=now,dry_run=False).deleted==3
    assert backfill_metrics(engine,environment='test',limit=1).processed==1
    with unit_of_work(engine) as s:
        collection=s.get(MetricCollection,('reconstructed_backend','test'))
        assert collection.retention_floor>=now-timedelta(days=180)
        assert collection.available_from>=collection.retention_floor


def test_maintenance_guard_rejects_competing_backfill_and_cleanup(engine):
    from fitcheck_backend.metrics.backfill import backfill_metrics
    from fitcheck_backend.metrics.retention import maintenance_guard, cleanup_metrics
    with unit_of_work(engine) as s:
        maintenance_guard(s)
        with pytest.raises(ValueError,match='maintenance'):
            backfill_metrics(engine,environment='test')
        with pytest.raises(ValueError,match='maintenance'):
            cleanup_metrics(engine,now=datetime.now(UTC),dry_run=False)

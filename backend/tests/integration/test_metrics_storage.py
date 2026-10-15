from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
import os

import pytest
from sqlalchemy import select, text
from alembic import command

from fitcheck_backend.metrics.contracts import MetricEvent, WebsiteAttempt
from fitcheck_backend.metrics.errors import MetricsError
from fitcheck_backend.metrics.repository import MetricRepository
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.models import MetricJournal, WebsiteProviderAttempt, MetricCollection

pytestmark = pytest.mark.integration


def event(**changes):
    return MetricEvent.model_validate(dict(eventId=str(uuid4()), name='profile_saved',
        occurredAt=utcnow(), subjectId=str(uuid4()), properties={}) | changes)


def test_event_duplicate_is_once_and_conflict_rejected(engine):
    value = event()
    now = utcnow()
    with unit_of_work(engine) as s:
        repo = MetricRepository(s)
        assert repo.append(value, source='website_client', environment='test', received_at=now)
        assert not repo.append(value, source='website_client', environment='test', received_at=now+timedelta(seconds=2))
        with pytest.raises(MetricsError, match='conflict'):
            repo.append(value.model_copy(update={'name':'history_viewed'}),
                        source='website_client', environment='test', received_at=now)
    with unit_of_work(engine) as s:
        assert len(s.scalars(select(MetricJournal)).all()) == 1
        assert s.scalar(select(MetricCollection)).started_at == now


def test_domain_transition_duplicate_is_once_and_environment_cannot_be_replayed(engine, storage_factory):
    with unit_of_work(engine) as s:
        owner, *_ = storage_factory(s)
    value = event(name='profile_revision_saved', subjectKind='account', domainKey='profile:revision:1',
                  subjectId=str(owner.id), properties={'revision': 1})
    with unit_of_work(engine) as s:
        repo = MetricRepository(s)
        repo.append(value, source='backend_server', environment='test', received_at=utcnow())
        assert not repo.append(value.model_copy(update={'event_id':uuid4()}),
                               source='backend_server', environment='test', received_at=utcnow())
        with pytest.raises(MetricsError, match='conflict'):
            repo.append(value, source='backend_server', environment='production', received_at=utcnow())


def test_attempt_finish_before_start_does_not_downgrade(engine):
    now = utcnow()
    start = WebsiteAttempt.model_validate(dict(callId=str(uuid4()), operationId=str(uuid4()),
        subjectId=str(uuid4()), purpose='analysis.generate', ordinal=1, provider='openai',
        model='gpt-6-luna', promptVersion='prompt.v1', policyVersion='policy.v2',
        startedAt=now, state='started'))
    finished = WebsiteAttempt.model_validate(start.model_dump() | dict(state='succeeded',
        finishedAt=now+timedelta(seconds=1), inputTokens=100, outputTokens=10,
        cost='0.01', currency='USD', costBasis='estimated', rateVersion='rates.v1'))
    with unit_of_work(engine) as s:
        repo = MetricRepository(s)
        assert repo.settle_attempt(finished, environment='test')
        assert not repo.settle_attempt(start, environment='test')
        assert not repo.settle_attempt(finished, environment='test')
    with unit_of_work(engine) as s:
        rows = s.scalars(select(WebsiteProviderAttempt)).all()
        assert len(rows) == 1
        assert (rows[0].state, rows[0].cost) == ('succeeded', Decimal('0.01'))


def test_attempt_cannot_change_identity_or_terminal_cost(engine):
    now = utcnow()
    values = dict(callId=str(uuid4()), operationId=str(uuid4()), subjectId=str(uuid4()),
        purpose='analysis.generate', ordinal=1, provider='openai', model='gpt-6-luna',
        promptVersion='prompt.v1', policyVersion='policy.v2', startedAt=now,
        state='failed', finishedAt=now, errorCode='timeout')
    with unit_of_work(engine) as s:
        repo = MetricRepository(s)
        repo.settle_attempt(WebsiteAttempt.model_validate(values), environment='test')
        with pytest.raises(MetricsError, match='conflict'):
            repo.settle_attempt(WebsiteAttempt.model_validate(values | {'subjectId':str(uuid4())}), environment='test')


def test_attempt_start_then_finish_updates_once_and_terminal_conflict_rejected(engine):
    now = utcnow()
    start = WebsiteAttempt.model_validate(dict(callId=str(uuid4()), operationId=str(uuid4()),
        subjectId=str(uuid4()), purpose='analysis.audit', ordinal=1, provider='openai',
        model='gpt-6-luna', promptVersion='prompt.v1', policyVersion='policy.v2',
        startedAt=now, state='started'))
    finish = WebsiteAttempt.model_validate(start.model_dump() | dict(state='succeeded',
        finishedAt=now, cost='0.01', currency='USD', costBasis='estimated'))
    with unit_of_work(engine) as s:
        repo = MetricRepository(s)
        assert repo.settle_attempt(start, environment='test')
        assert repo.settle_attempt(finish, environment='test')
        assert not repo.settle_attempt(finish, environment='test')
        with pytest.raises(MetricsError, match='conflict'):
            repo.settle_attempt(finish.model_copy(update={'cost': Decimal('0.02')}), environment='test')
    with unit_of_work(engine) as s:
        assert s.scalar(select(WebsiteProviderAttempt)).cost == Decimal('0.01')


def test_deleting_owner_erases_account_journal_preserves_visitors(engine, storage_factory):
    with unit_of_work(engine) as s:
        owner, *_ = storage_factory(s)
        repo = MetricRepository(s)
        repo.append(event(name='account_registered', subjectKind='account', subjectId=str(owner.id)),
                    source='backend_server', environment='test', received_at=utcnow())
        repo.append(event(), source='website_client', environment='test', received_at=utcnow())
        s.delete(owner)
    with unit_of_work(engine) as s:
        rows = s.scalars(select(MetricJournal)).all()
        assert len(rows) == 1
        assert rows[0].subject_kind == 'visitor'


def test_migration_0003_to_0004_preserves_jobs_and_calls(engine, storage_factory):
    from fitcheck_backend.storage.migrate import migration_config, run_migrations, check_schema
    from fitcheck_backend.config import Settings
    with engine.begin() as c:
        command.downgrade(migration_config(c), '0003')
    try:
        with unit_of_work(engine) as s:
            storage_factory(s)
        with engine.begin() as c:
            c.execute(text("INSERT INTO provider_calls(id,provider,operation,model,attempt,state,input_tokens,cost,currency,created_at) VALUES (:id,'deepseek','analysis','old',1,'succeeded',12,0.02,'USD',now())"), {'id':uuid4()})
        settings = Settings(database_url=os.environ['FITCHECK_TEST_DATABASE_URL'])
        run_migrations(settings)
        check_schema(settings)
        with engine.connect() as c:
            assert c.scalar(text('SELECT count(*) FROM jobs')) == 1
            assert c.scalar(text('SELECT input_tokens FROM provider_calls')) == 12
            assert c.scalar(text('SELECT version_num FROM alembic_version')) == '0006'
    finally:
        run_migrations(Settings(database_url=os.environ['FITCHECK_TEST_DATABASE_URL']))


@pytest.mark.parametrize('settled_before_delete', [False, True])
def test_erased_attempt_retains_accounting_and_all_other_conflict_checks(engine,settled_before_delete):
    from uuid import UUID
    from sqlalchemy import update
    now = utcnow()
    start = WebsiteAttempt(callId=uuid4(),operationId=uuid4(),subjectId=uuid4(),purpose='analysis.audit',
        ordinal=1,provider='openai',model='gpt-6-luna',promptVersion='v1',policyVersion='v1',startedAt=now,state='started')
    finish = WebsiteAttempt.model_validate(start.model_dump() | {'state':'succeeded','finishedAt':now,
        'inputTokens':100,'outputTokens':5,'cost':'0.01','currency':'USD','costBasis':'estimated'})
    with unit_of_work(engine) as session:
        MetricRepository(session).settle_attempt(finish if settled_before_delete else start,environment='test')
        session.execute(update(WebsiteProviderAttempt).values(subject_id=UUID(int=0)))
    with unit_of_work(engine) as session:
        repo = MetricRepository(session)
        assert repo.settle_attempt(finish,environment='test') is (not settled_before_delete)
        assert not repo.settle_attempt(finish,environment='test')
        assert not repo.settle_attempt(start,environment='test')
    conflicts = {'operation_id':uuid4(),'purpose':'analysis.generate','ordinal':2,'provider':'deepseek',
        'model':'different-model','prompt_version':'v2','policy_version':'v2','started_at':now-timedelta(seconds=1),
        'cost':Decimal('0.02'),'input_tokens':101,'state':'failed'}
    for field,value in conflicts.items():
        with pytest.raises(MetricsError,match='conflict'), unit_of_work(engine) as session:
            MetricRepository(session).settle_attempt(finish.model_copy(update={field:value}),environment='test')
    with pytest.raises(MetricsError,match='conflict'), unit_of_work(engine) as session:
        MetricRepository(session).settle_attempt(finish,environment='production')
    with unit_of_work(engine) as session:
        row = session.scalar(select(WebsiteProviderAttempt))
        assert row.subject_id == UUID(int=0) and row.cost == Decimal('0.01') and row.state == 'succeeded'

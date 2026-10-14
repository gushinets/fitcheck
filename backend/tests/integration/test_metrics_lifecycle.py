from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from analysis_fixtures import DATA
from job_fixtures import account, request
from fitcheck_backend.auth.access import AccountDeletionService
from fitcheck_backend.auth.email_service import EmailAuthService
from fitcheck_backend.auth.service import AuthService
from fitcheck_backend.contracts.domain import FreelancerProfile
from fitcheck_backend.jobs.admission import JobAdmission
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.job_queue import JobQueue
from fitcheck_backend.storage.job_publication import JobPublication
from fitcheck_backend.storage.metrics import MetricJournal
from fitcheck_backend.storage.models import Job, Owner, ProviderCall, User
from fitcheck_backend.storage.profile_repository import create_profile, update_profile

pytestmark = pytest.mark.integration


def rows(engine):
    with unit_of_work(engine) as s:
        return list(s.scalars(select(MetricJournal).order_by(MetricJournal.name)))


def registration(a, email='metrics@example.com'):
    return AuthService(a.engine, a.crypto, a.passwords, a.limiter, a.mailer, a.clock,
        metrics_environment='test').register(email, 'correct horse battery', '192.0.2.1')


def prepared(engine, a):
    owner, _ = account(engine)
    admission = JobAdmission(engine, a.limiter, metrics_environment='test')
    admitted = admission.start_analysis(owner_id=owner.id, request=request(),
        idempotency_key='one', client_ip='127.0.0.1')
    return owner, admission, admitted


def test_registration_profile_and_job_facts_commit_or_rollback_with_domain(engine, auth_components):
    a = auth_components
    issued = registration(a)
    EmailAuthService(engine, a.crypto, a.passwords, a.limiter, a.mailer, a.clock,
        metrics_environment='test').verify(issued.principal, a.mailer.messages[-1].token, '192.0.2.1')
    profile = FreelancerProfile.model_validate(DATA['profile'])
    with unit_of_work(engine) as s:
        create_profile(s, issued.principal.owner_id, profile, metrics_environment='test')
        update_profile(s, issued.principal.owner_id, 1, profile, metrics_environment='test')
    assert [r.name for r in rows(engine)] == ['account_registered', 'email_verified', 'profile_revision_saved']
    with pytest.raises(RuntimeError):
        with unit_of_work(engine) as s:
            update_profile(s, issued.principal.owner_id, 1, profile.model_copy(update={'specialization':'Changed'}), metrics_environment='test')
            raise RuntimeError('rollback')
    assert len(rows(engine)) == 3
    def fail(conn, cursor, statement, params, context, many):
        if statement.startswith('INSERT INTO metric_journal'):
            raise RuntimeError('forced metrics failure')
    event.listen(engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError):
            registration(a, 'rollback@example.com')
    finally:
        event.remove(engine, 'before_cursor_execute', fail)
    with unit_of_work(engine) as s:
        assert s.scalar(select(User).where(User.normalized_email=='rollback@example.com')) is None
    owner, admission, _ = prepared(engine, a)
    assert len([r for r in rows(engine) if r.name=='job_admitted']) == 1


def test_idempotent_admission_and_recovery_events_do_not_duplicate(engine, auth_components):
    owner, admission, admitted = prepared(engine, auth_components)
    assert admission.start_analysis(owner_id=owner.id, request=request(), idempotency_key='one', client_ip='127.0.0.1').job_id == admitted.job_id
    queue = JobQueue(engine, metrics_environment='test')
    lease = queue.claim()
    assert queue.heartbeat(lease)
    with unit_of_work(engine) as s:
        s.get(Job, lease.job_id).lease_expires_at = s.get(Job, lease.job_id).started_at - timedelta(seconds=1)
    assert queue.recover_expired() == 1
    assert queue.recover_expired() == 0
    second = queue.claim()
    assert second.execution_token != lease.execution_token
    records = rows(engine)
    assert len([r for r in records if r.name=='job_admitted']) == 1
    assert len([r for r in records if r.name=='job_execution_started']) == 2
    recovery = [r for r in records if r.name=='job_execution_recovered']
    assert len(recovery) == 1 and recovery[0].properties['executionToken'] == str(lease.execution_token)


def test_publication_failure_never_records_success(engine, auth_components):
    from fitcheck_backend.api.errors import ErrorBody
    _, _, admitted = prepared(engine, auth_components)
    lease = JobQueue(engine, metrics_environment='test').claim()
    publication = JobPublication(engine, metrics_environment='test')
    def fail(conn, cursor, statement, params, context, many):
        if statement.startswith('UPDATE jobs'):
            raise RuntimeError('forced domain failure')
    event.listen(engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError):
            publication.fail(lease, ErrorBody(code='timeout', message='Timeout', requestId=str(admitted.job_id)))
    finally:
        event.remove(engine, 'before_cursor_execute', fail)
    assert not any(r.name=='job_finished' for r in rows(engine))
    assert publication.fail(lease, ErrorBody(code='timeout', message='Timeout', requestId=str(admitted.job_id)))
    terminal = [r for r in rows(engine) if r.name=='job_finished']
    assert len(terminal)==1 and terminal[0].properties['outcome']=='failed'


def test_account_delete_erases_only_own_metrics_preserves_provider_accounting(engine, auth_components, storage_factory):
    a = auth_components
    first, other = registration(a), registration(a, 'other@example.com')
    with unit_of_work(engine) as s:
        owner, guest, *_ = storage_factory(s, kind='guest')
        guest.claimed_by_user_id, guest.claimed_at = first.principal.user_id, a.clock()
        s.add(ProviderCall(owner_id=first.principal.owner_id, provider='test', model='test', operation='analysis', attempt=1, state='succeeded', cost='0.01', currency='USD'))
    AccountDeletionService(engine, a.passwords, a.limiter, a.clock, metrics_environment='test').delete(first.principal, 'correct horse battery')
    records = rows(engine)
    assert [r.subject_id for r in records if r.subject_kind=='account'] == [other.principal.owner_id]
    deleted = [r for r in records if r.name=='account_deleted']
    assert len(deleted)==1 and deleted[0].subject_kind=='anonymous' and deleted[0].subject_id is None and deleted[0].owner_id is None
    with unit_of_work(engine) as s:
        assert s.get(Owner, owner.id) is None
        call=s.scalar(select(ProviderCall))
        assert call.owner_id is None and call.cost is not None


def test_erased_visitor_suppresses_late_server_fact_and_anonymizes_new_calls(engine):
    from types import SimpleNamespace
    from fitcheck_backend.metrics.collector import MetricsCollector
    from fitcheck_backend.metrics.contracts import AttemptBatch, WebsiteAttempt, WebsiteBatch, MetricEvent, ERASED_VISITOR_ID
    from fitcheck_backend.storage.base import utcnow
    from fitcheck_backend.storage.metrics import WebsiteProviderAttempt, MetricErasedVisitor
    now=utcnow()
    settings=SimpleNamespace(metrics_environment='test', metrics_campaign_codes=[])
    collector=MetricsCollector(engine, settings, lambda:now)
    visitor=uuid4()
    assert collector.delete_visitor(visitor)==0
    assert collector.delete_visitor(visitor)==0
    terminal=MetricEvent(eventId=uuid4(),name='analysis_finished',subjectId=visitor,
        operationId=uuid4(),occurredAt=now,properties={'outcome':'succeeded','durationMs':1})
    assert collector.ingest(WebsiteBatch(source='website_server',events=[terminal])).accepted==0
    attempt=WebsiteAttempt(callId=uuid4(),operationId=terminal.operation_id,subjectId=visitor,
        purpose='analysis.generate',ordinal=1,provider='deepseek',model='test',promptVersion='v1',
        policyVersion='v1',startedAt=now,state='started')
    assert collector.ingest_attempts(AttemptBatch(source='website_server',attempts=[attempt])).accepted==1
    finish=attempt.model_copy(update={'finished_at':now,'state':'succeeded','input_tokens':3})
    assert collector.ingest_attempts(AttemptBatch(source='website_server',attempts=[finish])).accepted==1
    assert collector.ingest_attempts(AttemptBatch(source='website_server',attempts=[finish])).duplicates==1
    with unit_of_work(engine) as s:
        assert not list(s.scalars(select(MetricJournal)))
        assert s.scalar(select(WebsiteProviderAttempt)).subject_id==ERASED_VISITOR_ID
        tombstone=s.scalar(select(MetricErasedVisitor))
        assert tombstone.erased_at==now and str(visitor) not in tombstone.visitor_digest


def test_guest_only_profile_facts_are_not_accounts(engine, storage_factory):
    with unit_of_work(engine) as s:
        owner, *_=storage_factory(s,kind='guest')
        create_profile(s,owner.id,FreelancerProfile.model_validate(DATA['profile']),metrics_environment='test')
    assert not rows(engine)


@pytest.mark.parametrize('recover', [False, True])
def test_owner_deletion_does_not_cycle_with_metrics_queue_locks(engine, auth_components, recover):
    from concurrent.futures import ThreadPoolExecutor
    from fitcheck_backend.storage.ownership import delete_owner
    first, _, first_job=prepared(engine,auth_components)
    second, _, second_job=prepared(engine,auth_components)
    queue=JobQueue(engine,metrics_environment='test')
    if recover:
        leases=[queue.claim(),queue.claim()]
        with unit_of_work(engine) as s:
            for lease in leases:
                job=s.get(Job,lease.job_id)
                job.lease_expires_at=job.started_at-timedelta(seconds=1)
    # Hold exactly the lock deletion takes before it visits the jobs. The queue
    # must skip that owner and transition another owner without waiting for it.
    with ThreadPoolExecutor(1) as pool:
        with unit_of_work(engine) as s:
            s.scalar(select(Owner).where(Owner.id==first.id).with_for_update())
            future=pool.submit(queue.recover_expired if recover else queue.claim)
            transitioned=future.result(timeout=5)
            assert transitioned==1 if recover else transitioned.job_id==second_job.job_id
            assert s.get(Job,first_job.job_id).status==('running' if recover else 'queued')
            delete_owner(s,first.id)
    records=rows(engine)
    name='job_execution_recovered' if recover else 'job_execution_started'
    assert len([r for r in records if r.name==name and r.owner_id==second.id])==1
    assert not [r for r in records if r.owner_id==first.id]

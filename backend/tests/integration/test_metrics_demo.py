from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from test_guest_sessions_http import guest, profile_http
from fitcheck_backend.metrics.collector import MetricsCollector
from fitcheck_backend.metrics.contracts import WebsiteBatch
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job, VacancyRecord, AnalysisRecord
from fitcheck_backend.storage.base import utcnow

pytestmark = pytest.mark.integration
KEY = {'X-FitCheck-Metrics-Key': 'demo-test-key'}


def setup(fixture):
    a, client, runtime, _, _ = fixture
    _, token = guest(client)
    identity = runtime.guests.resolve(token)
    settings = client.app.state.settings
    settings.metrics_enabled = True
    settings.metrics_environment = 'test'
    from pydantic import SecretStr
    settings.metrics_ingest_key = SecretStr('demo-test-key')
    collector = MetricsCollector(a.engine, settings, a.clock)
    client.app.state.metrics_collector = collector
    with unit_of_work(a.engine) as s:
        job = Job(owner_id=identity.owner_id, type='analysis', input={'mode': 'guest', 'sessionId': str(identity.session_id)},
                  idempotency_key=str(uuid4()), request_hash='a'*64,
                  status='succeeded', finished_at=utcnow())
        vacancy = VacancyRecord(owner_id=identity.owner_id, vacancy={})
        s.add_all([job, vacancy]); s.flush()
        result = AnalysisRecord(owner_id=identity.owner_id, job_id=job.id, job_type='analysis',
                                vacancy_id=vacancy.id, snapshot={}, analysis={})
        s.add(result); s.flush()
        return a, client, runtime, collector, identity, job.id, result.id


def event(a, job, result, visitor=None, **changes):
    return dict(eventId=str(uuid4()), name='analysis_result_viewed', occurredAt=a.clock().isoformat(),
                subjectId=str(visitor or uuid4()), operationId=str(job),
                properties={'flow': 'demo', 'resultId': str(result), 'locale': 'ru', 'inputMode': 'text'}, **changes)


def send(c, events):
    return c.post('/internal/metrics/events', json={'source': 'website_client', 'events': events}, headers=KEY)


def test_owned_view_replay_and_repeat(profile_http):
    a,c,_,_,identity,job,result=setup(profile_http)
    visitor=uuid4(); first=event(a,job,result,visitor)
    response=send(c,[first]); assert response.status_code==200,response.text
    assert send(c,[first]).json()=={'accepted':0,'duplicates':1}
    assert send(c,[event(a,job,result,visitor)]).status_code==200
    from fitcheck_backend.storage.metrics import MetricDemoLink, MetricJournal
    with unit_of_work(a.engine) as s:
        links=list(s.scalars(select(MetricDemoLink).order_by(MetricDemoLink.first_view.desc())))
        assert len(links)==2 and [x.first_view for x in links]==[True,False]
        assert all(x.guest_owner_id==identity.owner_id and x.job_id==job and x.result_id==result for x in links)
        assert all(x.subject_kind=='visitor' and x.owner_id is None for x in s.scalars(select(MetricJournal)))


def test_foreign_or_forged_result_never_gets_trusted_link(profile_http):
    a,c,_,_,_,job,result=setup(profile_http)
    assert send(c,[event(a,uuid4(),result),event(a,job,uuid4())]).status_code==200
    c.cookies.delete('__Host-fitcheck_guest'); guest(c)
    assert send(c,[event(a,job,result)]).status_code==200
    from fitcheck_backend.storage.metrics import MetricDemoLink
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(MetricDemoLink))==0


def test_attempt_before_admission_is_not_a_job(profile_http):
    a,c,_,_,identity,_,_=setup(profile_http)
    request=uuid4()
    payload=dict(eventId=str(uuid4()), name='analysis_requested',occurredAt=a.clock().isoformat(),
                 subjectId=str(uuid4()),properties={'flow':'demo','requestId':str(request),'locale':'en','inputMode':'url'})
    assert send(c,[payload]).status_code==200
    from fitcheck_backend.storage.metrics import MetricDemoLink
    with unit_of_work(a.engine) as s:
        link=s.scalar(select(MetricDemoLink))
        assert link.guest_owner_id==identity.owner_id and link.request_id==request and link.job_id is None


def test_concurrent_first_views_and_visitor_erasure(profile_http):
    a,_,_,collector,identity,job,result=setup(profile_http)
    visitor=uuid4()
    def ingest(_):
        return collector.ingest(WebsiteBatch(source='website_client',events=[event(a,job,result,visitor)]),guest_identity=identity)
    with ThreadPoolExecutor(2) as pool: list(pool.map(ingest,range(2)))
    from fitcheck_backend.storage.metrics import MetricDemoLink
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(MetricDemoLink).where(MetricDemoLink.first_view))==1
    assert collector.delete_visitor(visitor)==2
    ingest(None)
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(MetricDemoLink))==0


def test_claim_preserves_links_and_account_delete_erases_demo(profile_http):
    a,c,_,_,identity,job,result=setup(profile_http)
    visitor=uuid4(); first=event(a,job,result,visitor)
    assert send(c,[first]).status_code==200
    from fitcheck_backend.storage.ownership import transfer_guest_analyses, delete_owner
    from fitcheck_backend.storage.metrics import MetricDemoLink, MetricJournal
    account=profile_http[3].principal.owner_id
    with unit_of_work(a.engine) as s:
        assert transfer_guest_analyses(s,identity.owner_id,account)==1
    assert send(c,[first]).json()=={'accepted':0,'duplicates':1}
    assert send(c,[event(a,job,result,visitor)]).status_code==200
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(Job))==1
        assert s.scalar(select(func.count()).select_from(MetricDemoLink))==2
        assert s.get(AnalysisRecord,result).job_id==job
        delete_owner(s,account)
    assert send(c,[first]).status_code==200
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(MetricDemoLink))==0
        # Late browser claims can be observations, but never revive trusted proof.
        assert all(row.owner_id is None for row in s.scalars(select(MetricJournal)))


def test_expired_or_revoked_guest_is_only_an_unverified_observation(profile_http):
    a,c,_,_,identity,job,result=setup(profile_http)
    from fitcheck_backend.storage.models import GuestSessionRow
    from fitcheck_backend.storage.metrics import MetricDemoLink
    with unit_of_work(a.engine) as s:
        s.get(GuestSessionRow,identity.session_id).revoked_at=a.clock()
    assert send(c,[event(a,job,result)]).status_code==200
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(MetricDemoLink))==0


def test_metric_retention_cascades_proof_but_keeps_domain_result(profile_http):
    from datetime import timedelta
    from sqlalchemy import update
    from fitcheck_backend.metrics.retention import cleanup_metrics
    from fitcheck_backend.storage.metrics import MetricDemoLink, MetricJournal
    a,c,_,_,_,job,result=setup(profile_http)
    assert send(c,[event(a,job,result)]).status_code==200
    with unit_of_work(a.engine) as s:
        s.execute(update(MetricJournal).values(received_at=a.clock()-timedelta(days=181)))
    assert cleanup_metrics(a.engine,now=a.clock(),dry_run=False).deleted==1
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(MetricDemoLink))==0
        assert s.get(Job,job) is not None and s.get(AnalysisRecord,result) is not None

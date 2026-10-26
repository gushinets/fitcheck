import base64
import hashlib
import hmac
import json
from datetime import datetime, UTC, timedelta
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from fitcheck_backend.api.app import create_app
from fitcheck_backend.api.runtime import AuthRuntime
from fitcheck_backend.config import Settings
from fitcheck_backend.metrics.collector import MetricsCollector
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import User, Job, AnalysisRecord, VacancyRecord
from fitcheck_backend.storage.metric_identity import MetricIdentityTransition as Link

pytestmark=pytest.mark.integration
WEB='https://web.example.com'
PASSWORD='correct horse battery'
KEY='identity-test-key'


def assertion(a,visitor,path):
    ms=int(a.clock().timestamp()*1000)
    data=dict(v=1,environment='test',visitorId=str(visitor),cookieIssuedAt=ms-60000,
        issuedAt=ms,expiresAt=ms+120000,requestId=str(uuid4()),method='POST',path=path)
    encoded=base64.urlsafe_b64encode(json.dumps(data,separators=(',',':')).encode()).decode().rstrip('=')
    mac=hmac.new(KEY.encode(),('fitcheck:metrics:identity:v1:'+encoded).encode(),hashlib.sha256).digest()
    return encoded+'.'+base64.urlsafe_b64encode(mac).decode().rstrip('=')


@pytest.fixture
def identity_http(auth_components):
    a=auth_components; a.now[0]=datetime.now(UTC)
    settings=Settings(env='production',auth_enabled=True,auth_secret='78'*32,auth_web_base_url=WEB,
        database_url=a.engine.url.render_as_string(hide_password=False),allowed_origins=[WEB],
        guest_enabled=True,metrics_enabled=True,metrics_environment='test',metrics_ingest_key=KEY)
    runtime=AuthRuntime(settings,engine=a.engine,mailer=a.mailer,clock=a.clock)
    collector=MetricsCollector(a.engine,settings,a.clock)
    with TestClient(create_app(settings,auth_runtime=runtime,metrics_collector=collector),base_url='https://api.example.com') as c:
        yield a,c,runtime


def authenticate(fixture,visitor,*,kind='register',email='one@example.com',proof=True,password=PASSWORD):
    a,c,_=fixture; a.now[0]+=timedelta(seconds=1)
    csrf=c.get('/v1/auth/csrf',headers={'Origin':WEB}).json()['csrfToken']
    path='/v1/auth/'+kind
    headers={'Origin':WEB,'X-CSRF-Token':csrf}
    if proof:headers['X-FitCheck-Visitor-Proof']=assertion(a,visitor,path) if proof is True else proof
    return c.post(path,headers=headers,json={'email':email,'password':password})


def links(a):
    with unit_of_work(a.engine) as s:return list(s.scalars(select(Link).order_by(Link.occurred_at)))


def verify(a,response):
    with unit_of_work(a.engine) as s:s.get(User,UUID(response.json()['user']['id'])).email_verified_at=a.clock()


def test_registration_is_confirmed_once_without_rewriting_visitor(identity_http):
    a,c,r=identity_http; visitor=uuid4()
    response=authenticate(identity_http,visitor)
    assert response.status_code==201,response.text
    rows=links(a); assert len(rows)==1 and rows[0].kind=='registered'
    assert rows[0].visitor_id==visitor and rows[0].guest_owner_id is None
    issued=r.auth.session(c.cookies.get('__Host-fitcheck_session'))
    from fitcheck_backend.metrics.identity_proof import VisitorContext
    context=VisitorContext(visitor,a.clock()-timedelta(minutes=1),a.clock(),uuid4())
    r.identity.auth(context,issued,'registered')
    assert len(links(a))==1
    r.identity.auth(VisitorContext(uuid4(),context.cookie_issued_at,a.clock(),uuid4()),issued,'registered')
    assert len(links(a))==1 and links(a)[0].visitor_id==visitor
    assert authenticate(identity_http,visitor).status_code==409
    assert len(links(a))==1


@pytest.mark.parametrize('proof',[False,'forged'])
def test_missing_or_forged_context_keeps_registration_unattributed(identity_http,proof):
    a,_,_=identity_http
    assert authenticate(identity_http,uuid4(),proof=proof).status_code==201
    assert links(a)==[]


def test_mail_or_credentials_failure_never_creates_successful_link(identity_http):
    a,_,_=identity_http; a.mailer.fail=True
    assert authenticate(identity_http,uuid4()).status_code==503
    assert links(a)==[]
    a.mailer.fail=False
    assert authenticate(identity_http,uuid4(),kind='login',password='wrong password').status_code==401
    assert links(a)==[]


def test_analytics_failure_cannot_fail_successful_auth(identity_http,monkeypatch,caplog):
    from sqlalchemy.exc import SQLAlchemyError
    a,_,r=identity_http
    def fail(*args,**kwargs):raise SQLAlchemyError('private database detail')
    monkeypatch.setattr(r.identity,'_write_auth',fail)
    assert authenticate(identity_http,uuid4()).status_code==201
    assert links(a)==[]
    assert 'private database detail' not in caplog.text and PASSWORD not in caplog.text


def guest_result(fixture):
    from test_guest_sessions_http import guest
    a,c,r=fixture
    value,token=guest(c); identity=r.guests.resolve(token)
    with unit_of_work(a.engine) as s:
        job=Job(owner_id=identity.owner_id,type='analysis',input={'mode':'guest','sessionId':str(identity.session_id)},
            idempotency_key=str(uuid4()),request_hash='a'*64,status='succeeded',finished_at=a.clock())
        vacancy=VacancyRecord(owner_id=identity.owner_id,vacancy={});s.add_all([job,vacancy]);s.flush()
        result=AnalysisRecord(owner_id=identity.owner_id,job_id=job.id,job_type='analysis',vacancy_id=vacancy.id,snapshot={},analysis={})
        s.add(result);s.flush()
        return value,identity,job.id,result.id


def test_claim_receipt_and_late_demo_delivery_preserve_one_operation(identity_http):
    a,c,_=identity_http; visitor=uuid4()
    account=authenticate(identity_http,visitor);verify(a,account)
    guest,identity,job,result=guest_result(identity_http)
    a.now[0]+=timedelta(seconds=1)
    h={'Origin':WEB,'X-CSRF-Token':account.json()['csrfToken'],'X-Guest-CSRF-Token':guest['csrfToken'],
       'Idempotency-Key':'claim-once','X-FitCheck-Visitor-Proof':assertion(a,visitor,'/v1/guest-claims')}
    assert c.post('/v1/guest-claims',headers=h).json()['claimedCount']==1
    assert c.post('/v1/guest-claims',headers=h).json()['claimedCount']==1
    rows=links(a); assert [row.kind for row in rows]==['registered','claim']
    assert rows[1].guest_owner_id==identity.owner_id and rows[1].visitor_id==visitor
    # A delayed browser observation still proves the same guest/result after claim.
    payload=dict(eventId=str(uuid4()),name='analysis_result_viewed',occurredAt=(a.clock()-timedelta(milliseconds=1)).isoformat(),
        subjectId=str(visitor),operationId=str(job),properties={'flow':'demo','resultId':str(result)})
    response=c.post('/internal/metrics/events',json={'source':'website_client','events':[payload]},headers={'X-FitCheck-Metrics-Key':KEY})
    assert response.status_code==200,response.text
    from fitcheck_backend.metrics.identity_queries import claim_demo_events
    with unit_of_work(a.engine) as s:
        assert len(claim_demo_events(s,rows[1]))==1
        assert s.scalar(select(func.count()).select_from(Job))==1
        assert s.get(AnalysisRecord,result).job_id==job
    h['X-FitCheck-Visitor-Proof']=assertion(a,uuid4(),'/v1/guest-claims')
    assert c.post('/v1/guest-claims',headers=h).status_code==200
    assert len(links(a))==2 and links(a)[1].visitor_id==visitor


def test_logout_and_existing_account_login_have_half_open_windows(identity_http):
    from fitcheck_backend.metrics.identity_queries import identity_snapshot, account_at
    a,c,_=identity_http; visitor=uuid4()
    first=authenticate(identity_http,visitor); first_row=links(a)[0]
    a.now[0]+=timedelta(seconds=2); logout_at=a.clock()
    assert c.post('/v1/auth/logout',headers={'Origin':WEB,'X-CSRF-Token':first.json()['csrfToken']}).status_code==204
    assert authenticate(identity_http,visitor,email='two@example.com',proof=False).status_code==201
    assert authenticate(identity_http,visitor,kind='login',email='two@example.com').status_code==200
    rows=links(a); assert [row.kind for row in rows]==['registered','login']
    with unit_of_work(a.engine) as s:
        snapshot=identity_snapshot(s,'test',visitor,a.clock())
        assert account_at(snapshot,first_row.occurred_at).account_owner_id==first_row.account_owner_id
        assert account_at(snapshot,logout_at).account_owner_id is None
        assert account_at(snapshot,rows[1].occurred_at).account_owner_id==rows[1].account_owner_id
        assert account_at(snapshot,first_row.cookie_issued_at).account_owner_id is None
    assert rows[0].ended_at==logout_at


def test_visitor_erasure_and_late_auth_cannot_restore_link(identity_http):
    from fitcheck_backend.metrics.identity_proof import VisitorContext
    a,c,r=identity_http; visitor=uuid4()
    assert authenticate(identity_http,visitor).status_code==201
    issued=r.auth.session(c.cookies.get('__Host-fitcheck_session'))
    context=VisitorContext(visitor,a.clock()-timedelta(minutes=1),a.clock(),uuid4())
    c.app.state.metrics_collector.delete_visitor(visitor)
    r.identity.auth(context,issued,'registered')
    assert links(a)==[]


def test_session_pruning_keeps_confirmed_closure(identity_http):
    from fitcheck_backend.metrics.identity_queries import identity_snapshot, account_at
    from fitcheck_backend.operations.retention import cleanup
    from fitcheck_backend.storage.models import AuthSession
    a,c,_=identity_http; visitor=uuid4()
    response=authenticate(identity_http,visitor); original=links(a)[0]
    a.now[0]+=timedelta(seconds=2); end=a.clock()
    c.post('/v1/auth/logout',headers={'Origin':WEB,'X-CSRF-Token':response.json()['csrfToken']})
    a.now[0]+=timedelta(days=8)
    cleanup(a.engine,now=a.clock(),execute=True)
    with unit_of_work(a.engine) as s:
        assert s.get(AuthSession,original.auth_session_id) is None
        snapshot=identity_snapshot(s,'test',visitor,a.clock())
        assert account_at(snapshot,original.occurred_at).account_owner_id==original.account_owner_id
        assert account_at(snapshot,end).account_owner_id is None


def test_unarchived_missing_session_has_unknown_coverage(identity_http):
    from sqlalchemy import delete
    from fitcheck_backend.metrics.identity_queries import identity_snapshot, account_at
    from fitcheck_backend.storage.models import AuthSession
    a,_,_=identity_http; visitor=uuid4()
    authenticate(identity_http,visitor); original=links(a)[0]
    with unit_of_work(a.engine) as s:s.execute(delete(AuthSession).where(AuthSession.id==original.auth_session_id))
    with unit_of_work(a.engine) as s:
        result=account_at(identity_snapshot(s,'test',visitor,a.clock()),original.occurred_at)
        assert result.account_owner_id is None and result.reason=='missing_session_evidence'
        later=original.expires_at+timedelta(seconds=1)
        expired=account_at(identity_snapshot(s,'test',visitor,later),later)
        assert expired.account_owner_id is None and expired.reason=='no_confirmed_interval'


def test_switch_without_old_cookie_and_overlapping_logins_are_conservative(identity_http):
    from fitcheck_backend.metrics.identity_queries import identity_snapshot, account_at
    a,c,_=identity_http; visitor=uuid4()
    authenticate(identity_http,visitor)
    first=links(a)[0]
    c.cookies.delete('__Host-fitcheck_session')
    authenticate(identity_http,visitor,email='two@example.com')
    second=links(a)[1]
    with unit_of_work(a.engine) as s:
        snapshot=identity_snapshot(s,'test',visitor,a.clock())
        assert account_at(snapshot,second.occurred_at).account_owner_id==second.account_owner_id
        # Simulate overlapping server request intervals, not arrival order.
        s.get(Link,second.id).request_started_at=first.occurred_at-timedelta(milliseconds=1)
    with unit_of_work(a.engine) as s:
        result=account_at(identity_snapshot(s,'test',visitor,a.clock()),second.occurred_at)
        assert result.account_owner_id is None and result.reason=='ambiguous_sessions'
    c.cookies.delete('__Host-fitcheck_session')
    authenticate(identity_http,visitor,email='three@example.com')
    third=links(a)[2]
    with unit_of_work(a.engine) as s:
        assert account_at(identity_snapshot(s,'test',visitor,a.clock()),third.occurred_at).account_owner_id==third.account_owner_id


def test_account_erasure_preserves_other_account_and_anonymous_floor(identity_http):
    from fitcheck_backend.storage.ownership import delete_owner
    from fitcheck_backend.storage.metric_identity import MetricVisitorBoundary
    a,c,_=identity_http; visitor=uuid4()
    authenticate(identity_http,visitor); first=links(a)[0]
    c.cookies.delete('__Host-fitcheck_session')
    authenticate(identity_http,visitor,email='two@example.com'); second=links(a)[1]
    a.now[0]+=timedelta(seconds=2); erased_at=a.clock()
    with unit_of_work(a.engine) as s:delete_owner(s,first.account_owner_id,now=erased_at)
    assert [row.account_owner_id for row in links(a)]==[None,second.account_owner_id]
    erased=links(a)[0]
    assert erased.kind=='erased' and erased.source_id is None and erased.auth_session_id is None
    with unit_of_work(a.engine) as s:
        assert s.get(MetricVisitorBoundary,('test',visitor)).anonymous_floor>=erased_at
    # A later registration cannot inherit the deleted account's browser history.
    c.cookies.delete('__Host-fitcheck_session')
    authenticate(identity_http,visitor,email='three@example.com')
    assert links(a)[-1].anonymous_from>=erased_at


def test_session_archive_failure_does_not_fail_logout_or_prune_evidence(identity_http,monkeypatch):
    from fitcheck_backend.storage.models import AuthSession
    from fitcheck_backend.operations.retention import cleanup
    from fitcheck_backend.metrics import identity
    a,c,_=identity_http; visitor=uuid4()
    response=authenticate(identity_http,visitor); original=links(a)[0]
    monkeypatch.setattr(identity,'archive_sessions',lambda *args:False)
    assert c.post('/v1/auth/logout',headers={'Origin':WEB,'X-CSRF-Token':response.json()['csrfToken']}).status_code==204
    a.now[0]+=timedelta(days=8)
    cleanup(a.engine,now=a.clock(),execute=True)
    with unit_of_work(a.engine) as s:
        assert s.get(AuthSession,original.auth_session_id) is not None
        assert s.get(AuthSession,original.auth_session_id).revoked_at is not None


def test_identity_retention_is_bounded_and_keeps_business_account(identity_http):
    from fitcheck_backend.metrics.retention import cleanup_metrics
    from fitcheck_backend.storage.metric_identity import MetricVisitorBoundary
    a,_,_=identity_http; visitor=uuid4(); authenticate(identity_http,visitor)
    row=links(a)[0]; now=a.clock()+timedelta(days=181)
    # Other journal ledgers also share the global batch limit.
    for _ in range(8):
        result=cleanup_metrics(a.engine,now=now,dry_run=False,limit=1)
        assert result.processed<=1
        if result.processed==0:break
    assert links(a)==[]
    with unit_of_work(a.engine) as s:
        assert s.get(MetricVisitorBoundary,('test',visitor)) is None
        assert s.scalar(select(User).where(User.owner_id==row.account_owner_id)) is not None


def test_wrong_claim_proofs_and_unknown_visitor_never_invent_claim_link(identity_http):
    a,c,_=identity_http; visitor=uuid4()
    account=authenticate(identity_http,visitor); verify(a,account)
    guest,_,_,_=guest_result(identity_http)
    headers={'Origin':WEB,'X-CSRF-Token':account.json()['csrfToken'],'X-Guest-CSRF-Token':'x'*43,
        'Idempotency-Key':'claim','X-FitCheck-Visitor-Proof':assertion(a,visitor,'/v1/guest-claims')}
    assert c.post('/v1/guest-claims',headers=headers).status_code==403
    assert len(links(a))==1
    headers['X-Guest-CSRF-Token']=guest['csrfToken']
    assert c.post('/v1/guest-claims',headers=headers,json={'accountId':str(uuid4())}).status_code==400
    assert len(links(a))==1
    headers.pop('X-FitCheck-Visitor-Proof')
    assert c.post('/v1/guest-claims',headers=headers).status_code==200
    assert len(links(a))==1


@pytest.mark.parametrize('overlap',[False,True])
def test_erasing_switch_target_cannot_reassign_its_history(identity_http,overlap):
    from fitcheck_backend.storage.ownership import delete_owner
    from fitcheck_backend.metrics.identity_queries import identity_snapshot, account_at
    a,c,_=identity_http; visitor=uuid4()
    authenticate(identity_http,visitor); first=links(a)[0]
    c.cookies.delete('__Host-fitcheck_session')
    authenticate(identity_http,visitor,email='two@example.com'); second=links(a)[1]
    if overlap:
        with unit_of_work(a.engine) as s:
            s.get(Link,second.id).request_started_at=first.occurred_at-timedelta(milliseconds=1)
    a.now[0]+=timedelta(seconds=2)
    with unit_of_work(a.engine) as s:delete_owner(s,second.account_owner_id,now=a.clock())
    with unit_of_work(a.engine) as s:
        snapshot=identity_snapshot(s,'test',visitor,a.clock())
        assert account_at(snapshot,first.occurred_at).account_owner_id==first.account_owner_id
        assert account_at(snapshot,second.occurred_at).account_owner_id is None
        assert account_at(snapshot,a.clock()).account_owner_id is None
        assert all(row.account_owner_id!=second.account_owner_id for row in snapshot.transitions)
    c.cookies.delete('__Host-fitcheck_session')
    authenticate(identity_http,visitor,email='three@example.com'); third=links(a)[-1]
    with unit_of_work(a.engine) as s:
        assert account_at(identity_snapshot(s,'test',visitor,a.clock()),third.occurred_at).account_owner_id==third.account_owner_id


def test_account_erasure_cannot_restore_concurrently_erased_visitor(identity_http,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from fitcheck_backend.metrics.identity import account_boundary
    from fitcheck_backend.storage.metric_identity import MetricVisitorBoundary
    a,c,_=identity_http; visitor=uuid4(); authenticate(identity_http,visitor); original=links(a)[0]
    with unit_of_work(a.engine) as s:
        execute=s.execute
        def interleave(statement,*args,**kwargs):
            result=execute(statement,*args,**kwargs)
            if str(statement).startswith('SELECT DISTINCT metric_identity_transitions.environment'):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(c.app.state.metrics_collector.delete_visitor,visitor).result(timeout=5)
            return result
        monkeypatch.setattr(s,'execute',interleave)
        account_boundary(s,[original.account_owner_id],a.clock())
    with unit_of_work(a.engine) as s:
        assert s.get(MetricVisitorBoundary,('test',visitor)) is None
        assert list(s.scalars(select(Link).where(Link.visitor_id==visitor)))==[]


def test_rearchiving_cannot_restore_concurrently_erased_visitor(identity_http,monkeypatch):
    from fitcheck_backend.metrics.identity import archive_sessions
    from fitcheck_backend.storage.metric_identity import MetricVisitorBoundary
    a,c,_=identity_http; visitor=uuid4(); response=authenticate(identity_http,visitor)
    original=links(a)[0]
    c.post('/v1/auth/logout',headers={'Origin':WEB,'X-CSRF-Token':response.json()['csrfToken']})
    with unit_of_work(a.engine) as s:
        execute=s.execute
        def interleave(statement,*args,**kwargs):
            result=execute(statement,*args,**kwargs)
            if str(statement).startswith('SELECT metric_identity_transitions.environment'):
                c.app.state.metrics_collector.delete_visitor(visitor)
            return result
        monkeypatch.setattr(s,'execute',interleave)
        archive_sessions(s,[original.auth_session_id],a.clock())
    with unit_of_work(a.engine) as s:
        assert s.get(MetricVisitorBoundary,('test',visitor)) is None

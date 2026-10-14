from datetime import datetime, UTC, timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from fitcheck_backend.api.app import create_app
from fitcheck_backend.config import Settings
from fitcheck_backend.metrics.collector import MetricsCollector
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.metrics import MetricJournal, WebsiteProviderAttempt
from fitcheck_backend.metrics.repository import MetricRepository
from fitcheck_backend.metrics.contracts import MetricEvent, WebsiteAttempt
from fitcheck_backend.storage.models import Owner
pytestmark = pytest.mark.integration
NOW = datetime(2026,10,14,tzinfo=UTC)
KEY = {'X-FitCheck-Metrics-Key':'test-bridge-secret'}

@pytest.fixture
def metrics(engine):
    settings = Settings(metrics_enabled=True, metrics_environment='test', metrics_ingest_key='test-bridge-secret', database_url='postgresql://placeholder/test', metrics_campaign_codes=['launch'])
    clock = [NOW]
    collector = MetricsCollector(engine,settings,lambda:clock[0])
    with TestClient(create_app(settings,metrics_collector=collector)) as client:
        yield client,collector,clock

def event(**kwargs):
    return {'eventId':str(uuid4()),'name':'page_viewed','occurredAt':NOW.isoformat(),'subjectId':str(uuid4()),**kwargs}

def send(client,events,source='website_client'):
    return client.post('/internal/metrics/events',json={'source':source,'events':events},headers=KEY)

def count(engine):
    with engine.connect() as conn:
        return conn.scalar(select(func.count()).select_from(MetricJournal))

def test_internal_ingest_rejects_missing_key_and_forged_backend_source(metrics,engine):
    client,_,_ = metrics
    body = {'source':'website_client','events':[event()]}
    assert client.post('/internal/metrics/events',json=body).status_code == 401
    assert client.post('/internal/metrics/events?key=test-bridge-secret',json=body).status_code == 401
    assert send(client,[event()],source='backend_server').status_code == 400
    assert send(client,[event(name='account_registered',subjectKind='account')]).status_code == 400
    assert send(client,[event(name='analysis_finished',operationId=str(uuid4()),properties={'outcome':'succeeded','durationMs':1})]).status_code == 400
    assert send(client,[event(properties={'email':'private@example.com'})]).status_code == 400
    assert count(engine) == 0
    assert send(client,[event()]).json() == {'accepted':1,'duplicates':0}

def test_batch_21_and_32769_bytes_rejected(metrics,engine):
    client,_,_ = metrics
    assert send(client,[event() for _ in range(21)]).status_code == 400
    assert client.post('/internal/metrics/events',content=b' '*32769,headers={**KEY,'Content-Type':'application/json'}).status_code == 413
    assert count(engine) == 0

def test_clock_outside_five_minutes_uses_received_time(metrics,engine):
    client,_,clock = metrics
    payload = event(occurredAt=(NOW-timedelta(hours=1)).isoformat())
    assert send(client,[payload]).status_code == 200
    clock[0] += timedelta(seconds=10)
    assert send(client,[payload]).json() == {'accepted':0,'duplicates':1}
    with unit_of_work(engine) as session:
        row = session.scalar(select(MetricJournal))
        assert row.occurred_at == NOW and row.received_at == NOW and row.clock_adjusted

def test_conflicting_batch_rolls_back(metrics,engine):
    client,_,_ = metrics
    previous = event()
    assert send(client,[previous]).status_code == 200
    assert send(client,[event(),{**previous,'name':'history_viewed'}]).status_code == 409
    assert count(engine) == 1

def test_visitor_delete_cannot_select_account_subject(metrics,engine):
    client,_,_ = metrics
    subject = uuid4()
    assert send(client,[event(subjectId=str(subject)),event()]).status_code == 200
    with unit_of_work(engine) as session:
        session.add(Owner(id=subject,kind='user')); session.flush()
        MetricRepository(session).append(MetricEvent(eventId=uuid4(),name='account_registered',subjectId=subject,subjectKind='account',occurredAt=NOW),source='backend_server',environment='test',received_at=NOW)
        MetricRepository(session).settle_attempt(WebsiteAttempt(callId=uuid4(),operationId=uuid4(),subjectId=subject,purpose='analysis.generate',ordinal=1,provider='openai',model='gpt-6-luna',promptVersion='v1',policyVersion='v1',startedAt=NOW,state='started'),environment='test')
    assert client.delete(f'/internal/metrics/visitors/{subject}',headers=KEY).json() == {'deleted':1}
    with unit_of_work(engine) as session:
        assert session.scalar(select(func.count()).select_from(MetricJournal)) == 2
        assert session.scalar(select(WebsiteProviderAttempt)).subject_id != subject
        assert session.scalar(select(MetricJournal).where(MetricJournal.subject_id==subject)).subject_kind == 'account'

def test_campaign_normalization_and_first_touch(metrics,engine):
    client,_,_ = metrics
    subject = str(uuid4())
    first = event(subjectId=subject,properties={'campaign':'unknown'})
    assert send(client,[first,event(subjectId=subject,properties={'campaign':'launch'})]).status_code == 200
    assert send(client,[first]).json()['duplicates'] == 1
    with unit_of_work(engine) as session:
        assert [r.properties['campaign'] for r in session.scalars(select(MetricJournal))] == ['other','other']

def test_disabled():
    with TestClient(create_app(Settings(metrics_enabled=True))) as client:
        assert client.post('/internal/metrics/events',json={'source':'website_client','events':[event()]},headers=KEY).status_code == 503

def test_internal_origin_rejected(metrics):
    client,_,_ = metrics
    assert client.post('/internal/metrics/events',json={'source':'website_client','events':[event()]},headers={**KEY,'Origin':'https://example.com'}).status_code == 403


def test_attempt_endpoint_settlement_conflict_and_source(metrics,engine):
    client,_,_ = metrics
    attempt = {'callId':str(uuid4()),'operationId':str(uuid4()),'subjectId':str(uuid4()),
        'purpose':'analysis.generate','ordinal':1,'provider':'openai','model':'gpt-6-luna',
        'promptVersion':'v1','policyVersion':'v1','startedAt':NOW.isoformat(),'state':'started'}
    def post(attempts,source='website_server'):
        return client.post('/internal/metrics/attempts',json={'source':source,'attempts':attempts},headers=KEY)
    assert post([attempt],source='website_client').status_code == 400
    assert post([attempt]).json() == {'accepted':1,'duplicates':0}
    terminal = {**attempt,'state':'succeeded','finishedAt':(NOW+timedelta(seconds=1)).isoformat(),'inputTokens':10,'outputTokens':5}
    assert post([terminal]).json() == {'accepted':1,'duplicates':0}
    assert post([terminal]).json() == {'accepted':0,'duplicates':1}
    assert post([{**attempt,'callId':str(uuid4())},{**terminal,'outputTokens':6}]).status_code == 409
    with unit_of_work(engine) as session:
        assert session.scalar(select(func.count()).select_from(WebsiteProviderAttempt)) == 1


def test_http_rate_limit_is_shared_across_subjects(metrics,engine):
    client,_,_ = metrics
    for _ in range(60):
        assert send(client,[event()]).status_code == 200
    response = send(client,[event()])
    assert response.status_code == 429 and response.headers['Retry-After'] == '60'
    assert count(engine) == 60


def test_safe_logs_and_no_cors_bridge_header(metrics,caplog):
    client,_,_ = metrics
    subject = str(uuid4())
    response = client.delete(f'/internal/metrics/visitors/{subject}?secret=do-not-log',headers=KEY)
    assert response.status_code == 200
    assert subject not in caplog.text and 'test-bridge-secret' not in caplog.text and 'do-not-log' not in caplog.text
    response = client.options('/internal/metrics/events',headers={'Origin':'https://web.example',
        'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'x-fitcheck-metrics-key'})
    assert response.status_code == 403


def test_client_clock_at_tolerance_boundary_and_environment_not_caller_controlled(metrics,engine):
    client,_,_ = metrics
    payload = event(occurredAt=(NOW-timedelta(minutes=5)).isoformat())
    assert send(client,[payload]).status_code == 200
    with unit_of_work(engine) as session:
        row = session.scalar(select(MetricJournal))
        assert not row.clock_adjusted and row.environment == 'test'
    assert client.post('/internal/metrics/events',json={'source':'website_client','environment':'production','events':[event()]},headers=KEY).status_code == 400


@pytest.mark.parametrize('settled_before_delete', [False, True])
def test_deleted_visitor_attempt_can_settle_and_replay(metrics,engine,settled_before_delete):
    from decimal import Decimal
    from uuid import UUID
    client,_,_ = metrics
    subject = uuid4()
    start = {'callId':str(uuid4()),'operationId':str(uuid4()),'subjectId':str(subject),
        'purpose':'analysis.generate','ordinal':1,'provider':'openai','model':'gpt-6-luna',
        'promptVersion':'v1','policyVersion':'v1','startedAt':NOW.isoformat(),'state':'started'}
    finish = {**start,'state':'succeeded','finishedAt':(NOW+timedelta(seconds=1)).isoformat(),
              'inputTokens':100,'outputTokens':5,'cost':'0.01','currency':'USD','costBasis':'estimated'}
    def post(attempt):
        return client.post('/internal/metrics/attempts',json={'source':'website_server','attempts':[attempt]},headers=KEY)
    assert post(finish if settled_before_delete else start).status_code == 200
    assert client.delete(f'/internal/metrics/visitors/{subject}',headers=KEY).status_code == 200
    assert post(finish).json() == {'accepted':0 if settled_before_delete else 1,'duplicates':1 if settled_before_delete else 0}
    assert post(finish).json() == {'accepted':0,'duplicates':1}
    assert post(start).json() == {'accepted':0,'duplicates':1}
    assert post({**finish,'operationId':str(uuid4())}).status_code == 409
    assert post({**finish,'cost':'0.02'}).status_code == 409
    with unit_of_work(engine) as session:
        row = session.scalar(select(WebsiteProviderAttempt))
        assert row.subject_id == UUID(int=0) and row.state == 'succeeded'
        assert row.cost == Decimal('0.01') and row.input_tokens == 100
        assert session.scalar(select(func.count()).select_from(MetricJournal).where(MetricJournal.subject_id==subject)) == 0


def test_erased_visitor_sentinel_cannot_be_fresh_input(metrics,engine):
    from uuid import UUID
    client,_,_ = metrics
    assert send(client,[event(subjectId=str(UUID(int=0)))]).status_code == 400
    attempt = {'callId':str(uuid4()),'operationId':str(uuid4()),'subjectId':str(UUID(int=0)),
        'purpose':'analysis.generate','ordinal':1,'provider':'openai','model':'gpt-6-luna',
        'promptVersion':'v1','policyVersion':'v1','startedAt':NOW.isoformat(),'state':'started'}
    response = client.post('/internal/metrics/attempts',json={'source':'website_server','attempts':[attempt]},headers=KEY)
    assert response.status_code == 400
    with unit_of_work(engine) as session:
        assert session.scalar(select(func.count()).select_from(WebsiteProviderAttempt)) == 0

@pytest.mark.parametrize(('campaign', 'expected'), [
    (None, 'direct'), ('direct', 'direct'), ('other', 'other'),
    ('launch', 'launch'), ('unknown', 'other'),
])
def test_client_mapped_campaign_preserves_reserved_codes_and_first_touch(metrics, engine, campaign, expected):
    client, _, _ = metrics
    subject = str(uuid4())
    first = event(subjectId=subject, properties={} if campaign is None else {'campaign': campaign})
    assert send(client, [first]).json() == {'accepted': 1, 'duplicates': 0}
    assert send(client, [first]).json() == {'accepted': 0, 'duplicates': 1}
    assert send(client, [event(subjectId=subject, properties={'campaign': 'launch'})]).status_code == 200
    with unit_of_work(engine) as session:
        rows = session.scalars(select(MetricJournal).where(MetricJournal.subject_id == subject)).all()
        assert len(rows) == 2
        assert [row.properties['campaign'] for row in rows] == [expected, expected]

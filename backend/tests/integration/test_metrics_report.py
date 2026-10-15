from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import json

import pytest
from sqlalchemy import event as sa_event, update
from fitcheck_backend.metrics.report import MetricReportService
from fitcheck_backend.metrics.report_types import ReportOptions
from fitcheck_backend.metrics.contracts import MetricEvent, WebsiteAttempt
from fitcheck_backend.metrics.repository import MetricRepository
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import ProviderCall
from fitcheck_backend.storage.metrics import MetricCollection, WebsiteProviderAttempt

pytestmark=pytest.mark.integration
START=datetime(2026,1,1,tzinfo=timezone.utc)
END=START+timedelta(days=40)


def opts(environment='test',population='visitor'):
    return ReportOptions(start=START,end=END,environment=environment,population=population)


def metric(report,name,**dimensions):
    rows=[r for r in report.rows if r.metric==name and all(r.dimensions.get(k)==v for k,v in dimensions.items())]
    assert len(rows)==1,[(r.metric,r.dimensions) for r in rows]
    return rows[0]


def seed(engine):
    person,op=uuid4(),uuid4()
    with unit_of_work(engine) as s:
        repo=MetricRepository(s)
        for name,day,props,source in [('local_registration_completed',0,{},'website_client'),
            ('analysis_finished',1,{'outcome':'succeeded','durationMs':1000},'website_server'),
            ('analysis_result_viewed',2,{'resultId':str(op)},'website_client'),
            ('feedback_saved',3,{'resultId':str(op),'predictedScore':80,'correctedScore':70},'website_client'),
            ('feedback_saved',4,{'resultId':str(op),'predictedScore':80,'correctedScore':60},'website_client')]:
            when=START+timedelta(days=day)
            repo.append(MetricEvent(eventId=uuid4(),name=name,subjectKind='visitor',subjectId=person,
                occurredAt=when,operationId=op if source=='website_server' else None,properties=props),
                source=source,environment='test',received_at=when)
        for ordinal,purpose,cost,currency in [(1,'analysis.generate','1.00','USD'),(2,'analysis.audit','2.00','USD'),(3,'analysis.generate','5.00','EUR'),(4,'analysis.audit',None,None)]:
            repo.settle_attempt(WebsiteAttempt(callId=uuid4(),operationId=op,subjectId=person,purpose=purpose,ordinal=ordinal,
                provider='deepseek',model='deepseek-v4-flash',promptVersion='v1',policyVersion='v1',startedAt=START+timedelta(days=1)-timedelta(seconds=1),
                finishedAt=START+timedelta(days=1),state='succeeded',cost=cost,currency=currency,costBasis='estimated' if cost else 'unknown'),environment='test')
        s.execute(update(MetricCollection).values(available_from=START-timedelta(days=1)))
    return person,op


def test_join_fanout_cannot_multiply_calls_or_feedback(engine):
    person,op=seed(engine)
    report=MetricReportService(engine,clock=lambda:END).build(opts())
    assert metric(report,'provider_attempts',source='website_server').value==4
    assert metric(report,'feedback_coverage').numerator==1
    assert metric(report,'successful_operations',operation='analysis',source='website_server').value==1
    output=json.dumps(report.to_json())
    assert str(person) not in output and str(op) not in output


def test_audit_calls_not_analysis_count_and_unknown_cost_coverage_and_currencies_separate(engine):
    seed(engine)
    report=MetricReportService(engine,clock=lambda:END).build(opts())
    assert metric(report,'successful_operations',operation='analysis',source='website_server').value==1
    assert metric(report,'known_spend',currency='USD').value==3
    assert metric(report,'known_spend',currency='EUR').value==5
    assert metric(report,'unpriced_calls',source='website_server').value==1
    assert metric(report,'cost_coverage',source='website_server').value==75


def test_legacy_database_scope_cannot_be_assigned_from_report_options(engine):
    with unit_of_work(engine) as s:
        s.add(ProviderCall(id=uuid4(),owner_id=None,job_id=None,request_key=None,provider='deepseek',model='old',operation='analysis',attempt=1,state='succeeded',created_at=START,finished_at=START,cost=Decimal('9'),currency='USD'))
    absent=MetricReportService(engine,clock=lambda:END).build(opts(population='account'))
    assert not metric(absent,'provider_attempts',source='backend_server').available
    wrong=MetricReportService(engine,clock=lambda:END,backend_database_environment='development').build(opts(population='account'))
    assert not metric(wrong,'provider_attempts',source='backend_server').available
    scoped=MetricReportService(engine,clock=lambda:END,backend_database_environment='test').build(opts(population='account'))
    assert metric(scoped,'known_spend',currency='USD').value==9
    assert metric(scoped,'active_subjects',window_days='1',provenance='backend_server').value is None


def test_report_snapshot_timeout_and_future_end_guard(engine):
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany): statements.append(statement.lower())
    sa_event.listen(engine,'before_cursor_execute',capture)
    try:
        MetricReportService(engine,clock=lambda:END).build(opts())
    finally:
        sa_event.remove(engine,'before_cursor_execute',capture)
    assert any('statement_timeout' in s for s in statements)
    assert any('read only' in s for s in statements)
    with pytest.raises(ValueError,match='future'):
        MetricReportService(engine,clock=lambda:END-timedelta(seconds=1)).build(opts())


def test_scoped_backend_journal_survives_missing_legacy_scope(engine,storage_factory):
    with unit_of_work(engine) as s:
        owner,*_=storage_factory(s)
        repo=MetricRepository(s)
        for name,day,props,key in [('account_registered',0,{},f'account:{owner.id}:registered'),
            ('job_finished',1,{'jobType':'analysis','outcome':'succeeded','durationMs':1000},f'job:{uuid4()}:finished')]:
            when=START+timedelta(days=day)
            repo.append(MetricEvent(eventId=uuid4(),name=name,subjectKind='account',subjectId=owner.id,
                domainKey=key,occurredAt=when,properties=props),source='backend_server',environment='test',received_at=when)
    report=MetricReportService(engine,clock=lambda:END).build(opts(population='account'))
    assert metric(report,'activation',provenance='backend_server').value==100
    assert not metric(report,'provider_attempts',source='backend_server').available
    other=MetricReportService(engine,clock=lambda:END).build(opts(environment='production',population='account'))
    assert metric(other,'activation',provenance='backend_server').value is None


def test_erased_attempts_keep_spend_never_create_active_people(engine):
    from uuid import UUID
    with unit_of_work(engine) as s:
        MetricRepository(s).settle_attempt(WebsiteAttempt(callId=uuid4(),operationId=uuid4(),subjectId=uuid4(),
            purpose='analysis.generate',ordinal=1,provider='deepseek',model='deepseek-v4-flash',promptVersion='v1',policyVersion='v1',
            startedAt=START,finishedAt=START,state='succeeded',cost='4',currency='USD',costBasis='estimated'),environment='test')
        s.execute(update(WebsiteProviderAttempt).values(subject_id=UUID(int=0)))
    report=MetricReportService(engine,clock=lambda:END).build(opts())
    assert metric(report,'known_spend',currency='USD').value==4
    assert metric(report,'successful_operations',source='website_server',operation='analysis').value==0
    assert metric(report,'active_subjects',window_days='30').value is None


def test_cli_json_and_csv_use_same_aggregate_rows(engine,monkeypatch,tmp_path):
    from fitcheck_backend.metrics.__main__ import main
    from fitcheck_backend.config import Settings
    import fitcheck_backend.metrics.__main__ as cli
    import csv
    seed(engine)
    monkeypatch.setattr(cli,'create_engine',lambda settings:engine)
    monkeypatch.setattr(cli,'Settings',lambda:Settings(metrics_environment='production',metrics_database_environment='development'))
    common=['report','--start',START.isoformat(),'--end',END.isoformat(),'--environment','test','--population','visitor','--timezone','Europe/Moscow']
    json_path,csv_path=tmp_path/'report.json',tmp_path/'report.csv'
    assert main(common+['--output',str(json_path)])==0
    assert main(common+['--format','csv','--output',str(csv_path)])==0
    payload=json.loads(json_path.read_text())
    with csv_path.open() as stream: rows=list(csv.DictReader(stream))
    assert [(r['metric'],json.loads(r['dimensions'])) for r in rows]==[(r['metric'],r['dimensions']) for r in payload['rows']]
    assert all(r['environment']=='test' and r['timezone']=='Europe/Moscow' for r in rows)


def test_later_backfill_receipt_can_report_exact_historical_facts(engine,storage_factory):
    with unit_of_work(engine) as s:
        owner,*_=storage_factory(s)
        MetricRepository(s).append(MetricEvent(eventId=uuid4(),name='account_registered',subjectKind='account',
            subjectId=owner.id,occurredAt=START,domainKey=f'account:{owner.id}:registered'),
            source='reconstructed_backend',environment='test',received_at=END+timedelta(days=1))
    report=MetricReportService(engine,clock=lambda:END+timedelta(days=2)).build(opts(population='account'))
    assert metric(report,'registrations',provenance='reconstructed_backend').value==1


@pytest.mark.parametrize('state',['started','succeeded'])
def test_website_attempt_without_terminal_keeps_pending_and_cohort_completeness_unknown(engine,state):
    with unit_of_work(engine) as s:
        MetricRepository(s).settle_attempt(WebsiteAttempt(callId=uuid4(),operationId=uuid4(),subjectId=uuid4(),
            purpose='analysis.generate',ordinal=1,provider='deepseek',model='deepseek-v4-flash',promptVersion='v1',policyVersion='v1',
            startedAt=START,finishedAt=START+timedelta(seconds=1) if state=='succeeded' else None,state=state),environment='test')
    report=MetricReportService(engine,clock=lambda:END).build(opts())
    pending=metric(report,'pending_operations',source='website_server',operation='analysis',state='running')
    assert pending.value is None and not pending.available and pending.reason
    cost=metric(report,'cost_per_success',source='website_server',operation='analysis',currency='unknown')
    assert cost.coverage['pending_operations'] is None
    assert cost.coverage['cohort_completeness']=='unavailable'
    assert cost.coverage['unresolved_observed_operations']==1
    assert cost.denominator==0 and cost.value is None
    assert metric(report,'successful_operations',source='website_server',operation='analysis').value==0

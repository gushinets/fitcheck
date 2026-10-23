"""Current server controls; synthetic domain rows, no mail or provider sends."""
from datetime import datetime, timedelta, UTC
from uuid import uuid4
import pytest
from sqlalchemy import update
from fitcheck_backend.metrics.report import MetricReportService
from fitcheck_backend.metrics.report_types import ReportOptions
from fitcheck_backend.metrics.contracts import MetricEvent
from fitcheck_backend.metrics.repository import MetricRepository
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.metrics import MetricCollection
from fitcheck_backend.storage.metric_identity import MetricIdentityTransition as Link

pytestmark=pytest.mark.integration
START=datetime(2026,1,1,tzinfo=UTC)
END=START+timedelta(days=40)


def options(population='all',environment='test'):
    return ReportOptions(start=START,end=END,environment=environment,population=population)


def metric(report,name,**dimensions):
    rows=[r for r in report.rows if r.metric==name and all(r.dimensions.get(k)==v for k,v in dimensions.items())]
    assert len(rows)==1,[(r.metric,r.dimensions) for r in rows]
    return rows[0]


def seed_account(session,storage_factory,*,view=True,correction=60,day=0):
    from fitcheck_backend.storage.models import Owner, User, Job, VacancyRecord, AnalysisRecord, AnalysisAnnotation
    at=START+timedelta(days=day)
    owner=Owner(kind='user');session.add(owner);session.flush()
    user=User(owner_id=owner.id,normalized_email=f'{owner.id}@example.com',password_hash='synthetic',created_at=at)
    job=Job(owner_id=owner.id,type='analysis',input={'mode':'account'},idempotency_key=str(uuid4()),
        request_hash='a'*64,status='succeeded',created_at=at,finished_at=at+timedelta(hours=1))
    vacancy=VacancyRecord(owner_id=owner.id,vacancy={})
    session.add_all([user,job,vacancy]);session.flush()
    analysis=AnalysisRecord(owner_id=owner.id,job_id=job.id,job_type='analysis',vacancy_id=vacancy.id,
        snapshot={},analysis={'score':80},created_at=at+timedelta(hours=1))
    session.add(analysis);session.flush()
    annotation=AnalysisAnnotation(owner_id=owner.id,analysis_id=analysis.id,corrected_score=correction,
        note='private feedback text' if correction is not None else None,
        feedback_created_at=at+timedelta(days=2) if correction is not None else None,
        updated_at=at+timedelta(days=2))
    session.add(annotation)
    visitor=uuid4();source=uuid4()
    session.add(Link(environment='test',visitor_id=visitor,account_owner_id=owner.id,kind='registered',
        source_id=source,auth_session_id=source,cookie_issued_at=at-timedelta(days=1),
        request_started_at=at,occurred_at=at,anonymous_from=at-timedelta(days=1),
        expires_at=at+timedelta(days=7),ended_at=at+timedelta(days=7),end_basis='expired'))
    repo=MetricRepository(session)
    def event(name,when,subject,props=None,backend=False,operation=None):
        value=MetricEvent(eventId=uuid4(),name=name,subjectKind='account' if backend else 'visitor',
            subjectId=subject,occurredAt=when,properties=props or {},operationId=operation)
        repo.append(value,source='backend_server' if backend else 'website_client',environment='test',received_at=when)
        return value
    event('account_registered',at,owner.id,backend=True)
    event('job_finished',job.finished_at,owner.id,{'jobType':'analysis','outcome':'succeeded','durationMs':3600000},True,job.id)
    if view:
        event('analysis_result_viewed',at+timedelta(days=1),visitor,{'flow':'account','resultId':str(analysis.id)})
    session.execute(update(MetricCollection).values(available_from=START-timedelta(days=2)))
    session.flush()
    return owner,user,job,analysis,annotation,visitor


def report(engine,population='all',environment='test'):
    return MetricReportService(engine,backend_database_environment='test',clock=lambda:END).build(options(population,environment))


def test_snapshot_loads_minimal_domain_and_temporal_identity(engine,storage_factory):
    from fitcheck_backend.metrics.queries import load_snapshot
    from fitcheck_backend.metrics.identity_queries import account_at
    with unit_of_work(engine) as s:
        owner,_,job,analysis,_,visitor=seed_account(s,storage_factory)
    with engine.connect() as conn:
        data=load_snapshot(conn,options(),'test')
    assert data.server_backed
    fact=next(f for f in data.analyses if f.analysis_id==analysis.id)
    assert fact.job_id==job.id and fact.owner_id==owner.id
    assert fact.predicted_score==80 and fact.corrected_score==60
    assert not hasattr(fact,'note')
    assert account_at(data.identities[visitor],START+timedelta(days=1)).account_owner_id==owner.id


def test_product_activation_is_viewed_not_completed_and_feedback_is_latest(engine,storage_factory):
    with unit_of_work(engine) as s:
        first=seed_account(s,storage_factory,view=True)
        second=seed_account(s,storage_factory,view=False,correction=None)
    result=report(engine)
    activated=metric(result,'activation',population='account',provenance='backend_server')
    assert (activated.value,activated.numerator,activated.denominator)==(50,1,2)
    assert metric(result,'time_to_value_seconds',population='account',provenance='backend_server',percentile='p50').value==86400
    feedback=metric(result,'feedback_coverage',population='account')
    assert (feedback.value,feedback.numerator,feedback.denominator)==(50,1,2)
    assert metric(result,'score_correction',population='account',percentile='p50').value==20
    assert metric(result,'successful_operations',population='account',operation='analysis',provenance='deployment_database_scope').value==2
    from fitcheck_backend.storage.models import AnalysisAnnotation
    with unit_of_work(engine) as s:s.get(AnalysisAnnotation,first[3].id).corrected_score=30
    assert metric(report(engine),'score_correction',population='account',percentile='p50').value==50
    with unit_of_work(engine) as s:
        value=s.get(AnalysisAnnotation,first[3].id)
        value.corrected_score=None;value.note=None;value.feedback_created_at=None
    result=report(engine)
    assert metric(result,'feedback_coverage',population='account').numerator==0
    assert metric(result,'score_correction',population='account',percentile='p50').value is None
    import json
    output=json.dumps(result.to_json())
    assert 'private feedback text' not in output and str(first[0].id) not in output


def test_missing_identity_does_not_claim_zero_activation(engine,storage_factory):
    from sqlalchemy import delete
    with unit_of_work(engine) as s:
        seed_account(s,storage_factory)
        s.execute(delete(Link))
    row=metric(report(engine),'activation',population='account',provenance='backend_server')
    assert row.value is None and not row.available and row.reason
    assert row.coverage['excluded_unlinked_registrations']==1


def test_unknown_domain_scope_never_confirms_account_result(engine,storage_factory):
    with unit_of_work(engine) as s:seed_account(s,storage_factory)
    result=MetricReportService(engine,clock=lambda:END).build(options())
    row=metric(result,'activation',population='account',provenance='backend_server')
    assert not row.available and row.value is None


def append_view(session,visitor,analysis,at,*,operation=None,flow='account'):
    value=MetricEvent(eventId=uuid4(),name='analysis_result_viewed',subjectKind='visitor',subjectId=visitor,
        occurredAt=at,operationId=operation,properties={'resultId':str(analysis),'flow':flow})
    MetricRepository(session).append(value,source='website_client',environment='test',received_at=at)
    return value


@pytest.mark.parametrize('case',['foreign_result','wrong_job','missing_session','overlap','erased_switch'])
def test_uncertain_or_foreign_views_do_not_activate(engine,storage_factory,case):
    from sqlalchemy import delete
    from fitcheck_backend.storage.ownership import delete_owner
    with unit_of_work(engine) as s:
        first=seed_account(s,storage_factory,view=False)
        second=seed_account(s,storage_factory,view=False)
        one=s.query(Link).filter(Link.visitor_id==first[-1]).one()
        two=s.query(Link).filter(Link.visitor_id==second[-1]).one()
        target=first[3].id;operation=None
        if case=='foreign_result':target=second[3].id
        if case=='wrong_job':operation=second[2].id
        if case=='missing_session':one.ended_at=None;one.end_basis=None
        if case in {'overlap','erased_switch'}:
            two.visitor_id=first[-1];two.occurred_at=START+timedelta(hours=1)
            two.request_started_at=START-timedelta(seconds=1) if case=='overlap' else two.occurred_at
            target=second[3].id
        append_view(s,first[-1],target,START+timedelta(days=1),operation=operation)
        if case=='erased_switch':
            s.flush();delete_owner(s,second[0].id,now=START+timedelta(days=2))
    result=report(engine)
    row=metric(result,'activation',population='account',provenance='backend_server')
    assert row.numerator==0
    assert row.coverage['unknown_account_views']


def test_repeated_view_and_legacy_registration_never_duplicate_current_counts(engine,storage_factory):
    with unit_of_work(engine) as s:
        value=seed_account(s,storage_factory)
        append_view(s,value[-1],value[3].id,START+timedelta(days=2))
        legacy=MetricEvent(eventId=uuid4(),name='local_registration_completed',subjectKind='visitor',
            subjectId=uuid4(),occurredAt=START,properties={})
        repo=MetricRepository(s)
        assert repo.append(legacy,source='website_client',environment='test',received_at=START)
        assert not repo.append(legacy,source='website_client',environment='test',received_at=START)
    result=report(engine)
    assert metric(result,'registrations',population='account',provenance='backend_server').value==1
    assert metric(result,'registrations',population='visitor').value==1
    assert metric(result,'activation',population='account',provenance='backend_server').numerator==1
    assert metric(result,'feedback_coverage',population='account').denominator==1


def test_mature_window_is_half_open_and_immature_is_unavailable(engine,storage_factory):
    from fitcheck_backend.storage.metrics import MetricJournal
    with unit_of_work(engine) as s:
        value=seed_account(s,storage_factory,view=False,day=38)
        append_view(s,value[-1],value[3].id,START+timedelta(days=39))
    row=metric(report(engine),'activation',population='account',provenance='backend_server')
    assert row.value is None and not row.available and row.denominator==0
    assert row.coverage['immature_registrations']==1


def test_cli_current_json_csv_and_financial_totals_are_identical(engine,storage_factory,monkeypatch,tmp_path):
    import csv,json
    from decimal import Decimal
    from fitcheck_backend.storage.models import ProviderCall
    from fitcheck_backend.metrics.__main__ import main
    import fitcheck_backend.metrics.__main__ as cli
    from fitcheck_backend.config import Settings
    with unit_of_work(engine) as s:
        value=seed_account(s,storage_factory)
        for ordinal in range(2):
            s.add(ProviderCall(owner_id=value[0].id,job_id=value[2].id,request_key=None,
                provider='deepseek',model='synthetic',operation='analysis',attempt=ordinal+1,state='succeeded',
                created_at=START,finished_at=START+timedelta(hours=1),cost=Decimal('1.25'),currency='USD',
                input_tokens=100,output_tokens=20,cost_basis='estimated'))
        append_view(s,value[-1],value[3].id,START+timedelta(days=3))
    monkeypatch.setattr(cli,'create_engine',lambda settings:engine)
    monkeypatch.setattr(cli,'Settings',lambda:Settings(metrics_database_environment='test'))
    args=['report','--start',START.isoformat(),'--end',END.isoformat(),'--environment','test','--population','all']
    json_path=tmp_path/'report.json';csv_path=tmp_path/'report.csv'
    assert main(args+['--output',str(json_path)])==0
    assert main(args+['--format','csv','--output',str(csv_path)])==0
    payload=json.loads(json_path.read_text())
    with csv_path.open() as stream:rows=list(csv.DictReader(stream))
    for expected,actual in zip(payload['rows'],rows,strict=True):
        assert expected['metric']==actual['metric']
        assert expected['dimensions']==json.loads(actual['dimensions'])
        for key in ('value','numerator','denominator'):
            assert actual[key]==('' if expected[key] is None else str(expected[key]))
    result=report(engine)
    assert metric(result,'provider_attempts',source='backend_server').value==2
    assert metric(result,'known_spend',source='backend_server',currency='USD').value==Decimal('2.50')
    assert metric(result,'ai_tokens',source='backend_server',token_type='input_tokens').value==200
    assert str(value[0].id) not in json.dumps(payload)


def test_demo_before_registration_claim_stays_one_guest_operation(engine,storage_factory):
    from fitcheck_backend.storage.models import Owner, Guest, Job, VacancyRecord, AnalysisRecord
    from fitcheck_backend.storage.metrics import MetricDemoLink
    from fitcheck_backend.storage.ownership import transfer_guest_analyses
    with unit_of_work(engine) as s:
        account=seed_account(s,storage_factory,view=False,correction=None,day=2)
        visitor=account[-1];registered=s.query(Link).filter(Link.visitor_id==visitor).one()
        registered.cookie_issued_at=START-timedelta(days=1);registered.anonymous_from=registered.cookie_issued_at
        owner=Owner(kind='guest');s.add(owner);s.flush()
        guest=Guest(owner_id=owner.id,expires_at=END);s.add(guest)
        job=Job(owner_id=owner.id,type='analysis',input={'mode':'guest','sessionId':str(uuid4())},
            idempotency_key=str(uuid4()),request_hash='b'*64,status='succeeded',created_at=START,
            finished_at=START+timedelta(hours=1))
        vacancy=VacancyRecord(owner_id=owner.id,vacancy={});s.add_all([job,vacancy]);s.flush()
        analysis=AnalysisRecord(owner_id=owner.id,job_id=job.id,job_type='analysis',vacancy_id=vacancy.id,
            snapshot={},analysis={'score':70},created_at=job.finished_at)
        s.add(analysis);s.flush()
        repo=MetricRepository(s)
        for name,hour in [('page_viewed',0),('vacancy_input_started',.1),('analysis_requested',.2),('analysis_result_viewed',2)]:
            props={'campaign':'direct'} if name=='page_viewed' else {'flow':'demo'}
            if name=='analysis_result_viewed':props['resultId']=str(analysis.id)
            event=MetricEvent(eventId=uuid4(),name=name,subjectKind='visitor',subjectId=visitor,
                occurredAt=START+timedelta(hours=hour),operationId=job.id if name=='analysis_result_viewed' else None,properties=props)
            repo.append(event,source='website_client',environment='test',received_at=event.occurred_at)
            if name!='page_viewed':
                s.add(MetricDemoLink(event_id=event.event_id,environment='test',visitor_id=visitor,guest_owner_id=owner.id,
                    job_id=job.id if name=='analysis_result_viewed' else None,result_id=analysis.id if name=='analysis_result_viewed' else None,
                    first_view=name=='analysis_result_viewed'))
        s.flush()
        assert transfer_guest_analyses(s,owner.id,account[0].id)==1
        s.add(Link(environment='test',visitor_id=visitor,account_owner_id=account[0].id,guest_owner_id=owner.id,
            kind='claim',source_id=uuid4(),auth_session_id=registered.auth_session_id,
            cookie_issued_at=registered.cookie_issued_at,request_started_at=START+timedelta(days=2),
            occurred_at=START+timedelta(days=2),expires_at=None))
        s.execute(update(MetricCollection).values(available_from=START-timedelta(days=2)))
    result=report(engine)
    assert metric(result,'funnel',funnel='demo',step='analysis_result_viewed').numerator==1
    assert metric(result,'funnel',funnel='visit_to_registration').value==100
    assert metric(result,'funnel',funnel='demo_to_registration').value==100
    assert metric(result,'activation',population='account',provenance='backend_server').numerator==0
    assert metric(result,'activation',population='visitor').numerator==1
    assert metric(result,'successful_operations',population='visitor',operation='analysis',provenance='server_guest_domain').value==1
    assert metric(result,'successful_operations',population='account',operation='analysis',provenance='deployment_database_scope').value==1
    with unit_of_work(engine) as s:
        assert s.get(AnalysisRecord,analysis.id).job_id==job.id
        assert s.get(Job,job.id).owner_id==account[0].id


def test_observed_activity_does_not_require_retained_registration_event(engine,storage_factory):
    from sqlalchemy import delete
    from fitcheck_backend.storage.metrics import MetricJournal
    with unit_of_work(engine) as s:
        seed_account(s,storage_factory)
        s.execute(delete(MetricJournal).where(MetricJournal.name=='account_registered'))
    result=report(engine)
    row=metric(result,'feature_adoption',population='account',provenance='backend_server',feature='analysis')
    assert row.numerator==1 and row.denominator==1


def test_funnel_accepts_initial_cookie_page_clock_skew_without_crossing_prior_account(engine,storage_factory):
    from fitcheck_backend.storage.metrics import MetricJournal
    with unit_of_work(engine) as s:
        value=seed_account(s,storage_factory)
        link=s.query(Link).filter(Link.visitor_id==value[-1]).one()
        link.cookie_issued_at=START;link.anonymous_from=START
        event=MetricEvent(eventId=uuid4(),name='page_viewed',subjectKind='visitor',subjectId=value[-1],
            occurredAt=START-timedelta(milliseconds=1),properties={'campaign':'direct'})
        MetricRepository(s).append(event,source='website_client',environment='test',received_at=START)
        s.execute(update(MetricCollection).values(available_from=START-timedelta(days=2)))
    service=MetricReportService(engine,backend_database_environment='test',clock=lambda:END)
    opt=ReportOptions(start=START-timedelta(hours=1),end=END,population='all',environment='test')
    assert metric(service.build(opt),'funnel',funnel='visit_to_registration').numerator==1
    with unit_of_work(engine) as s:
        link=s.query(Link).filter(Link.visitor_id==value[-1]).one()
        link.cookie_issued_at=START-timedelta(days=1)  # Now anonymous_from is a prior-account boundary.
    assert metric(service.build(opt),'funnel',funnel='visit_to_registration').numerator==0


def test_failed_job_is_technical_failure_not_product_activation(engine,storage_factory):
    from fitcheck_backend.storage.models import Job
    with unit_of_work(engine) as s:
        value=seed_account(s,storage_factory,view=False)
        failed=Job(owner_id=value[0].id,type='analysis',input={'mode':'account'},idempotency_key=str(uuid4()),
            request_hash='c'*64,status='failed',created_at=START,finished_at=START+timedelta(hours=1),
            error={'code':'upstream_error'})
        s.add(failed)
        # Establish observation history, without claiming that a result was viewed.
        event=MetricEvent(eventId=uuid4(),name='page_viewed',subjectKind='visitor',subjectId=value[-1],
            occurredAt=START,properties={'campaign':'direct'})
        MetricRepository(s).append(event,source='website_client',environment='test',received_at=START)
        s.execute(update(MetricCollection).values(available_from=START-timedelta(days=2)))
    result=report(engine)
    assert metric(result,'operation_success_rate',operation='analysis',provenance='deployment_database_scope').value==50
    assert metric(result,'operation_errors',operation='analysis',error_code='upstream_error',provenance='deployment_database_scope').value==1
    assert metric(result,'activation',population='account',provenance='backend_server').numerator==0
    assert metric(result,'time_to_value_seconds',population='account',provenance='backend_server',percentile='p50').value is None

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


@pytest.mark.parametrize('remove_activated', [False, True])
def test_missing_registration_cohort_is_unavailable_in_cli_json_and_csv(engine,storage_factory,monkeypatch,tmp_path,remove_activated):
    import csv
    import json
    from sqlalchemy import delete, select
    from fitcheck_backend.metrics.__main__ import main
    from fitcheck_backend.storage.metrics import MetricJournal

    with unit_of_work(engine) as s:
        first=seed_account(s,storage_factory,view=True)
        second=seed_account(s,storage_factory,view=False,correction=None)
    control=report(engine)
    dims={'population':'account','provenance':'backend_server'}
    activation=metric(control,'activation',**dims)
    assert (activation.value,activation.numerator,activation.denominator)==(50,1,2)
    lost=first if remove_activated else second
    with unit_of_work(engine) as s:
        fact=s.scalar(select(MetricJournal).where(MetricJournal.name=='account_registered',MetricJournal.subject_id==lost[0].id))
        saved=MetricEvent(eventId=fact.event_id,name=fact.name,subjectKind='account',subjectId=fact.subject_id,
            occurredAt=fact.occurred_at,properties=fact.properties)
        s.execute(delete(MetricJournal).where(MetricJournal.event_id==fact.event_id))

    monkeypatch.setenv('FITCHECK_DATABASE_URL',engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv('FITCHECK_METRICS_DATABASE_ENVIRONMENT','test')
    args=['report','--start',START.isoformat(),'--end',END.isoformat(),'--environment','test','--population','account']
    for fmt in ('json','csv'):
        assert main(args+['--format',fmt,'--output',str(tmp_path/f'report.{fmt}')])==0
    exported=json.loads((tmp_path/'report.json').read_text())['rows']
    with (tmp_path/'report.csv').open() as stream:
        csv_rows=list(csv.DictReader(stream))
    names={'registrations','activation','time_to_value_seconds','onboarding','email_verification'}
    selected=[r for r in exported if r['metric'] in names and all(r['dimensions'].get(k)==v for k,v in dims.items())]
    assert len(selected)==6
    for value in selected:
        assert value['available'] is False and value['value'] is None
        assert 'registration' in value['reason'].lower()
        assert value['coverage']['missing_domain_registration_facts']==1
        csv_value=next(r for r in csv_rows if r['metric']==value['metric'] and json.loads(r['dimensions'])==value['dimensions'])
        assert csv_value['available']=='False' and csv_value['value']==''
        assert csv_value['reason']==value['reason']
        assert json.loads(csv_value['coverage'])==value['coverage']
    # Removing an observation cannot alter successful domain jobs or saved feedback.
    after=report(engine)
    assert metric(after,'feedback_coverage',population='account')==metric(control,'feedback_coverage',population='account')
    assert metric(after,'successful_operations',population='account',operation='analysis',provenance='deployment_database_scope').value==2
    # Restoring the fact recovers the original cohort and first-view TTV.
    with unit_of_work(engine) as s:
        MetricRepository(s).append(saved,source='backend_server',environment='test',received_at=saved.occurred_at)
    restored=report(engine)
    assert metric(restored,'activation',**dims)==activation
    assert metric(restored,'time_to_value_seconds',**dims,percentile='p50').value==86400


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
    from fitcheck_backend.operations.retention import cleanup
    assert cleanup(engine,now=END,execute=True)['jobs']==1
    after=report(engine)
    assert metric(after,'provider_attempts',source='backend_server').value==2
    assert metric(after,'known_spend',source='backend_server',currency='USD').value==Decimal('2.50')
    assert metric(after,'ai_tokens',source='backend_server',token_type='input_tokens').value==200
    assert metric(after,'successful_operations',operation='analysis',provenance='deployment_database_scope').value==1


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
    from fitcheck_backend.operations.retention import cleanup
    from fitcheck_backend.storage.analysis_operation import AnalysisOperationProof
    assert cleanup(engine,now=END,execute=True)['jobs']==2
    after=report(engine)
    assert metric(after,'successful_operations',population='visitor',operation='analysis',provenance='server_guest_domain').value==1
    assert metric(after,'successful_operations',population='account',operation='analysis',provenance='deployment_database_scope').value==1
    assert metric(after,'activation',population='account',provenance='backend_server').numerator==0
    with unit_of_work(engine) as s:
        assert s.get(AnalysisRecord,analysis.id).job_id is None
        proof=s.get(AnalysisOperationProof,analysis.id)
        assert proof.job_id==job.id and proof.mode=='guest'
        assert transfer_guest_analyses(s,owner.id,account[0].id)==0


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


@pytest.mark.parametrize('viewed',[True,False])
def test_real_job_cleanup_preserves_confirmed_product_cohorts(engine,storage_factory,viewed):
    from sqlalchemy import select,func
    from fitcheck_backend.operations.retention import cleanup
    from fitcheck_backend.storage.models import AnalysisRecord,Job
    from fitcheck_backend.storage.metrics import MetricJournal
    with unit_of_work(engine) as s:
        account=seed_account(s,storage_factory,view=viewed)
        when=START+timedelta(days=31,hours=1)
        MetricRepository(s).append(MetricEvent(eventId=uuid4(),name='profile_revision_saved',
            subjectKind='account',subjectId=account[0].id,occurredAt=when,properties={'revision':1}),
            source='backend_server',environment='test',received_at=when)
    before=report(engine,'account')
    assert cleanup(engine,now=END,execute=True)['jobs']==1
    after=report(engine,'account')
    for name,dims in [('activation',{'provenance':'backend_server'}),
                      ('retention',{'provenance':'backend_server','day':'30'}),
                      ('feedback_coverage',{})]:
        old=metric(before,name,**dims);new=metric(after,name,**dims)
        assert (new.value,new.numerator,new.denominator,new.available)==(old.value,old.numerator,old.denominator,old.available)
        if viewed or name=='feedback_coverage':assert (new.value,new.numerator,new.denominator)==(100,1,1)
    assert metric(after,'activation',provenance='backend_server').numerator==int(viewed)
    with unit_of_work(engine) as s:
        assert s.get(Job,account[2].id) is None
        assert s.get(AnalysisRecord,account[3].id).job_id is None
        assert s.scalar(select(func.count()).select_from(MetricJournal).where(MetricJournal.name=='analysis_result_viewed'))==int(viewed)


@pytest.mark.parametrize('population',['visitor','all'])
def test_current_session_rows_in_postgresql_cli_json_and_csv(engine,monkeypatch,tmp_path,population):
    import csv,json
    from fitcheck_backend.metrics.__main__ import main
    from fitcheck_backend.config import Settings
    import fitcheck_backend.metrics.__main__ as cli
    visitor,sid=uuid4(),uuid4()
    with unit_of_work(engine) as s:
        repo=MetricRepository(s)
        for name,props in [('session_started',{}),('visible_activity',{'activeMs':15000}),('profile_saved',{})]:
            value=MetricEvent(eventId=uuid4(),name=name,subjectKind='visitor',subjectId=visitor,
                sessionId=sid,occurredAt=START+timedelta(days=1),properties=props)
            assert repo.append(value,source='website_client',environment='test',received_at=value.occurred_at)
            assert not repo.append(value,source='website_client',environment='test',received_at=value.occurred_at)
        s.execute(update(MetricCollection).values(available_from=START-timedelta(days=2)))
    monkeypatch.setattr(cli,'create_engine',lambda settings:engine)
    monkeypatch.setattr(cli,'Settings',lambda:Settings(metrics_database_environment='test'))
    args=['report','--start',START.isoformat(),'--end',END.isoformat(),'--environment','test','--population',population]
    for fmt in ('json','csv'):
        assert main(args+['--format',fmt,'--output',str(tmp_path/('sessions.'+fmt))])==0
    rows=json.loads((tmp_path/'sessions.json').read_text())['rows']
    with (tmp_path/'sessions.csv').open() as stream:csv_rows=list(csv.DictReader(stream))
    for name,expected in [('session_frequency',1),('session_duration_seconds',15)]:
        row=next(r for r in rows if r['metric']==name)
        csv_row=next(r for r in csv_rows if r['metric']==name)
        assert row['available'] and row['value']==expected and float(csv_row['value'])==expected
        assert row['dimensions']['population']=='visitor'
        assert json.loads(csv_row['dimensions'])==row['dimensions']


def test_archived_operation_is_idempotent_and_cascades_with_analysis(engine,storage_factory):
    from sqlalchemy import select,func,delete
    from fitcheck_backend.storage.models import AnalysisRecord
    from fitcheck_backend.storage.analysis_operation import AnalysisOperationProof as Proof
    from fitcheck_backend.metrics.analysis_operation import archive_analysis_operations
    from fitcheck_backend.operations.retention import cleanup
    with unit_of_work(engine) as s:
        account=seed_account(s,storage_factory)
        archive_analysis_operations(s,[account[2].id],END)
        archive_analysis_operations(s,[account[2].id],END)
    assert cleanup(engine,now=END,execute=True)['jobs']==1
    assert cleanup(engine,now=END,execute=True)['jobs']==0
    with unit_of_work(engine) as s:
        assert s.scalar(select(func.count()).select_from(Proof))==1
        proof=s.get(Proof,account[3].id)
        assert proof.job_id==account[2].id and proof.mode=='account'
        s.execute(delete(AnalysisRecord).where(AnalysisRecord.id==account[3].id))
        archive_analysis_operations(s,[account[2].id],END)
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(Proof))==0
    assert metric(report(engine),'activation',population='account',provenance='backend_server').numerator==0


def test_archival_failure_rolls_back_real_job_cleanup(engine,storage_factory,monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from fitcheck_backend.storage.models import AnalysisRecord,Job
    from fitcheck_backend.metrics import analysis_operation
    from fitcheck_backend.operations.retention import cleanup
    with unit_of_work(engine) as s:account=seed_account(s,storage_factory)
    def fail(*args):raise SQLAlchemyError('synthetic archive failure')
    monkeypatch.setattr(analysis_operation,'archive_analysis_operations',fail)
    with pytest.raises(SQLAlchemyError):cleanup(engine,now=END,execute=True)
    with unit_of_work(engine) as s:
        assert s.get(Job,account[2].id) is not None
        assert s.get(AnalysisRecord,account[3].id).job_id==account[2].id
    assert metric(report(engine),'activation',population='account',provenance='backend_server').value==100


def test_proof_cannot_restore_deleted_account_or_erased_visitor(engine,storage_factory):
    from sqlalchemy import select,func
    from fitcheck_backend.storage.analysis_operation import AnalysisOperationProof as Proof
    from fitcheck_backend.operations.retention import cleanup
    from fitcheck_backend.storage.ownership import delete_owner
    from fitcheck_backend.metrics.collector import MetricsCollector
    from fitcheck_backend.config import Settings
    with unit_of_work(engine) as s:account=seed_account(s,storage_factory)
    cleanup(engine,now=END,execute=True)
    settings=Settings(metrics_enabled=True,metrics_environment='test',metrics_ingest_key='test-key')
    MetricsCollector(engine,settings,lambda:END).delete_visitor(account[-1])
    # Domain provenance is not another visitor association; observations are gone.
    assert metric(report(engine),'activation',population='account',provenance='backend_server').numerator==0
    with unit_of_work(engine) as s:
        delete_owner(s,account[0].id,now=END)
        assert s.scalar(select(func.count()).select_from(Proof))==0
    assert cleanup(engine,now=END,execute=True)['jobs']==0


def test_proof_retention_shares_batch_and_does_not_delete_saved_result(engine,storage_factory):
    from sqlalchemy import select,func
    from fitcheck_backend.metrics.retention import cleanup_metrics
    from fitcheck_backend.storage.analysis_operation import AnalysisOperationProof as Proof
    from fitcheck_backend.storage.models import AnalysisRecord
    from fitcheck_backend.operations.retention import cleanup
    with unit_of_work(engine) as s:account=seed_account(s,storage_factory)
    cleanup(engine,now=END,execute=True)
    now=START+timedelta(days=184)
    for _ in range(30):
        result=cleanup_metrics(engine,now=now,dry_run=False,limit=1)
        assert result.processed<=1
        if result.processed==0:break
    with unit_of_work(engine) as s:
        assert s.scalar(select(func.count()).select_from(Proof))==0
        assert s.get(AnalysisRecord,account[3].id) is not None


def test_retained_late_view_keeps_required_operation_proof(engine,storage_factory):
    from sqlalchemy import select,func
    from fitcheck_backend.metrics.retention import cleanup_metrics
    from fitcheck_backend.storage.analysis_operation import AnalysisOperationProof as Proof
    from fitcheck_backend.operations.retention import cleanup
    with unit_of_work(engine) as s:account=seed_account(s,storage_factory)
    cleanup(engine,now=END,execute=True)
    with unit_of_work(engine) as s:
        append_view(s,account[-1],account[3].id,START+timedelta(days=170))
    for _ in range(30):
        result=cleanup_metrics(engine,now=START+timedelta(days=200),dry_run=False,limit=1)
        if result.processed==0:break
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(Proof))==1
    for _ in range(30):
        result=cleanup_metrics(engine,now=START+timedelta(days=351),dry_run=False,limit=1)
        if result.processed==0:break
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(Proof))==0


def test_history_erasure_does_not_rearchive_from_surviving_job(engine,storage_factory):
    from sqlalchemy import select,func,delete
    from fitcheck_backend.storage.models import AnalysisRecord,Job
    from fitcheck_backend.storage.analysis_operation import AnalysisOperationProof as Proof
    from fitcheck_backend.metrics.analysis_operation import archive_analysis_operations
    from fitcheck_backend.operations.retention import cleanup
    with unit_of_work(engine) as s:
        account=seed_account(s,storage_factory)
        archive_analysis_operations(s,[account[2].id],END)
        assert s.get(Proof,account[3].id) is not None
        s.execute(delete(AnalysisRecord).where(AnalysisRecord.id==account[3].id))
        assert s.get(Job,account[2].id) is not None
        archive_analysis_operations(s,[account[2].id],END)
        assert s.scalar(select(func.count()).select_from(Proof))==0
    cleanup(engine,now=END,execute=True)
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(Proof))==0

"""Fixed server_v2 numerators and denominators independent of SQL fixtures."""
from datetime import datetime, UTC, timedelta
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4, UUID
import pytest
from fitcheck_backend.metrics.report_types import Event, Snapshot, AnalysisFact, DemoProof, ReportOptions
from fitcheck_backend.metrics.identity_queries import project_identity
from fitcheck_backend.metrics.calculations import calculate

START=datetime(2026,1,1,tzinfo=UTC)
END=START+timedelta(days=40)


def snapshot():
    return Snapshot(server_backed=True,backend_scope_reason=None,collections={s:START-timedelta(days=40)
        for s in ('website_client','backend_server','website_server','reconstructed_backend')},backfill_complete_through=END)


def options(population='all'):
    return ReportOptions(start=START,end=END,environment='test',population=population)


def event(data,name,person,day=0,*,source='website_client',**props):
    value=Event(event_id=uuid4(),name=name,subject_id=person,subject_kind='visitor' if source=='website_client' else 'account',
        source=source,occurred_at=START+timedelta(days=day),properties=props)
    data.events.append(value);return value


def account(data,*,day=0):
    owner,visitor,result,job=uuid4(),uuid4(),uuid4(),uuid4()
    at=START+timedelta(days=day)
    event(data,'account_registered',owner,day,source='backend_server')
    link=SimpleNamespace(id=uuid4(),kind='registered',visitor_id=visitor,account_owner_id=owner,
        occurred_at=at,request_started_at=at,anonymous_from=START-timedelta(days=1),cookie_issued_at=START-timedelta(days=1),
        expires_at=at+timedelta(days=14),ended_at=at+timedelta(days=14))
    data.identities[visitor]=project_identity([(link,None)])
    data.analyses.append(AnalysisFact(analysis_id=result,owner_id=owner,job_id=job,created_at=at,
        finished_at=at,state='succeeded',account_owned=True,mode='account',predicted_score=80,corrected_score=None,feedback_at=None))
    return owner,visitor,result,job


def row(rows,name,**dims):
    selected=[r for r in rows if r.metric==name and all(r.dimensions.get(k)==v for k,v in dims.items())]
    assert len(selected)==1,(name,dims,len(selected));return selected[0]


def test_exact_seven_day_view_is_outside_activation_and_immature_is_excluded():
    data=snapshot();one=account(data);two=account(data);three=account(data,day=38)
    for value,day in [(one,1),(two,7),(three,39)]:
        event(data,'analysis_result_viewed',value[1],day,flow='account',resultId=str(value[2]))
    rows=calculate(options(),data);value=row(rows,'activation',population='account',provenance='backend_server')
    assert (value.value,value.numerator,value.denominator)==(50,1,2)
    assert value.coverage['immature_registrations']==1
    assert row(rows,'registrations',population='account',provenance='backend_server').value==3


def test_demo_funnel_requires_same_guest_order_and_strict_seven_days():
    data=snapshot();visitors=[uuid4() for _ in range(3)]
    for index,visitor in enumerate(visitors):
        guest=uuid4();event(data,'page_viewed',visitor)
        for name,day in [('vacancy_input_started',.1),('analysis_requested',.2),('analysis_result_viewed',1 if index==0 else .15 if index==1 else 7)]:
            e=event(data,name,visitor,day,flow='demo',**({'resultId':str(uuid4())} if name.endswith('viewed') else {}))
            job=uuid4() if name.endswith('viewed') else None
            if job:
                e=replace(e,operation_id=job);data.events[-1]=e
            data.demo_proofs[e.event_id]=DemoProof(guest_owner_id=guest,job_id=job,
                result_id=UUID(e.properties['resultId']) if job else None)
    rows=calculate(options('visitor'),data)
    value=row(rows,'funnel',funnel='demo',step='analysis_result_viewed')
    assert value.numerator==1 and value.denominator==3 and value.value==pytest.approx(100/3)
    assert row(rows,'activation',population='visitor').numerator==1
    event_id=next(k for k,p in data.demo_proofs.items() if p.result_id is not None)
    data.demo_proofs[event_id]=replace(data.demo_proofs[event_id],guest_owner_id=uuid4())
    assert row(calculate(options('visitor'),data),'funnel',funnel='demo',step='analysis_result_viewed').numerator==0


def test_reconstructed_or_live_completion_is_neither_return_nor_activation():
    data=snapshot();owner,visitor,result,job=account(data)
    event(data,'analysis_result_viewed',visitor,1,flow='account',resultId=str(result))
    for source in ('backend_server','reconstructed_backend'):
        event(data,'job_finished',owner,8,source=source,jobType='analysis',outcome='succeeded')
    retained=row(calculate(options('account'),data),'retention',population='account',provenance='backend_server',day='7')
    assert retained.denominator==1 and retained.numerator==0
    event(data,'profile_revision_saved',owner,8,source='backend_server',revision=1)
    assert row(calculate(options('account'),data),'retention',population='account',provenance='backend_server',day='7').value==100


def test_missing_source_stays_unknown():
    data=snapshot();owner,visitor,result,job=account(data)
    event(data,'analysis_result_viewed',visitor,1,flow='account',resultId=str(result))
    data.collections.pop('website_client')
    value=row(calculate(options('account'),data),'activation',population='account',provenance='backend_server')
    assert not value.available and value.value is None and value.reason


def test_unknown_view_proof_does_not_publish_false_zero():
    data=snapshot();owner,visitor,result,job=account(data)
    event(data,'analysis_result_viewed',visitor,1,flow='account',resultId=str(uuid4()))
    value=row(calculate(options('account'),data),'activation',population='account',provenance='backend_server')
    assert not value.available and value.value is None and value.coverage['unknown_account_views']


def test_late_login_does_not_supply_registration_window_coverage():
    data=snapshot();owner,visitor,result,job=account(data)
    snap=data.identities[visitor];link=snap.transitions[0]
    link.occurred_at=START+timedelta(days=10);link.request_started_at=link.occurred_at
    link.kind='login';data.identities[visitor]=project_identity([(link,None)])
    value=row(calculate(options('account'),data),'activation',population='account',provenance='backend_server')
    assert not value.available and value.denominator==0 and value.coverage['excluded_unlinked_registrations']==1


def test_missing_prediction_makes_correction_distribution_unavailable():
    data=snapshot();account(data)
    data.analyses[0]=replace(data.analyses[0],predicted_score=None,corrected_score=60,feedback_at=START)
    rows=calculate(options('account'),data)
    assert row(rows,'feedback_coverage',population='account').value==100
    assert not row(rows,'score_correction_distribution',bucket='1-10').available
    assert row(rows,'score_correction',population='account',percentile='p50').value is None


def test_guest_usage_without_person_link_is_unavailable_not_zero():
    from fitcheck_backend.metrics.report_types import Operation
    data=snapshot();visitor=uuid4();job=uuid4();result=uuid4()
    viewed=event(data,'analysis_result_viewed',visitor,1,flow='demo',resultId=str(result))
    viewed=replace(viewed,operation_id=job);data.events[-1]=viewed
    data.demo_proofs[viewed.event_id]=DemoProof(guest_owner_id=uuid4(),job_id=job,result_id=result)
    data.operations.append(Operation(operation_id=job,subject_id=None,source='backend_server',kind='analysis',
        created_at=START,finished_at=START+timedelta(hours=1),state='succeeded',provenance='server_guest_domain'))
    value=row(calculate(options('visitor'),data),'usage_intensity',provenance='server_guest_domain')
    assert not value.available and value.value is None
    assert value.denominator==1 and 'link' in value.reason.lower()


def test_retention_exposes_immature_first_view_cohort():
    data=snapshot();owner,visitor,result,job=account(data,day=34)
    event(data,'analysis_result_viewed',visitor,35,flow='account',resultId=str(result))
    value=row(calculate(options('account'),data),'retention',population='account',provenance='backend_server',day='7')
    assert not value.available and value.value is None and value.denominator==0
    assert value.coverage['immature_first_view_cohort']==1

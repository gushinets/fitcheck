from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4, UUID

import pytest

from fitcheck_backend.metrics.report_types import Event, Attempt, Snapshot, ReportOptions
from fitcheck_backend.metrics.calculations import calculate, nearest_rank, ratio

UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=40)


def options(start=START, end=END, zone='Europe/Moscow', population='visitor'):
    return ReportOptions(start=start, end=end, timezone=zone, environment='test', population=population)


def event(name, subject, day=0, *, source='website_client', operation=None, session=None, **props):
    return Event(name=name, subject_id=subject, occurred_at=START+timedelta(days=day), source=source,
                 subject_kind='visitor' if source.startswith('website') else 'account',
                 operation_id=operation, session_id=session, properties=props)


def snapshot(events=(), attempts=(), **kwargs):
    return Snapshot(events=list(events), attempts=list(attempts), collections={
        'website_client': START-timedelta(days=1), 'website_server': START-timedelta(days=1),
        'backend_server': START-timedelta(days=1), 'reconstructed_backend': START-timedelta(days=1)}, **kwargs)


def row(rows, metric, **dimensions):
    found = [r for r in rows if r.metric == metric and all(r.dimensions.get(k) == v for k,v in dimensions.items())]
    assert len(found) == 1, (metric, dimensions, [(r.metric,r.dimensions) for r in found])
    return found[0]


def test_activation_2_of_4_is_50_percent_and_excludes_immature():
    people = [uuid4() for _ in range(5)]
    events = [event('local_registration_completed', p, day) for p,day in zip(people,[0,0,0,0,38])]
    events += [event('analysis_result_viewed',p,1,resultId=str(uuid4())) for p in people[:2]]
    result = row(calculate(options(),snapshot(events)), 'activation')
    assert (result.value,result.numerator,result.denominator) == (50,2,4)
    assert row(calculate(options(),snapshot(events)), 'time_to_value_seconds', percentile='p50').value == 86400


def test_funnel_requires_order_within_7_days():
    good,bad,late = [uuid4() for _ in range(3)]
    events = []
    for person in [good,bad,late]:
        events += [event('page_viewed',person,0),event('local_registration_completed',person,1),
                   event('profile_saved',person,2),event('analysis_requested',person,3)]
    events += [event('analysis_result_viewed',good,4,resultId=str(uuid4())),
               event('analysis_result_viewed',bad,2,resultId=str(uuid4())),
               event('analysis_result_viewed',late,7,resultId=str(uuid4()))]
    result = row(calculate(options(), snapshot(events)), 'funnel', step='analysis_result_viewed')
    assert (result.numerator,result.denominator) == (1,3)
    assert result.value == pytest.approx(100/3)


def test_d7_d30_calendar_offsets_dst_and_complete_windows():
    from zoneinfo import ZoneInfo
    zone = ZoneInfo('America/New_York')
    activation = datetime(2026,3,1,23,30,tzinfo=zone).astimezone(UTC)
    p = uuid4()
    def e(name,when):
        return Event(name=name,subject_id=p,occurred_at=when,source='website_client',subject_kind='visitor',properties={})
    events=[e('local_registration_completed',activation-timedelta(hours=1)),e('analysis_result_viewed',activation), e('history_viewed',datetime(2026,3,8,0,tzinfo=zone).astimezone(UTC)),
            e('history_viewed',datetime(2026,3,31,12,tzinfo=zone).astimezone(UTC))]
    opt=options(start=datetime(2026,3,1,tzinfo=UTC),end=datetime(2026,4,1,4,tzinfo=UTC),zone='America/New_York')
    rows=calculate(opt,snapshot(events))
    assert row(rows,'retention',day='7').value == 100
    assert row(rows,'retention',day='30').value == 100
    incomplete=calculate(options(start=opt.start,end=opt.end-timedelta(seconds=1),zone=opt.timezone),snapshot(events))
    assert row(incomplete,'retention',day='30').denominator == 0


def test_empty_percentiles_and_ratios_are_null():
    assert nearest_rank([],50) is None
    assert nearest_rank([1,2,3,4],50)==2
    assert nearest_rank(list(range(1,21)),95)==19
    assert ratio(0,0) is None
    assert row(calculate(options(),snapshot()),'activation').value is None


def test_useful_actions_exclude_page_view_login_retry():
    a,b,c = [uuid4() for _ in range(3)]
    events=[event('page_viewed',a,39.5), event('local_login_completed',b,39.5),event('analysis_requested',b,39.5),event('profile_saved',c,39.5)]
    rows=calculate(options(),snapshot(events))
    assert row(rows,'active_subjects',window_days='1').value == 1
    assert row(rows,'stickiness').value == 100


def test_30_second_visible_pulses_bound_session_duration():
    p,s=uuid4(),uuid4()
    events=[event('profile_saved',p,1,session=s),event('session_started',p,1,session=s),
            event('visible_activity',p,1.01,session=s,activeMs=90000),event('visible_activity',p,1.02,session=s,activeMs=15000)]
    rows=calculate(options(),snapshot(events))
    assert row(rows,'session_duration_seconds',percentile='p50').value==45
    assert row(rows,'session_frequency').value==1


def test_deleted_and_rotated_subjects_not_linked():
    old,new=uuid4(),uuid4()
    events=[event('local_registration_completed',old),event('analysis_result_viewed',new,1),event('profile_saved',UUID(int=0),39.5)]
    rows=calculate(options(),snapshot(events))
    assert row(rows,'activation').numerator==0
    assert row(rows,'active_subjects',window_days='1').value==0


def test_reconstructed_history_cannot_produce_view_retention():
    p=uuid4()
    events=[event('account_registered',p,source='reconstructed_backend'),
            event('job_finished',p,1,source='reconstructed_backend',outcome='succeeded',jobType='analysis')]
    rows=calculate(options(population='account'),snapshot(events))
    result=row(rows,'retention',day='7',provenance='reconstructed_backend')
    assert result.value is None and not result.available and result.reason


def test_unavailable_financial_survey_and_outcome_metrics_have_reasons():
    rows=calculate(options(),snapshot())
    for name in ['mrr','arr','paid_conversion','subscription_churn','nrr','grr','cac','ltv','margins','sales','nps','csat','ces','outcome_conversion']:
        value=row(rows,name)
        assert not value.available and value.value is None and value.reason


def test_collection_gap_does_not_become_zero_retention_or_activation():
    data=snapshot([event('local_registration_completed',uuid4(),0)])
    data.collections['website_client']=START+timedelta(days=5)
    result=row(calculate(options(),data),'activation')
    assert not result.available and result.reason and result.value is None


def test_options_reject_naive_reversed_long_and_unknown_scope():
    for changes in [{'start':START.replace(tzinfo=None)},{'end':START},{'end':START+timedelta(days=367)}, {'timezone':'bad/zone'},{'population':'people'},{'environment':'anything'}]:
        with pytest.raises(ValueError):
            ReportOptions(**({'start':START,'end':END,'environment':'test','population':'visitor'}|changes))


def test_retention_excludes_unverifiable_first_activation_before_observed_registration():
    p=uuid4()
    rows=calculate(options(),snapshot([event('analysis_result_viewed',p,1),event('history_viewed',p,8)]))
    result=row(rows,'retention',day='7')
    assert result.value is None and result.denominator==0
    assert result.coverage['excluded_uncertain_first_activation']==1


def test_cost_success_uses_created_cohort_and_all_attempts_not_date_spend():
    from fitcheck_backend.metrics.report_types import Operation
    p,old,new=uuid4(),uuid4(),uuid4()
    data=snapshot()
    data.operations=[Operation(operation_id=old,subject_id=p,source='website_server',kind='analysis',created_at=START-timedelta(days=1),finished_at=START+timedelta(days=1),state='succeeded'),
                     Operation(operation_id=new,subject_id=p,source='website_server',kind='analysis',created_at=START+timedelta(days=1),finished_at=START+timedelta(days=2),state='succeeded')]
    for op,cost in [(old,'9'),(new,'2'),(new,'3')]:
        data.attempts.append(Attempt(call_id=uuid4(),operation_id=op,subject_id=p,source='website_server',purpose='analysis.audit',provider='deepseek',model='safe',started_at=START+timedelta(days=1),state='failed',cost=Decimal(cost),currency='USD',cost_basis='estimated'))
    rows=calculate(options(),data)
    assert row(rows,'known_spend',currency='USD').value==14
    value=row(rows,'cost_per_success',operation='analysis',currency='USD')
    assert (value.value,value.numerator,value.denominator)==(5,5,1)
    assert row(rows,'successful_operations',source='website_server',operation='analysis').value==2


def test_queued_operations_unknown_tokens_and_clamped_duration_do_not_fabricate_values():
    p,op=uuid4(),uuid4()
    data=snapshot([event('analysis_finished',p,2,source='website_server',operation=op,outcome='succeeded',durationMs=86400000)])
    data.attempts=[Attempt(call_id=uuid4(),operation_id=op,subject_id=p,source='website_server',purpose='analysis.generate',provider='deepseek',model='safe',started_at=START+timedelta(days=1),state='unknown')]
    rows=calculate(options(),data)
    assert row(rows,'cost_per_success',operation='analysis',currency='unknown').value is None
    assert row(rows,'cost_per_success',operation='analysis',currency='unknown').denominator==0
    assert row(rows,'ai_tokens',token_type='input_tokens').value is None
    assert row(rows,'provider_terminal_coverage',source='website_server').value==0


def test_operation_provenance_never_blends_reconstructed_and_observed_facts():
    p,a,b=uuid4(),uuid4(),uuid4()
    events=[event('job_finished',p,1,source=source,operation=op,jobType='analysis',outcome='succeeded',durationMs=1000)
            for source,op in [('backend_server',a),('reconstructed_backend',b)]]
    rows=calculate(options(population='account'),snapshot(events))
    assert row(rows,'successful_operations',source='backend_server',operation='analysis',provenance='backend_server').value==1
    assert row(rows,'successful_operations',source='backend_server',operation='analysis',provenance='reconstructed_backend').value==1


def test_acquisition_attributes_returning_visitors_to_existing_first_touch():
    p=uuid4()
    events=[event('page_viewed',p,-1,campaign='partner'),event('page_viewed',p,1,campaign='partner'),
            event('local_registration_completed',p,2),event('analysis_result_viewed',p,3)]
    rows=calculate(options(),snapshot(events))
    assert row(rows,'acquisition',campaign='partner',stage='visitors').value==1
    assert row(rows,'acquisition',campaign='partner',stage='registrations').value==1
    assert row(rows,'acquisition',campaign='partner',stage='activations').value==1

"""Versioned product math for the current server-backed website.

Identity and domain joins stay private; only aggregate counts leave this module.
"""
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo
from .calculations import WEEK, ratio, nearest_rank, person
from .identity_queries import account_at

VERSION='server_v2'
FEATURES={'profile_saved':'profile','profile_revision_saved':'profile',
          'analysis_result_viewed':'analysis','skills_accepted':'skills',
          'history_viewed':'history','feedback_saved':'feedback'}


def uuid(value):
    try:return UUID(str(value))
    except (ValueError,TypeError,AttributeError):return None


def add(out,metric,*,coverage=None,**values):
    out.add(metric,coverage={'formula_version':VERSION,**(coverage or {})},**values)


def campaign(event):
    value=event.properties.get('campaign')
    return value if isinstance(value,str) and value else 'unknown'


def anonymous_event(event,link,registration_at):
    if link.anonymous_from is None or event.occurred_at>registration_at:return False
    if event.occurred_at>=link.anonymous_from:return True
    # The first page creates its signed cookie on the server, milliseconds after
    # the browser observed it. Allow only the collector's 5-minute clock bound
    # at an initial cookie floor, never at a logout/switch/erasure boundary.
    return (link.anonymous_from==link.cookie_issued_at and event.received_at is not None
            and link.cookie_issued_at<=event.received_at<=link.occurred_at
            and link.cookie_issued_at-timedelta(minutes=5)<=event.occurred_at)


def first_registration(data):
    result={}
    for event in sorted(data.events,key=lambda e:e.occurred_at):
        if event.name=='account_registered' and event.subject_kind=='account' and person(event.subject_id):
            result.setdefault((event.source,event.subject_id),event.occurred_at)
    return result


def confirmed_activity(data):
    """Domain result, temporal account and observed flow must all agree."""
    facts={f.analysis_id:f for f in data.analyses}
    activity=[];views=[];unknown=defaultdict(int)
    for event in data.events:
        if event.source=='backend_server' and event.subject_kind=='account' and event.name in {'profile_revision_saved','email_verified'}:
            activity.append(event)
        if event.source!='website_client' or event.name not in FEATURES or not person(event.subject_id):continue
        if event.properties.get('flow')=='demo':continue
        snapshot=data.identities.get(event.subject_id)
        owner=account_at(snapshot,event.occurred_at) if snapshot else None
        if owner is None or owner.account_owner_id is None:
            if event.name=='analysis_result_viewed':unknown[owner.reason if owner else 'missing_identity']+=1
            continue
        if event.name in {'analysis_result_viewed','feedback_saved'}:
            fact=facts.get(uuid(event.properties.get('resultId')))
            if (fact is None or not fact.account_owned or fact.owner_id!=owner.account_owner_id or fact.job_id is None
                    or fact.state!='succeeded' or fact.finished_at is None or fact.finished_at>event.occurred_at
                    or fact.created_at>event.occurred_at
                    or event.operation_id is not None and event.operation_id!=fact.job_id):
                if event.name=='analysis_result_viewed':unknown['unverified_result_job']+=1
                continue
            if event.name=='analysis_result_viewed' and event.properties.get('flow')!='account':
                unknown['unknown_result_flow']+=1;continue
        linked=replace(event,subject_id=owner.account_owner_id,subject_kind='account')
        activity.append(linked)
        if event.name=='analysis_result_viewed':views.append(linked)
    return sorted(activity,key=lambda e:e.occurred_at),sorted(views,key=lambda e:e.occurred_at),dict(unknown)


def registration_links(data,registered):
    result=[]
    owners={}
    for (_,p),t in registered.items():owners[p]=min(t,owners.get(p,t))
    for visitor,snapshot in data.identities.items():
        for link in snapshot.transitions:
            at=owners.get(link.account_owner_id)
            if link.kind=='registered' and at is not None and at<=link.occurred_at:
                result.append((visitor,link,at))
    return result


def product_activity(out,events,population,provenance,source,registrations=None,views=()):
    opt=out.options;dims={'population':population,'provenance':provenance}
    selected=[e for e in events if person(e.subject_id) and e.occurred_at<opt.end]
    by_owner=defaultdict(list)
    for e in selected:by_owner[e.subject_id].append(e)
    active={e.subject_id for e in selected if opt.start<=e.occurred_at<opt.end}
    coverage={'activity_basis':'observed_user_actions_only_no_job_completion',
              'cohort_scope':'confirmed_identity' if population=='account' else 'server_proven_demo'}
    rolling={}
    for days in (1,7,30):
        begin=opt.end-timedelta(days=days)
        rolling[days]={e.subject_id for e in selected if begin<=e.occurred_at<opt.end}
        add(out,'active_subjects',dims=dims|{'window_days':str(days)},sources=source,
            required_start=begin,value=len(rolling[days]),coverage=coverage)
    add(out,'stickiness',dims=dims,sources=source,required_start=opt.end-timedelta(days=30),
        value=ratio(len(rolling[1]),len(rolling[30])),numerator=len(rolling[1]),denominator=len(rolling[30]),coverage=coverage)
    for feature in ('profile','analysis','skills','history','feedback'):
        users={e.subject_id for e in selected if opt.start<=e.occurred_at<opt.end and FEATURES.get(e.name)==feature}
        add(out,'feature_adoption',dims=dims|{'feature':feature},sources=source,value=ratio(len(users),len(active)),
            numerator=len(users),denominator=len(active),coverage=coverage)
    zone=ZoneInfo(opt.timezone)
    first={}
    for event in views:
        registered_at=(registrations or {}).get(event.subject_id)
        if registered_at is not None and event.occurred_at>=registered_at:
            first.setdefault(event.subject_id,event.occurred_at)
    for offset in (7,30):
        mature=retained=excluded=immature=0
        for owner,at in first.items():
            if not opt.start<=at<opt.end:continue
            floors=[out.data.collections.get(s) for s in source]
            registered_at=registrations[owner]
            if any(f is None or registered_at<f for f in floors) or (out.data.history_floor and registered_at<out.data.history_floor):
                excluded+=1;continue
            date=at.astimezone(zone).date()
            left=datetime.combine(date+timedelta(days=offset),time.min,zone).astimezone(timezone.utc)
            right=datetime.combine(date+timedelta(days=offset+1),time.min,zone).astimezone(timezone.utc)
            if right<=opt.end:
                mature+=1
                retained+=any(left<=e.occurred_at<right for e in by_owner[owner])
            else:immature+=1
        add(out,'retention',dims=dims|{'day':str(offset)},sources=source,
            reason='No mature observed first-view cohort' if not mature else None,
            value=ratio(retained,mature),numerator=retained,denominator=mature,
            coverage=coverage|{'cohort':'first_verified_view_after_registration','excluded_uncertain_first_view':excluded,'immature_first_view_cohort':immature,
                               'calendar_timezone':opt.timezone})
    return active


def account_metrics(out,registered,activity,views,unknown):
    opt=out.options;data=out.data;active=set()
    intervals=defaultdict(list);views_by_owner=defaultdict(list)
    for snap in data.identities.values():
        for w in snap.windows:
            if w.reason=='confirmed' and w.account_owner_id is not None:intervals[w.account_owner_id].append(w)
    for view in views:views_by_owner[view.subject_id].append(view.occurred_at)
    for provenance in ('backend_server','reconstructed_backend'):
        registrations={p:t for (source,p),t in registered.items() if source==provenance}
        dims={'population':'account','provenance':provenance}
        missing = data.missing_domain_registration_facts if provenance=='backend_server' else 0
        add(out,'registrations',dims=dims,sources=(provenance,),
            reason='Current domain registrations lack committed observation facts' if missing else None,
            value=sum(opt.start<=t<opt.end for t in registrations.values()),
            coverage={'missing_domain_registration_facts':missing,'basis':'distinct_account_registered_owner_facts'})
        mature={p:t for p,t in registrations.items() if opt.start<=t<opt.end and t+WEEK<=opt.end}
        cohort={p:t for p,t in mature.items() if any(w.start<t+WEEK and (w.end is None or w.end>t) for w in intervals[p])}
        activated={p:min(times) for p,t in cohort.items()
                   if (times:=[at for at in views_by_owner[p] if t<=at<t+WEEK])}
        reason=('Incomplete backfill coverage through the requested report end' if provenance=='reconstructed_backend' and
                (data.backfill_complete_through is None or data.backfill_complete_through<opt.end) else data.backend_scope_reason)
        if unknown and not activated:reason=reason or 'Observed result views lack complete identity or domain proof'
        if not cohort:reason=reason or ('No confirmed identity coverage for mature registrations' if mature else 'No mature registration cohort')
        coverage={'activation_basis':'first_verified_result_view_after_registration','window_days':7,
            'cohort_scope':'registrations_with_confirmed_identity_coverage','mature_registrations':len(mature),
            'excluded_unlinked_registrations':len(mature)-len(cohort),
            'immature_registrations':sum(opt.start<=t<opt.end<t+WEEK for t in registrations.values()),
            'unknown_account_views':unknown,'registration_source':provenance,
            'coverage_quality':'limited_verified_subset','rate_interpretation':'observed_confirmed_lower_bound',
            'outcome_sources':['website_client','confirmed_identity','current_domain_result_job'],
            'observation_limit':'Observed verified subset; missing links and delivery are not inferred'}
        sources=(provenance,'website_client')
        add(out,'activation',dims=dims,sources=sources,reason=reason,value=ratio(len(activated),len(cohort)),
            numerator=len(activated),denominator=len(cohort),coverage=coverage)
        for percentile in (50,95):
            durations=[(at-cohort[p]).total_seconds() for p,at in activated.items()]
            add(out,'time_to_value_seconds',dims=dims|{'percentile':f'p{percentile}'},sources=sources,reason=reason,
                value=nearest_rank(durations,percentile),sample_count=len(durations),coverage=coverage)
        for metric,name in [('onboarding','profile_revision_saved'),('email_verification','email_verified')]:
            outcomes=defaultdict(list)
            for e in data.events:
                if e.source in {'backend_server','reconstructed_backend'} and e.name==name and e.subject_id in registrations:
                    outcomes[e.subject_id].append(e)
            outcome_sources={e.source for history in outcomes.values() for e in history}
            required_sources=tuple(sorted({provenance}|outcome_sources))
            # A source can disappear from visible outcomes precisely because it was
            # pruned. Its persisted coverage floor must still invalidate gaps.
            outcome_floor=max((data.retention_floors[s] for s in ('backend_server','reconstructed_backend')
                               if s in data.retention_floors),default=None)
            success=sum(any(t<=e.occurred_at<t+WEEK for e in outcomes[p]) for p,t in mature.items())
            add(out,metric,dims=dims,sources=(provenance,),retention_floor=outcome_floor,
                backfill_required='reconstructed_backend' in required_sources,
                reason='No mature registration cohort' if not mature else None,
                value=ratio(success,len(mature)),numerator=success,denominator=len(mature),
                coverage={'basis':'exact_committed_backend_action_not_return_activity','window_days':7,
                          'registration_source':provenance,'outcome_sources':sorted(outcome_sources)})
        selected=product_activity(out,[e for e in activity if provenance=='backend_server' or e.subject_id in registrations], 'account',provenance,sources,registrations,views)
        if provenance=='backend_server':active=selected
    deletion_count=sum(e.name=='account_deleted' and e.source=='backend_server' and opt.start<=e.occurred_at<opt.end for e in data.events)
    add(out,'account_deletions',dims={'population':'account','provenance':'backend_server'},sources=('backend_server',),value=deletion_count)
    return active


def visitor_metrics(out,registered,links):
    opt=out.options;data=out.data
    events=sorted([e for e in data.events if e.source=='website_client' and person(e.subject_id)],key=lambda e:e.occurred_at)
    pages=defaultdict(list);demo=[];unproven=0
    for event in events:
        if event.name=='page_viewed':pages[event.subject_id].append(event)
        if event.properties.get('flow')!='demo':continue
        proof=data.demo_proofs.get(event.event_id)
        if proof is None:
            unproven+=1;continue
        if event.name=='analysis_result_viewed' and (proof.result_id!=uuid(event.properties.get('resultId')) or proof.job_id!=event.operation_id):
            unproven+=1;continue
        demo.append((event,proof))
    entered={p:min(e.occurred_at for e in history if opt.start<=e.occurred_at<opt.end)
             for p,history in pages.items() if any(opt.start<=e.occurred_at<opt.end for e in history)}
    mature={p:t for p,t in entered.items() if t+WEEK<=opt.end}
    linked_owners={link.account_owner_id for _,link,_ in links}
    registration_sources=tuple(sorted({source for source,owner in registered if owner in linked_owners})) or ('backend_server',)
    dims={'population':'visitor','provenance':'confirmed_demo'}
    coverage={'cohort':'first_observed_entry_in_period','window_days':7,'mature_visitors':len(mature),
        'immature_visitors':len(entered)-len(mature),'unproven_demo_events':unproven,
        'observation_limit':'Server-proven guest subset only; missing proof is unknown',
        'coverage_quality':'limited_verified_subset','rate_interpretation':'observed_confirmed_lower_bound',
        'registration_sources':list(registration_sources)}
    demo_reason='No server-proven demo observation coverage' if not demo else None
    cursors={};first_views={}
    for step in ('page_viewed','vacancy_input_started','analysis_requested','analysis_result_viewed'):
        if step=='page_viewed':count=len(mature)
        else:
            next_cursors={}
            for event,proof in demo:
                visitor=event.subject_id;key=(visitor,proof.guest_owner_id)
                if visitor not in mature or event.name!=step:continue
                previous=mature[visitor] if step=='vacancy_input_started' else cursors.get(key)
                if previous is not None and previous<=event.occurred_at<mature[visitor]+WEEK:
                    next_cursors.setdefault(key,event.occurred_at)
            cursors=next_cursors;count=len({p for p,_ in cursors})
            if step=='analysis_result_viewed':
                for (p,_),at in cursors.items():first_views[p]=min(at,first_views.get(p,at))
        add(out,'funnel',dims=dims|{'funnel':'demo','step':step},sources=('website_client',),
            reason=('No mature visitor cohort' if not mature else demo_reason if step!='page_viewed' else None),
            value=ratio(count,len(mature)),numerator=count,denominator=len(mature),coverage=coverage)
    demo_views=[e for e,p in demo if e.name=='analysis_result_viewed']
    demo_by_visitor=defaultdict(list)
    for e in demo_views:demo_by_visitor[e.subject_id].append(e)
    entry_pages={p:next(e for e in pages[p] if e.occurred_at==at) for p,at in entered.items()}
    converted=set();demo_converted=set();attributed_visitors=set()
    for visitor,link,registration_at in links:
        if opt.start<=registration_at<opt.end:attributed_visitors.add(visitor)
        anchor=mature.get(visitor)
        if anchor is None or not anonymous_event(entry_pages[visitor],link,registration_at) or not anchor<=registration_at<anchor+WEEK:continue
        converted.add(visitor)
        if any(e.subject_id==visitor and anonymous_event(e,link,registration_at) and e.occurred_at<registration_at and anchor<=e.occurred_at<anchor+WEEK for e in demo_by_visitor[visitor]):
            demo_converted.add(visitor)
    add(out,'registrations',dims={'population':'visitor','provenance':'confirmed_identity'},sources=('website_client',)+registration_sources,
        reason='Observed account registrations have no confirmed visitor registration link' if registered and not attributed_visitors else None,
        value=len(attributed_visitors),coverage={'basis':'distinct_visitors_with_registered_link_and_account_fact','not_account_count':True,'registration_sources':list(registration_sources)})
    demo_cohort={p for p in mature if any(e.subject_id==p and mature[p]<=e.occurred_at<mature[p]+WEEK for e in demo_by_visitor[p])}
    for name,numerator,denominator in [('visit_to_registration',len(converted),len(mature)),
                                        ('demo_to_registration',len(demo_converted),len(demo_cohort))]:
        add(out,'funnel',dims={'population':'visitor','provenance':'confirmed_identity','funnel':name,'step':'account_registered'},
            sources=('website_client',)+registration_sources,reason='No mature observed conversion cohort' if not denominator else None,
            value=ratio(numerator,denominator),numerator=numerator,denominator=denominator,
            coverage=coverage|{'registration_basis':'account_registered_and_registered_identity_transition',
                               'denominator_basis':'mature_entry_visitors' if name.startswith('visit') else 'mature_entry_visitors_with_verified_demo_view'})
    add(out,'activation',dims=dims,sources=('website_client',),reason=demo_reason or ('No mature visitor cohort' if not mature else None),
        value=ratio(len(first_views),len(mature)),numerator=len(first_views),denominator=len(mature),
        coverage=coverage|{'activation_basis':'ordered_demo_first_view','distinct_from_account_activation':True})
    for percentile in (50,95):
        durations=[(at-mature[p]).total_seconds() for p,at in first_views.items()]
        add(out,'time_to_value_seconds',dims=dims|{'percentile':f'p{percentile}'},sources=('website_client',),reason=demo_reason,
            value=nearest_rank(durations,percentile),sample_count=len(durations),coverage=coverage|{'anchor':'period_entry'})
    active=product_activity(out,[e for e,p in demo], 'visitor','confirmed_demo',('website_client',),mature,demo_views)
    campaign_visitors=defaultdict(set)
    for visitor,page in entry_pages.items():campaign_visitors[campaign(page)].add(visitor)
    for code,visitors in sorted(campaign_visitors.items()):
        add(out,'acquisition',dims={'population':'visitor','provenance':'website_observed','campaign':code,'stage':'visitors'},
            sources=('website_client',),value=len(visitors),coverage={'attribution':'first_observed_page_in_period'})
    return active


def account_acquisition(out,links,registered,views):
    opt=out.options;pages=defaultdict(list);views_by_owner=defaultdict(list)
    for e in out.data.events:
        if e.source=='website_client' and e.name=='page_viewed':pages[e.subject_id].append(e)
    for e in views:views_by_owner[e.subject_id].append(e)
    touches={}
    for visitor,link,at in links:
        if link.anonymous_from is None:continue
        candidates=[e for e in pages[visitor] if anonymous_event(e,link,at)]
        if candidates:touches.setdefault(link.account_owner_id,campaign(min(candidates,key=lambda e:e.occurred_at)))
    for provenance in ('backend_server','reconstructed_backend'):
        groups=defaultdict(set)
        for (source,owner),at in registered.items():
            if source==provenance and opt.start<=at<opt.end:groups[touches.get(owner,'unknown')].add(owner)
        for code,owners in sorted(groups.items()):
            for stage in ('registrations','activations'):
                count=len(owners) if stage=='registrations' else sum(any(v.subject_id==p and registered[(provenance,p)]<=v.occurred_at<registered[(provenance,p)]+WEEK for v in views_by_owner[p]) for p in owners)
                add(out,'acquisition',dims={'population':'account','provenance':provenance,'campaign':code,'stage':stage},
                    sources=(provenance,'website_client'),value=count,
                    coverage={'attribution':'first_observed_touch_in_confirmed_anonymous_segment','missing_touch':'unknown'})


def feedback_metrics(out):
    opt=out.options;data=out.data;dims={'population':'account','provenance':'current_domain_snapshot'}
    candidates=[f for f in data.analyses if f.account_owned and opt.start<=f.created_at<opt.end]
    cohort=[f for f in candidates if f.job_id is not None and f.state=='succeeded' and f.finished_at is not None and f.finished_at<opt.end]
    corrected=[f for f in cohort if f.corrected_score is not None and f.feedback_at is not None]
    coverage={'basis':'latest_saved_annotation_current_snapshot','snapshot_at':data.snapshot_at,
              'cohort':'current_account_owned_successful_analyses_created_in_period',
              'excluded_unlinked_or_unfinished':len(candidates)-len(cohort),
              'history_limit':'Not state at report end; edits replace and deletion removes saved feedback',
              'meaning':'absolute_score_difference_not_model_accuracy','claim_basis':'current_owner_not_creation_time_account_activity'}
    reason=data.backend_scope_reason or ('No successful linked analysis cohort' if not cohort else None)
    add(out,'feedback_coverage',dims=dims,reason=reason,value=ratio(len(corrected),len(cohort)),
        numerator=len(corrected),denominator=len(cohort),coverage=coverage)
    differences=[abs(f.predicted_score-f.corrected_score) for f in corrected if f.predicted_score is not None]
    for percentile in (50,95):
        add(out,'score_correction',dims=dims|{'percentile':f'p{percentile}'},reason=data.backend_scope_reason or ('No saved correction with valid prediction' if not differences else None),
            value=nearest_rank(differences,percentile),sample_count=len(differences),coverage=coverage)
    for low,high in ((0,0),(1,10),(11,25),(26,50),(51,100)):
        add(out,'score_correction_distribution',dims=dims|{'bucket':f'{low}-{high}'},reason=data.backend_scope_reason or ('No saved correction with valid prediction' if not differences else None),
            value=sum(low<=value<=high for value in differences),sample_count=len(differences),coverage=coverage)
    for status in ('not_applied','applied','replied','interview','rejected','hired'):
        add(out,'current_application_status',dims={'population':'account','status':status,'provenance':'deployment_database_scope'},
            reason=data.backend_scope_reason,value=data.statuses.get(status,0),
            coverage={'basis':'current_snapshot_not_historical_transitions','snapshot_at':data.snapshot_at})


def session_metrics(out):
    """Observed visitor sessions, independent of account/result attribution."""
    opt=out.options
    events=[];seen=set()
    for event in out.data.events:
        if (event.source!='website_client' or event.subject_kind!='visitor' or not person(event.subject_id)
                or not opt.start<=event.occurred_at<opt.end):continue
        if event.event_id is not None:
            if event.event_id in seen:continue
            seen.add(event.event_id)
        events.append(event)
    useful={'profile_saved','analysis_result_viewed','history_viewed','skills_accepted','feedback_saved'}
    active={e.subject_id for e in events if e.name in useful}
    starts=set();durations=defaultdict(int)
    for event in events:
        if event.session_id is None:continue
        key=(event.subject_id,event.session_id)
        if event.name=='session_started' and event.subject_id in active:starts.add(key)
        pulse=event.properties.get('activeMs')
        if event.name=='visible_activity' and type(pulse) is int:
            durations[key]+=max(0,min(30000,pulse))
    dims={'population':'visitor','provenance':'website_observed'}
    coverage={'active_basis':'distinct_visitors_with_observed_useful_client_actions_in_period',
              'useful_actions':sorted(useful),'active_visitors':len(active),
              'observation_limit':'Observed starts/pulses only; missing delivery is not inferred',
              'identity_basis':'signed_visitor_population_not_account_attribution'}
    add(out,'session_frequency',dims=dims,sources=('website_client',),
        reason='No observed active visitor cohort' if not active else None,
        value=len(starts)/len(active) if active else None,numerator=len(starts),denominator=len(active),
        coverage=coverage|{'basis':'observed_session_starts_among_active_visitors'})
    add(out,'session_duration_seconds',dims=dims|{'percentile':'p50'},sources=('website_client',),
        reason='No observed foreground session pulses' if not durations else None,
        value=nearest_rank([duration/1000 for duration in durations.values()],50),sample_count=len(durations),
        coverage=coverage|{'basis':'observed_foreground_pulses_not_wall_clock','pulse_cap_seconds':30,
                           'session_cohort':'sessions_with_valid_foreground_pulses_in_period'})


def calculate_server(out):
    registrations=first_registration(out.data)
    links=registration_links(out.data,registrations)
    activity,views,unknown=confirmed_activity(out.data)
    active={}
    if out.options.population in {'visitor','all'}:
        active['visitor']=visitor_metrics(out,registrations,links)
        session_metrics(out)
        add(out,'feedback_coverage',dims={'population':'visitor','provenance':'current_domain_snapshot'},
            reason='Saved account feedback requires account or all population; client feedback is not current saved state')
    if out.options.population in {'account','all'}:
        active['account']=account_metrics(out,registrations,activity,views,unknown)
        account_acquisition(out,links,registrations,views)
        feedback_metrics(out)
    return active

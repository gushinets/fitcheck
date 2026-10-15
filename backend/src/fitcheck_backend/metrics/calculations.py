"""Pure, identity-free aggregates over independent telemetry projections."""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from math import ceil
from uuid import UUID
from zoneinfo import ZoneInfo

from .report_types import MetricRow, Operation

WEEK = timedelta(days=7)
USEFUL = {'profile_saved', 'profile_revision_saved', 'analysis_result_viewed',
          'history_viewed', 'skills_accepted', 'feedback_saved'}
FEATURES = {'profile_saved': 'profile', 'profile_revision_saved': 'profile',
            'analysis_result_viewed': 'analysis', 'analysis_finished': 'analysis',
            'history_viewed': 'history', 'skills_accepted': 'skills',
            'suggestions_finished': 'skills', 'feedback_saved': 'feedback'}
WEBSITE_LIMIT = 'Observed only; client blockers and failed delivery are not exhaustively measurable'
BACKEND_LIMIT = 'Committed scoped facts; retained history cannot establish activity before collection'
LEGACY_LIMIT = 'Deployment database scope; legacy rows have no per-row historical environment'
WEBSITE_PENDING_REASON = ('Website operation starts and missing terminal facts are not observed; '
                          'pending state and creation-cohort completeness are unavailable')


def ratio(numerator, denominator):
    return numerator / denominator * 100 if denominator else None


def nearest_rank(values, percentile):
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered)*percentile/100)-1)] if ordered else None


def person(subject):
    return subject is not None and subject != UUID(int=0)


def useful(event):
    if not person(event.subject_id):
        return False
    if event.name in USEFUL:
        return True
    return event.properties.get('outcome') == 'succeeded' and (
        event.name in {'analysis_finished', 'suggestions_finished'} or
        event.name == 'job_finished' and event.properties.get('jobType') in {'analysis', 'skill_suggestions'})


def operation_key(event):
    if event.operation_id:
        return event.operation_id
    if event.domain_key and event.domain_key.startswith('job:'):
        try:
            return UUID(event.domain_key.split(':')[1])
        except (ValueError, IndexError):
            pass
    return None


def operations(data):
    """One record per source/operation before relating any physical attempts."""
    result = {}
    for event in sorted(data.events, key=lambda e: e.occurred_at):
        key = operation_key(event)
        if key is None:
            continue
        if event.source == 'website_server':
            kinds = {'analysis_finished': 'analysis', 'suggestions_finished': 'skill_suggestions', 'extraction_finished': 'extraction'}
            if event.name not in kinds:
                continue
            duration = event.properties.get('durationMs')
            # The terminal duration is clamped by the producer at 24h. Its cap
            # cannot identify the operation's actual creation cohort.
            created = event.occurred_at-timedelta(milliseconds=duration) if duration is not None and duration < 86_400_000 else None
            result[(event.source, key)] = Operation(operation_id=key, subject_id=event.subject_id,
                source=event.source, kind=kinds[event.name], created_at=created,
                finished_at=event.occurred_at, state=event.properties.get('outcome', 'unknown'),
                duration_ms=duration, error_code=event.properties.get('errorCode'), provenance='website_server')
        elif event.name.startswith('job_'):
            identity = ('backend_server', key)
            op = result.setdefault(identity, Operation(operation_id=key, subject_id=event.subject_id,
                source='backend_server', kind=event.properties.get('jobType', 'unknown'),
                created_at=None, provenance=event.source))
            if event.name == 'job_admitted':
                op.created_at, op.state = event.occurred_at, 'queued'
            elif event.name == 'job_execution_started':
                op.started_at = op.started_at or event.occurred_at
                op.state = 'running'
                op.executions += 1
            elif event.name == 'job_execution_recovered':
                op.recovered = True
            elif event.name == 'job_finished':
                op.finished_at, op.state = event.occurred_at, event.properties.get('outcome', 'unknown')
                op.duration_ms = event.properties.get('durationMs')
                op.error_code = event.properties.get('errorCode')
    for op in data.operations:
        old = result.get((op.source, op.operation_id))
        if old:
            op.recovered = old.recovered
            if op.state == 'unknown' and old.state in {'queued', 'running'}:
                op.state = old.state
            op.executions = max(op.executions, old.executions)
            # Domain started_at is the most recent claim; first observed claim
            # from the journal is the only support for first queue duration.
            op.started_at = old.started_at
        else:
            op.started_at = None
        result[(op.source, op.operation_id)] = op
    return list(result.values())


class Rows:
    def __init__(self, options, data):
        self.options, self.data, self.rows = options, data, []

    def add(self, metric, *, dims=None, sources=(), required_start=None, reason=None, coverage=None, **values):
        starts = [self.data.collections.get(source) for source in sources]
        start = max(starts) if starts and all(value is not None for value in starts) else None
        required = required_start or self.options.start
        if sources and (start is None or start > required):
            reason = reason or 'Required observation history is unavailable for this source and period'
        if self.data.history_floor and required < self.data.history_floor:
            reason = reason or 'Required history is outside the bounded snapshot'
        dimensions = dict(dims or {})
        dimensions.setdefault('provenance', 'unavailable')
        if start is None and not sources:
            relevant = [t for key, t in self.data.collections.items() if
                        dimensions.get('population') == 'all' or
                        key.startswith('website_') == (dimensions.get('population') == 'visitor')]
            start = min(relevant, default=None)
        details = {'observation_limit': WEBSITE_LIMIT if dimensions.get('population') == 'visitor' or
                   dimensions.get('source') == 'website_server' else BACKEND_LIMIT}
        details.update(coverage or {})
        if reason:
            values['value'] = None
        self.rows.append(MetricRow(metric=metric, dimensions=dimensions, coverage=details,
            available=reason is None, reason=reason, data_start=start, **values))


def population_metrics(out, events, population, provenance):
    opt = out.options
    source = 'website_client' if population == 'visitor' else provenance
    dims = {'population': population, 'provenance': provenance}
    events = sorted([e for e in events if person(e.subject_id)], key=lambda e: e.occurred_at)
    in_period = lambda t: opt.start <= t < opt.end
    registration = 'local_registration_completed' if population == 'visitor' else 'account_registered'
    profile = 'profile_saved' if population == 'visitor' else 'profile_revision_saved'
    by_subject = defaultdict(list)
    for event in events:
        by_subject[event.subject_id].append(event)
    registered = {p: next((e.occurred_at for e in history if e.name == registration), None) for p, history in by_subject.items()}
    registered = {p: t for p, t in registered.items() if t is not None}
    cohort = {p: t for p, t in registered.items() if in_period(t) and t+WEEK <= opt.end}
    out.add('registrations', dims=dims, sources=(source,), value=sum(in_period(t) for t in registered.values()))
    activation = {}
    for p, history in by_subject.items():
        candidates = [e.occurred_at for e in history if (
            e.name == 'analysis_result_viewed' if population == 'visitor' else
            e.name == 'job_finished' and e.properties.get('jobType') == 'analysis' and e.properties.get('outcome') == 'succeeded')]
        if candidates:
            activation[p] = min(candidates)
    activated = {p: activation[p] for p, t in cohort.items() if p in activation and t <= activation[p] < t+WEEK}
    coverage = {'mature_registrations': len(cohort), 'immature_registrations': sum(in_period(t) and t+WEEK > opt.end for t in registered.values()),
                'activation_basis': 'viewed_result' if population == 'visitor' else 'completion_based'}
    out.add('activation', dims=dims, sources=(source,), numerator=len(activated), denominator=len(cohort),
            value=ratio(len(activated), len(cohort)), coverage=coverage)
    durations = [(t-registered[p]).total_seconds() for p, t in activated.items()]
    for percentile in (50, 95):
        out.add('time_to_value_seconds', dims=dims | {'percentile': f'p{percentile}'}, sources=(source,),
                value=nearest_rank(durations, percentile), sample_count=len(durations), coverage=coverage)
    for metric, target in [('onboarding', profile)] + ([('email_verification', 'email_verified')] if population == 'account' else []):
        successes = sum(any(e.name == target and t <= e.occurred_at < t+WEEK for e in by_subject[p]) for p, t in cohort.items())
        out.add(metric, dims=dims, sources=(source,), numerator=successes, denominator=len(cohort), value=ratio(successes, len(cohort)))
    active = {e.subject_id for e in events if useful(e) and in_period(e.occurred_at)}
    rolling = {}
    for days in (1, 7, 30):
        begin = opt.end-timedelta(days=days)
        rolling[days] = {e.subject_id for e in events if useful(e) and begin <= e.occurred_at < opt.end}
        out.add('active_subjects', dims=dims | {'window_days': str(days)}, sources=(source,), required_start=begin, value=len(rolling[days]))
    out.add('stickiness', dims=dims, sources=(source,), required_start=opt.end-timedelta(days=30),
            value=ratio(len(rolling[1]), len(rolling[30])), numerator=len(rolling[1]), denominator=len(rolling[30]))
    zone = ZoneInfo(opt.timezone)
    for offset in (7, 30):
        retained = mature = uncertain_first = 0
        for p, activated_at in activation.items():
            if not in_period(activated_at):
                continue
            collection_start = out.data.collections.get(source)
            registration_at = registered.get(p)
            if (registration_at is None or registration_at > activated_at or collection_start is None
                    or registration_at < collection_start
                    or out.data.history_floor is not None and registration_at < out.data.history_floor):
                uncertain_first += 1
                continue
            date = activated_at.astimezone(zone).date()
            left = datetime.combine(date+timedelta(days=offset), time.min, zone).astimezone(timezone.utc)
            right = datetime.combine(date+timedelta(days=offset+1), time.min, zone).astimezone(timezone.utc)
            if right <= opt.end:
                mature += 1
                retained += any(useful(e) and left <= e.occurred_at < right for e in by_subject[p])
        out.add('retention', dims=dims | {'day': str(offset)}, sources=(source,), value=ratio(retained, mature),
            numerator=retained, denominator=mature,
            reason='Reconstructed history cannot establish viewed or observed return activity' if provenance == 'reconstructed_backend' else None,
            coverage={'cohort': 'first_activation_after_observed_registration', 'excluded_uncertain_first_activation': uncertain_first,
                      'calendar_timezone': opt.timezone})
    for feature in ('profile', 'analysis', 'skills', 'history', 'feedback'):
        users = {e.subject_id for e in events if useful(e) and in_period(e.occurred_at) and
                 (FEATURES.get(e.name) == feature or e.name == 'job_finished' and
                  {'analysis': 'analysis', 'skill_suggestions': 'skills'}.get(e.properties.get('jobType')) == feature)}
        out.add('feature_adoption', dims=dims | {'feature': feature}, sources=(source,), value=ratio(len(users), len(active)),
                numerator=len(users), denominator=len(active))
    if population == 'visitor':
        website_metrics(out, events, by_subject, registered, activation, active, dims)
    else:
        out.add('acquisition', dims=dims, reason='Backend acquisition requires authenticated visitor/account linking')
    return active


def website_metrics(out, events, by_subject, registered, activation, active, dims):
    opt = out.options
    entries = {p: next((e.occurred_at for e in history if e.name == 'page_viewed'), None) for p, history in by_subject.items()}
    entered = {p: t for p, t in entries.items() if t is not None and opt.start <= t < opt.end and t+WEEK <= opt.end}
    cursors = dict(entered)
    for step in ('page_viewed', 'local_registration_completed', 'profile_saved', 'analysis_requested', 'analysis_result_viewed'):
        if step != 'page_viewed':
            cursors = {p: min(times) for p, previous in cursors.items()
                       if (times := [e.occurred_at for e in by_subject[p] if e.name == step and previous <= e.occurred_at < entered[p]+WEEK])}
        out.add('funnel', dims=dims | {'step': step}, sources=('website_client',),
                numerator=len(cursors), denominator=len(entered), value=ratio(len(cursors), len(entered)))
    sessions, durations = set(), defaultdict(int)
    for event in events:
        if not opt.start <= event.occurred_at < opt.end or not event.session_id:
            continue
        key = (event.subject_id, event.session_id)
        if event.name == 'session_started' and event.subject_id in active:
            sessions.add(key)
        if event.name == 'visible_activity':
            durations[key] += max(0, min(30_000, event.properties.get('activeMs', 0)))
    out.add('session_frequency', dims=dims, sources=('website_client',), value=len(sessions)/len(active) if active else None,
            numerator=len(sessions), denominator=len(active), coverage={'basis': 'observed_session_starts_among_active_visitors'})
    out.add('session_duration_seconds', dims=dims | {'percentile': 'p50'}, sources=('website_client',),
            value=nearest_rank([value/1000 for value in durations.values()], 50), sample_count=len(durations),
            coverage={'basis': 'observed_foreground_pulses_not_wall_clock', 'pulse_cap_seconds': 30})
    campaigns = defaultdict(set)
    for p, history in by_subject.items():
        page = next((e for e in history if e.name == 'page_viewed'), None)
        if page:
            campaigns[page.properties.get('campaign') or 'direct'].add(p)
    for campaign, people in sorted(campaigns.items()):
        for stage, selected in [('visitors', {p for p in people if any(e.name == 'page_viewed' and opt.start <= e.occurred_at < opt.end for e in by_subject[p])}), ('registrations', {p for p in people if p in registered and opt.start <= registered[p] < opt.end}),
                                ('activations', {p for p in people if p in activation and opt.start <= activation[p] < opt.end})]:
            out.add('acquisition', dims=dims | {'campaign': campaign, 'stage': stage}, sources=('website_client',),
                    value=len(selected), coverage={'attribution': 'first_observed_touch_in_retained_history'})
    latest = {}
    for event in events:
        if event.name == 'feedback_saved' and opt.start <= event.occurred_at < opt.end:
            latest[(event.subject_id, str(event.properties.get('resultId')))] = event
    differences = [abs(e.properties['predictedScore']-e.properties['correctedScore']) for e in latest.values()
                   if e.properties.get('predictedScore') is not None and e.properties.get('correctedScore') is not None]
    out.add('score_correction', dims=dims | {'percentile': 'p50'}, sources=('website_client',),
            value=nearest_rank(differences, 50), sample_count=len(differences), coverage={'meaning': 'absolute_score_difference_not_model_accuracy', 'samples': 'latest_feedback_per_result'})
    for low, high in ((0, 0), (1, 10), (11, 25), (26, 50), (51, 100)):
        out.add('score_correction_distribution', dims=dims | {'bucket': f'{low}-{high}'}, sources=('website_client',),
                value=sum(low <= v <= high for v in differences), sample_count=len(differences))


def operation_metrics(out, ops, active_by_population):
    opt, data = out.options, out.data
    selected_sources = ['website_server'] if opt.population == 'visitor' else ['backend_server'] if opt.population == 'account' else ['website_server', 'backend_server']
    partitions = [(source, provenance) for source in selected_sources
                  for provenance in sorted({op.provenance or source for op in ops if op.source == source} or {source})]
    for source, provenance in partitions:
        population = 'visitor' if source == 'website_server' else 'account'
        kinds = ('analysis', 'skill_suggestions', 'extraction') if population == 'visitor' else ('analysis', 'skill_suggestions', 'import')
        scoped = [op for op in ops if op.source == source and (op.provenance or source) == provenance]
        for kind in kinds:
            values = [op for op in scoped if op.kind == kind]
            terminal = [op for op in values if op.finished_at and opt.start <= op.finished_at < opt.end and op.state in {'succeeded', 'failed'}]
            successful = [op for op in terminal if op.state == 'succeeded']
            cohort = [op for op in values if op.created_at and opt.start <= op.created_at < opt.end]
            pending = [op for op in cohort if op.state not in {'succeeded', 'failed'}]
            dims = {'population': population, 'source': source, 'operation': kind, 'provenance': provenance}
            sources = (provenance,) if provenance != 'deployment_database_scope' else ()
            reason = None
            if source == 'backend_server' and data.backend_scope_reason and provenance not in data.collections:
                reason = data.backend_scope_reason
            coverage = {'creation_basis': 'terminal_minus_recorded_nonclamped_duration' if source == 'website_server' else 'admission',
                        'legacy_database_limit': LEGACY_LIMIT if not data.backend_scope_reason and source == 'backend_server' else None}
            out.add('successful_operations', dims=dims, sources=sources, reason=reason, value=len(successful), coverage=coverage)
            out.add('operation_success_rate', dims=dims, sources=sources, reason=reason,
                    value=ratio(len(successful), len(terminal)), numerator=len(successful), denominator=len(terminal), coverage=coverage)
            for status in ('queued', 'running', 'unknown'):
                out.add('pending_operations', dims=dims | {'state': status}, sources=sources,
                        reason=WEBSITE_PENDING_REASON if source == 'website_server' else reason,
                        value=sum(op.state == status for op in pending), coverage=coverage)
            for code in sorted({op.error_code or 'unknown' for op in terminal if op.state == 'failed'}):
                out.add('operation_errors', dims=dims | {'error_code': code}, sources=sources, reason=reason,
                        value=sum(op.state == 'failed' and (op.error_code or 'unknown') == code for op in terminal))
            durations = [(op.finished_at-op.created_at).total_seconds()*1000 for op in terminal if op.created_at is not None]
            queue = [(op.started_at-op.created_at).total_seconds()*1000 for op in cohort if op.started_at and op.created_at <= op.started_at]
            execution = [(op.finished_at-op.started_at).total_seconds()*1000 for op in terminal if op.started_at and op.finished_at >= op.started_at]
            for metric, samples in [('end_to_end_latency_ms', durations), ('queue_latency_ms', queue), ('execution_latency_ms', execution)]:
                for percentile in (50, 95):
                    out.add(metric, dims=dims | {'percentile': f'p{percentile}'}, sources=sources, reason=reason,
                            value=nearest_rank(samples, percentile), sample_count=len(samples), coverage=coverage)
            if kind in {'analysis', 'skill_suggestions'}:
                active = active_by_population.get((population, provenance), active_by_population.get(population, set()))
                # Attempts retained after erasure count financially, not as people.
                attributable = [op for op in successful if person(op.subject_id) and op.subject_id in active]
                out.add('usage_intensity', dims=dims, sources=(('backend_server',) if provenance == 'deployment_database_scope' else sources), reason=reason,
                        value=len(attributable)/len(active) if active else None, numerator=len(attributable), denominator=len(active))
            if population == 'account':
                executions = defaultdict(set)
                for attempt in data.attempts:
                    if attempt.source == source and attempt.execution_token and attempt.operation_id:
                        executions[attempt.operation_id].add(attempt.execution_token)
                out.add('jobs_multiple_executions', dims=dims, sources=sources, reason=reason,
                        value=sum(max(op.executions, len(executions[op.operation_id])) > 1 for op in cohort))
                out.add('jobs_recovered', dims=dims, sources=('backend_server',), value=sum(op.recovered for op in cohort))
                out.add('jobs_exhausted', dims=dims, sources=sources, reason=reason,
                        value=sum(op.state == 'failed' and op.executions >= 2 for op in cohort))
    if opt.population in {'visitor', 'all'}:
        cohort = [op for op in ops if op.source == 'website_server' and op.kind == 'analysis' and
                  op.state == 'succeeded' and op.created_at and opt.start <= op.created_at < opt.end and op.created_at+WEEK <= opt.end]
        feedback = defaultdict(list)
        for event in data.events:
            if event.name == 'feedback_saved' and event.source == 'website_client' and person(event.subject_id):
                feedback[(event.subject_id, str(event.properties.get('resultId')))].append(event.occurred_at)
        count = sum(any(op.created_at <= t < op.created_at+WEEK for t in feedback[(op.subject_id, str(op.operation_id))]) for op in cohort)
        out.add('feedback_coverage', dims={'population': 'visitor', 'provenance': 'website_client_and_server'},
            sources=('website_client', 'website_server'), value=ratio(count, len(cohort)), numerator=count, denominator=len(cohort),
            coverage={'linkage': 'server_operation_id_and_same_visitor_only', 'legacy_unlinked_results': 'not_attributable'})


def attempt_metrics(out, ops):
    opt, data = out.options, out.data
    zone = ZoneInfo(opt.timezone)
    selected = ['website_server'] if opt.population == 'visitor' else ['backend_server'] if opt.population == 'account' else ['website_server', 'backend_server']
    for source in selected:
        all_calls = [a for a in data.attempts if a.source == source]
        calls = [a for a in all_calls if opt.start <= a.started_at < opt.end]
        source_operations = [op for op in ops if op.source == source]
        source_operation_ids = {op.operation_id for op in source_operations}
        unlinked_period_calls = sum(a.operation_id is None or a.operation_id not in source_operation_ids for a in calls)
        unresolved_observed_operations = len({a.operation_id for a in calls
            if a.operation_id is not None and a.operation_id not in source_operation_ids})
        dims = {'source': source, 'population': 'visitor' if source == 'website_server' else 'account',
                'provenance': 'website_server' if source == 'website_server' else 'deployment_database_scope'}
        reason = data.backend_scope_reason if source == 'backend_server' else None
        sources = ('website_server',) if source == 'website_server' else ()
        priced = lambda a: a.cost is not None and a.currency is not None and a.cost_basis in {'estimated', 'reported'}
        known = [a for a in calls if priced(a)]
        coverage = {'basis': 'observed_calls_only', 'delivery_loss_rate': 'unknown',
                    'legacy_database_limit': LEGACY_LIMIT if source == 'backend_server' else None}
        out.add('provider_attempts', dims=dims, sources=sources, reason=reason, value=len(calls), coverage=coverage)
        out.add('unpriced_calls', dims=dims, sources=sources, reason=reason, value=len(calls)-len(known), coverage=coverage)
        out.add('cost_coverage', dims=dims, sources=sources, reason=reason, value=ratio(len(known), len(calls)),
                numerator=len(known), denominator=len(calls), coverage=coverage)
        settled = [a for a in calls if a.state in {'succeeded', 'failed'}]
        out.add('provider_terminal_coverage', dims=dims, sources=sources, reason=reason, value=ratio(len(settled), len(calls)),
                numerator=len(settled), denominator=len(calls), coverage=coverage)
        for state in ('started', 'unknown', 'succeeded', 'failed'):
            out.add('provider_attempt_states', dims=dims | {'state': state}, sources=sources, reason=reason,
                    value=sum(a.state == state for a in calls), coverage=coverage)
        latencies = [(a.finished_at-a.started_at).total_seconds()*1000 for a in calls if a.finished_at]
        for percentile in (50, 95):
            out.add('provider_latency_ms', dims=dims | {'percentile': f'p{percentile}'}, sources=sources, reason=reason,
                    value=nearest_rank(latencies, percentile), sample_count=len(latencies))
        for currency in sorted({a.currency for a in known}) or ['unknown']:
            amounts = [a.cost for a in known if a.currency == currency]
            out.add('known_spend', dims=dims | {'currency': currency}, sources=sources, reason=reason,
                    value=sum(amounts, Decimal(0)) if amounts else None, sample_count=len(amounts), coverage=coverage)
        groups = defaultdict(list)
        for call in calls:
            key = (call.started_at.astimezone(zone).date().isoformat(), call.provider, call.model,
                   call.purpose, call.state, call.currency or 'unknown', call.cost_basis)
            groups[key].append(call)
        for key, group in sorted(groups.items()):
            dimensions = dims | dict(zip(('date', 'provider', 'model', 'operation', 'outcome', 'currency', 'cost_basis'), key))
            amounts = [a.cost for a in group if priced(a)]
            out.add('ai_spend', dims=dimensions, sources=sources, reason=reason,
                    value=sum(amounts, Decimal(0)) if amounts else None, sample_count=len(group),
                    coverage=coverage | {'priced_calls': len(amounts), 'observed_calls': len(group)})
            for token in ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_write_tokens', 'reasoning_tokens'):
                samples = [getattr(a, token) for a in group if getattr(a, token) is not None]
                out.add('ai_tokens', dims=dimensions | {'token_type': token}, sources=sources, reason=reason,
                        value=sum(samples) if samples else None, sample_count=len(samples),
                        coverage=coverage | {'known_calls': len(samples), 'observed_calls': len(group)})
        for kind in ('analysis', 'skill_suggestions', 'extraction' if source == 'website_server' else 'import'):
            cohort = [op for op in source_operations if op.kind == kind and op.created_at and opt.start <= op.created_at < opt.end]
            ids = {op.operation_id for op in cohort}
            cohort_calls = [a for a in all_calls if a.operation_id in ids and a.started_at < opt.end]
            successes = sum(op.state == 'succeeded' and op.finished_at is not None and op.finished_at < opt.end for op in cohort)
            pending = sum(op.state not in {'succeeded', 'failed'} for op in cohort)
            linked = {a.operation_id for a in cohort_calls}
            extra = coverage | {'pending_operations': None if source == 'website_server' else pending, 'cohort_operations': len(cohort),
                'operations_with_observed_calls': len(linked), 'unpriced_calls': sum(not priced(a) for a in cohort_calls),
                'unlinked_period_calls': unlinked_period_calls,
                'basis': 'known_spend_for_created_operations_all_observed_attempts_through_end'}
            if source == 'website_server':
                extra.update(cohort_completeness='unavailable', cohort_completeness_reason=WEBSITE_PENDING_REASON,
                    cohort_scope='observed_operations_with_reconstructable_creation_only',
                    unresolved_observed_operations=unresolved_observed_operations,
                    unresolved_operation_scope='all_operation_types_in_source_period_attempts')
            out.add('attempts_per_operation', dims=dims | {'operation': kind}, sources=sources, reason=reason,
                    value=len(cohort_calls)/len(cohort) if cohort else None, numerator=len(cohort_calls), denominator=len(cohort), coverage=extra)
            currencies = sorted({a.currency for a in cohort_calls if priced(a)}) or ['unknown']
            for currency in currencies:
                amounts = [a.cost for a in cohort_calls if priced(a) and a.currency == currency]
                spend = sum(amounts, Decimal(0)) if amounts else None
                out.add('cost_per_success', dims=dims | {'operation': kind, 'currency': currency}, sources=sources, reason=reason,
                        value=spend/successes if spend is not None and successes else None, numerator=spend, denominator=successes, coverage=extra)


def calculate(options, data):
    out = Rows(options, data)
    ops = operations(data)
    active = {}
    if options.population in {'visitor', 'all'}:
        events = [e for e in data.events if e.source in {'website_client', 'website_server'} and e.subject_kind == 'visitor' and e.occurred_at < options.end]
        active['visitor'] = population_metrics(out, events, 'visitor', 'website_observed')
    if options.population in {'account', 'all'}:
        # Reconstructed facts remain a separate cohort; never silently combine
        # their subjects with the independently observed live-account cohort.
        active['account'] = set()
        for provenance in ('backend_server', 'reconstructed_backend'):
            events = [e for e in data.events if e.source == provenance and e.subject_kind == 'account' and e.occurred_at < options.end]
            subjects = population_metrics(out, events, 'account', provenance)
            active[('account', provenance)] = subjects
            if provenance == 'backend_server':
                active['account'] = subjects
        deletions = sum(e.name == 'account_deleted' and e.source == 'backend_server' and
                        options.start <= e.occurred_at < options.end for e in data.events)
        out.add('account_deletions', dims={'population': 'account', 'provenance': 'backend_server'}, sources=('backend_server',), value=deletions)
        for status in ('not_applied', 'applied', 'replied', 'interview', 'rejected', 'hired'):
            out.add('current_application_status', dims={'population': 'account', 'status': status, 'provenance': 'deployment_database_scope'},
                    reason=data.backend_scope_reason, value=data.statuses.get(status, 0),
                    coverage={'basis': 'current_snapshot_not_historical_period', 'observation_limit': LEGACY_LIMIT})
        out.add('feedback_coverage', dims={'population': 'account', 'provenance': 'backend_server'},
                reason='Backend feedback events are unavailable until ANY-650')
        out.add('score_correction', dims={'population': 'account', 'provenance': 'backend_server'},
                reason='Backend scored feedback events are unavailable until ANY-650')
    operation_metrics(out, ops, active)
    attempt_metrics(out, ops)
    missing = {'mrr': 'No subscription or billing ledger', 'arr': 'No subscription or billing ledger',
        'paid_conversion': 'No payment events', 'subscription_churn': 'No subscription lifecycle',
        'nrr': 'No recurring revenue and customer billing cohorts', 'grr': 'No recurring revenue and customer billing cohorts',
        'cac': 'No acquisition expense ledger or paying-customer attribution', 'ltv': 'No realized customer revenue or lifetime history',
        'margins': 'No revenue and complete expense ledger', 'sales': 'No sales pipeline or CRM',
        'nps': 'No NPS survey responses', 'csat': 'No CSAT survey responses; corrected scores are not surveys',
        'ces': 'No CES survey responses', 'outcome_conversion': 'No recorded application-status transitions; ANY-650 is not implemented'}
    if options.population == 'visitor':
        missing['current_application_status'] = 'Website application-status functionality is not implemented'
    for metric, reason in missing.items():
        out.add(metric, dims={'population': options.population}, reason=reason)
    return sorted(out.rows, key=lambda row: (row.metric, sorted(row.dimensions.items())))

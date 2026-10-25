"""Independent projections: never join the one-to-many telemetry ledgers.

The caller owns the read-only repeatable-read transaction. A row ceiling fails
closed instead of silently truncating cohorts or exhausting operator memory.
"""
from datetime import timedelta
import re

from sqlalchemy import select, func, or_
from ..storage.metrics import MetricJournal, MetricCollection, WebsiteProviderAttempt
from ..storage.accounting import ProviderCall
from ..storage.work import Job, AnalysisAnnotation
from ..storage.models import User
from .report_types import Event, Attempt, Operation, Snapshot

MAX_ROWS = 100_000
PROPERTY_KEYS = ('campaign', 'resultId', 'predictedScore', 'correctedScore', 'activeMs',
                 'outcome', 'durationMs', 'errorCode', 'jobType', 'attempts', 'executionToken', 'flow', 'requestId')


def bounded(conn, statement):
    rows = conn.execute(statement.limit(MAX_ROWS+1)).mappings().all()
    if len(rows) > MAX_ROWS:
        raise ValueError('Report exceeds the safe row limit; choose a shorter period')
    return rows


def safe_code(value):
    return value if isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,79}', value) else 'unknown'


def load_snapshot(conn, options, backend_database_environment=None):
    # Retention is 180 days. A bounded additional historical window establishes
    # observed registration/first-activation and rolling activity context.
    floor = options.start-timedelta(days=180)
    scope_reason = ('Backend database environment scope is not configured' if backend_database_environment is None
                    else 'Backend database environment does not match report environment'
                    if backend_database_environment != options.environment else None)
    data = Snapshot(server_backed=True, backend_scope_reason=scope_reason, history_floor=floor)
    for row in conn.execute(select(MetricCollection.source, MetricCollection.available_from,
            MetricCollection.retention_floor, MetricCollection.backfill_complete_through)
            .where(MetricCollection.environment == options.environment)).mappings():
        data.collections[row['source']] = max(row['available_from'], row['retention_floor'] or row['available_from'])
        if row['retention_floor'] is not None:
            data.retention_floors[row['source']] = row['retention_floor']
        if row['source'] == 'reconstructed_backend':
            data.backfill_complete_through = row['backfill_complete_through']
    from ..storage.metric_collection_gap import MetricCollectionGap as Gap
    for row in bounded(conn, select(Gap.source, Gap.started_at, Gap.ended_at).where(
            Gap.environment == options.environment, Gap.started_at < options.end,
            or_(Gap.ended_at.is_(None), Gap.ended_at > floor)).order_by(Gap.started_at, Gap.id)):
        data.collection_interruptions.append(dict(row))
    columns = [getattr(MetricJournal, key) for key in ('event_id', 'received_at', 'name', 'occurred_at', 'source', 'subject_kind',
               'subject_id', 'session_id', 'operation_id', 'domain_key')]
    columns += [MetricJournal.properties[key].label(key) for key in PROPERTY_KEYS]
    statement = select(*columns).where(MetricJournal.environment == options.environment,
        MetricJournal.occurred_at >= floor, MetricJournal.occurred_at < options.end)
    for row in bounded(conn, statement):
        values = dict(row)
        props = {key: values.pop(key) for key in PROPERTY_KEYS}
        data.events.append(Event(**values, properties={key: value for key, value in props.items() if value is not None}))
    if options.population in {'visitor', 'all'}:
        keys = ('call_id', 'operation_id', 'subject_id', 'purpose', 'provider', 'model', 'started_at',
                'finished_at', 'state', 'input_tokens', 'output_tokens', 'cached_input_tokens',
                'cache_write_tokens', 'reasoning_tokens', 'cost', 'currency', 'cost_basis', 'error_code',
                'rate_version', 'cost_reason', 'service_tier', 'processing_region', 'response_model')
        for row in bounded(conn, select(*(getattr(WebsiteProviderAttempt, key) for key in keys)).where(
                WebsiteProviderAttempt.environment == options.environment,
                WebsiteProviderAttempt.started_at >= floor, WebsiteProviderAttempt.started_at < options.end)):
            values = dict(row)
            # A snapshot taken later cannot reveal a terminal state before end.
            if values['finished_at'] is not None and values['finished_at'] >= options.end:
                for key in ('finished_at', 'cost', 'currency', 'input_tokens', 'output_tokens',
                            'cached_input_tokens', 'cache_write_tokens', 'reasoning_tokens', 'error_code',
                            'rate_version', 'cost_reason', 'service_tier', 'processing_region', 'response_model'):
                    values[key] = None
                values.update(state='started', cost_basis='unknown')
            data.attempts.append(Attempt(source='website_server', **values))
    from .server_projection import load_server_projection
    load_server_projection(conn, options, data)
    if scope_reason is not None or options.population == 'visitor':
        return data
    # SDK costs are estimates, even for historical calls with a successful state.
    keys = ('id', 'owner_id', 'operation', 'provider', 'model', 'created_at',
            'finished_at', 'state', 'input_tokens', 'output_tokens', 'cost', 'currency', 'error_code', 'execution_token',
            'cached_input_tokens', 'cache_write_tokens', 'reasoning_tokens', 'cost_basis', 'rate_version',
            'cost_reason', 'service_tier', 'processing_region', 'response_model')
    for row in bounded(conn, select(*(getattr(ProviderCall, key) for key in keys),
            func.coalesce(ProviderCall.operation_id, ProviderCall.job_id).label('operation_id')).where(
            ProviderCall.created_at >= floor, ProviderCall.created_at < options.end)):
        values = dict(row)
        for old, new in [('id','call_id'), ('owner_id','subject_id'),
                         ('operation','purpose'), ('created_at','started_at')]:
            values[new] = values.pop(old)
        if values['finished_at'] is not None and values['finished_at'] >= options.end:
            for key in ('finished_at', 'cost', 'currency', 'input_tokens', 'output_tokens', 'error_code',
                        'cached_input_tokens', 'cache_write_tokens', 'reasoning_tokens', 'rate_version',
                        'cost_reason', 'service_tier', 'processing_region', 'response_model'):
                values[key] = None
            values.update(state='started', cost_basis='unknown')
        values['error_code'] = safe_code(values['error_code']) if values['error_code'] else None
        if values['cost_basis'] is None:
            values['cost_basis'] = 'estimated' if values['cost'] is not None else 'unknown'
        data.attempts.append(Attempt(source='backend_server', **values))
    # User is one-to-one with owner. Guest jobs never become registered people.
    statement = select(Job.id, Job.owner_id, Job.type, Job.created_at, Job.started_at,
        Job.finished_at, Job.status, Job.available_at, Job.attempts, Job.error['code'].as_string().label('error_code'))\
        .join(User, User.owner_id == Job.owner_id).where(Job.created_at >= floor, Job.created_at < options.end,
            Job.input['mode'].as_string().is_distinct_from('guest'))
    for row in bounded(conn, statement):
        finished = row['finished_at'] if row['finished_at'] is not None and row['finished_at'] < options.end else None
        started = row['started_at'] if row['started_at'] is not None and row['started_at'] < options.end else None
        data.operations.append(Operation(operation_id=row['id'], subject_id=row['owner_id'], source='backend_server',
            kind=row['type'], created_at=row['created_at'], started_at=started, finished_at=finished,
            state=backend_job_state(row, options.end),
            error_code=safe_code(row['error_code']) if finished and row['error_code'] else None,
            executions=row['attempts'] if finished else 0, provenance='deployment_database_scope'))
    # These are current statuses, not historical transitions or cohort outcomes.
    data.statuses = dict(conn.execute(select(AnalysisAnnotation.application_status, func.count())
        .join(User, User.owner_id == AnalysisAnnotation.owner_id)
        .group_by(AnalysisAnnotation.application_status)).all())
    return data


def backend_job_state(row, end):
    """Latest domain timestamps prove only states with a known surviving boundary."""
    if row['finished_at'] is not None:
        return row['status'] if row['finished_at'] < end else 'unknown'
    if row['status'] == 'queued' and (row['attempts'] == 0 or row['available_at'] < end):
        return 'queued'
    if row['status'] == 'running' and row['started_at'] is not None and row['started_at'] < end:
        return 'running'
    return 'unknown'

from collections import Counter
import hmac
import math
import threading
from pathlib import Path
from sqlalchemy import text
from fastapi import APIRouter, Request
from fastapi.responses import Response


class Counters:
    def __init__(self):
        self._lock = threading.Lock()
        self.requests = Counter()
        self.denials = Counter()
        self.collector_requests = Counter()
        self.seconds = 0.0

    def observe(self, method, status, seconds, code=None, route=None):
        if method not in {'GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'}: method = 'OTHER'
        with self._lock:
            self.requests[method, str(status)] += 1
            self.seconds += seconds
            operation = {'/internal/metrics/events':'events', '/internal/metrics/attempts':'attempts',
                         '/internal/metrics/visitors/{visitorId}':'delete'}.get(route)
            if operation:
                self.collector_requests[operation, str(status)] += 1
            if code in {'quota_exceeded', 'budget_exceeded', 'rate_limited'}: self.denials[code] += 1

    def render(self):
        with self._lock:
            lines = ['# TYPE fitcheck_http_requests_total counter']
            lines += [f'fitcheck_http_requests_total{{method="{method}",status="{status}"}} {count}' for (method, status), count in sorted(self.requests.items())]
            lines += ['# TYPE fitcheck_http_duration_seconds_sum counter', f'fitcheck_http_duration_seconds_sum {self.seconds}']
            lines += ['# TYPE fitcheck_admission_denials_total counter']
            lines += [f'fitcheck_admission_denials_total{{reason="{code}"}} {self.denials[code]}' for code in ('quota_exceeded', 'budget_exceeded', 'rate_limited')]
            lines += ['# TYPE fitcheck_metrics_collector_requests_total counter']
            lines += [f'fitcheck_metrics_collector_requests_total{{operation="{operation}",status="{status}"}} {count}'
                      for (operation, status), count in sorted(self.collector_requests.items())]
            return '\n'.join(lines) + '\n'


def collection_configuration(settings):
    values = {
        'enabled': settings.metrics_enabled,
        'collector_configured': settings.metrics_configured,
        'lifecycle_configured': bool(settings.metrics_enabled and settings.database_url and settings.metrics_environment),
        'database_scope_configured': settings.metrics_database_environment is not None,
    }
    return ''.join(f'# TYPE fitcheck_metrics_{name} gauge\nfitcheck_metrics_{name} {int(value)}\n' for name, value in values.items())


def database_metrics(engine, *, metrics_environment=None):
    lines = ['# TYPE fitcheck_database_up gauge', 'fitcheck_database_up 1']
    with engine.connect() as conn, conn.begin():
        conn.execute(text('SET TRANSACTION READ ONLY'))
        conn.execute(text("SET LOCAL statement_timeout='3s'"))
        conn.execute(text("SET LOCAL lock_timeout='500ms'"))
        if metrics_environment in {'development', 'production', 'test'}:
            journal = conn.execute(text("""SELECT source, count(*) AS count,
                extract(epoch FROM max(received_at)) AS latest
                FROM metric_journal WHERE environment=:environment GROUP BY source"""),
                {'environment': metrics_environment}).mappings().all()
            by_source = {row['source']:row for row in journal}
            lines += ['# TYPE fitcheck_metrics_journal_events gauge',
                      '# TYPE fitcheck_metrics_journal_observed gauge',
                      '# TYPE fitcheck_metrics_journal_latest_received_timestamp_seconds gauge']
            for source in ('website_client', 'website_server', 'backend_server', 'reconstructed_backend'):
                row = by_source.get(source)
                labels = f'source="{source}",environment="{metrics_environment}"'
                lines.append(f'fitcheck_metrics_journal_observed{{{labels}}} {int(row is not None)}')
                lines.append(f'fitcheck_metrics_journal_events{{{labels}}} {row["count"] if row else 0}')
                if row:
                    lines.append(f'fitcheck_metrics_journal_latest_received_timestamp_seconds{{{labels}}} {float(row["latest"])}')
        jobs = conn.execute(text("""SELECT type, status, count(*) AS count,
            coalesce(max(extract(epoch FROM now()-created_at)) FILTER (WHERE status='queued' AND available_at<=now()),0) AS lag
            FROM jobs WHERE status IN ('queued','running') GROUP BY type,status""")).mappings().all()
        values = {(row['type'], row['status']): row for row in jobs}
        lines += ['# TYPE fitcheck_jobs gauge', '# TYPE fitcheck_queue_lag_seconds gauge']
        for kind in ('analysis', 'skill_suggestions', 'import'):
            for status in ('queued', 'running'):
                lines.append(f'fitcheck_jobs{{type="{kind}",status="{status}"}} {values.get((kind,status),{}).get("count",0)}')
            lines.append(f'fitcheck_queue_lag_seconds{{type="{kind}"}} {max(0,float(values.get((kind,"queued"),{}).get("lag",0)))}')
        gauges = conn.execute(text("""SELECT
            (SELECT count(*) FROM jobs WHERE status='failed' AND finished_at>=now()-interval '1 hour') AS failed,
            (SELECT count(*) FROM jobs WHERE status='running' AND lease_expires_at<now()) AS expired,
            coalesce(percentile_cont(.95) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE latency_ms IS NOT NULL),0)/1000.0 AS latency,
            coalesce(sum(cost) FILTER (WHERE currency='USD'),0) AS cost,
            count(*) FILTER (WHERE cost IS NULL) AS unknown
            FROM provider_calls WHERE created_at>=date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'""")).mappings().one()
        for name, field in [('failed_jobs_last_hour','failed'), ('expired_job_leases','expired'), ('provider_latency_p95_seconds_today','latency'), ('provider_cost_usd_today','cost'), ('provider_unknown_cost_calls_today','unknown')]:
            number = float(gauges[field])
            if not math.isfinite(number): raise ValueError('Invalid operational metric')
            lines += [f'# TYPE fitcheck_{name} gauge', f'fitcheck_{name} {max(0,number)}']
    return '\n'.join(lines) + '\n'


router = APIRouter()


@router.get('/internal/operations/metrics', include_in_schema=False)
def metrics(request: Request):
    settings = request.app.state.settings
    token = settings.ops_token.get_secret_value() if settings.ops_token else None
    proof = request.headers.get('authorization', '')
    if not token or not hmac.compare_digest(proof.encode('utf-8'), ('Bearer '+token).encode('utf-8')):
        return Response(status_code=404, headers={'Cache-Control':'no-store'})
    runtime = request.app.state.auth_runtime
    diagnostics = request.app.state.ops_counters.render() + collection_configuration(settings)
    try:
        collector = request.app.state.metrics_collector
        engine = runtime.engine if runtime is not None else getattr(collector, 'engine', None)
        if engine is None: raise ValueError('Unavailable')
        output = diagnostics + database_metrics(engine, metrics_environment=settings.metrics_environment)
        for kind in ('backup','restore'):
            try:
                value = float((Path(settings.ops_state_dir)/f'{kind}.timestamp').read_text(encoding='utf-8'))
                if not math.isfinite(value) or value<0: value=0
            except (OSError,ValueError): value=0
            output += f'# TYPE fitcheck_last_{kind}_success_timestamp_seconds gauge\nfitcheck_last_{kind}_success_timestamp_seconds {value}\n'
        return Response(output, media_type='text/plain; version=0.0.4', headers={'Cache-Control':'no-store'})
    except Exception:
        return Response(diagnostics + 'fitcheck_database_up 0\n', status_code=200, media_type='text/plain', headers={'Cache-Control':'no-store'})

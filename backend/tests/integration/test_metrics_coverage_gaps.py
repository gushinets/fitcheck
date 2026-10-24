"""F01: a real disabled runtime must not turn missing observations into zero."""
from datetime import timedelta
from uuid import uuid4
import csv
import io
import json

import pytest
from sqlalchemy import select, func
from fitcheck_backend.api.runtime import AuthRuntime
from fitcheck_backend.config import Settings
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Owner, User
from fitcheck_backend.storage.metrics import MetricJournal
from fitcheck_backend.metrics.contracts import MetricEvent
from fitcheck_backend.metrics.repository import MetricRepository
from fitcheck_backend.metrics.report import MetricReportService
from fitcheck_backend.metrics.report_types import ReportOptions
from fitcheck_backend.metrics.csv_export import write_csv

pytestmark = pytest.mark.integration


def setup_coverage(engine):
    now = utcnow()
    with unit_of_work(engine) as s:
        owner = Owner(kind='user'); s.add(owner); s.flush()
        old = now - timedelta(days=2)
        s.add(User(owner_id=owner.id, normalized_email=f'{uuid4()}@example.com', password_hash='synthetic', created_at=old))
        s.flush()
        MetricRepository(s).append(MetricEvent(eventId=uuid4(), name='account_registered',
            subjectKind='account', subjectId=owner.id, occurredAt=old, properties={}),
            source='backend_server', environment='test', received_at=old)
    return now


def runtime(engine, mailer, enabled, clock):
    settings = Settings(database_url=engine.url.render_as_string(hide_password=False), auth_enabled=True, auth_secret='78'*32, auth_web_base_url='https://web.example.com',
        metrics_enabled=enabled, metrics_environment='test', metrics_database_environment='test')
    return AuthRuntime(settings, engine=engine, mailer=mailer, clock=clock)


def registration_row(engine, start, end, environment='test'):
    report = MetricReportService(engine, backend_database_environment='test', clock=lambda: end).build(
        ReportOptions(start=start, end=end, environment=environment, population='account', timezone='Asia/Novosibirsk'))
    row = next(r for r in report.rows if r.metric == 'registrations' and r.dimensions['provenance'] == 'backend_server')
    return report, row


def test_disabled_auth_runtime_registration_is_not_a_covered_zero(engine, auth_components):
    now = setup_coverage(engine)
    disabled = runtime(engine, auth_components.mailer, False, lambda: now)
    disabled.auth.register('gap@example.com', 'correct horse battery', '127.0.0.1')
    end = utcnow() + timedelta(seconds=1)
    start = now - timedelta(days=1)
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(User).where(User.created_at >= start, User.created_at < end)) == 1
        assert c.scalar(select(func.count()).select_from(MetricJournal).where(MetricJournal.name == 'account_registered',
            MetricJournal.occurred_at >= start, MetricJournal.occurred_at < end)) == 0
    report, row = registration_row(engine, start, end)
    assert not row.available, row
    assert row.value is None
    assert 'interrupt' in row.reason.lower()
    assert row.coverage['collection_interruptions']
    stream = io.StringIO(); write_csv(report, stream)
    exported = next(r for r in csv.DictReader(io.StringIO(stream.getvalue())) if r['metric'] == 'registrations'
        and json.loads(r['dimensions'])['provenance'] == 'backend_server')
    assert exported['available'] == 'False'
    assert exported['value'] == ''
    assert exported['reason'] == row.reason
    assert json.loads(exported['coverage']) == report.to_json()['rows'][report.rows.index(row)]['coverage']
    disabled.close()


def test_closed_gap_stays_historical_but_covered_zero_recovers(engine, auth_components):
    now = setup_coverage(engine)
    clock = [now]
    disabled = runtime(engine, auth_components.mailer, False, lambda: clock[0])
    # Even without business actions an explicitly disabled interval is not covered.
    _, during = registration_row(engine, now, now + timedelta(hours=1))
    assert not during.available
    _, before = registration_row(engine, now - timedelta(hours=2), now - timedelta(hours=1))
    assert before.available and before.value == 0
    clock[0] = now + timedelta(hours=2)
    disabled.close()
    enabled = runtime(engine, auth_components.mailer, True, lambda: clock[0])
    # A new event cannot retroactively erase the old gap.
    with unit_of_work(engine) as s:
        user = s.scalar(select(User))
        MetricRepository(s).append(MetricEvent(eventId=uuid4(), name='profile_revision_saved', subjectKind='account',
            subjectId=user.owner_id, occurredAt=now + timedelta(hours=3), properties={'revision':1}),
            source='backend_server', environment='test', received_at=now + timedelta(hours=3))
    _, spanning = registration_row(engine, now - timedelta(hours=1), now + timedelta(hours=4))
    assert not spanning.available and spanning.value is None
    _, after = registration_row(engine, now + timedelta(hours=2), now + timedelta(hours=4))
    assert after.available and after.value == 0
    enabled.close()


def test_enabled_runtime_cannot_close_another_disabled_writer(engine, auth_components):
    now = setup_coverage(engine)
    clock = [now]
    one = runtime(engine, auth_components.mailer, False, lambda: clock[0])
    two = runtime(engine, auth_components.mailer, False, lambda: clock[0])
    clock[0] = now + timedelta(hours=1)
    one.close()
    enabled = runtime(engine, auth_components.mailer, True, lambda: clock[0])
    _, row = registration_row(engine, clock[0], now + timedelta(hours=2))
    assert not row.available
    assert any(g['ended_at'] is None for g in row.coverage['collection_interruptions'])
    # Leaving two open represents a crashed/abandoned process, never auto-healed.
    enabled.close()
    _, row = registration_row(engine, now + timedelta(hours=2), now + timedelta(hours=3))
    assert not row.available
    clock[0] = now + timedelta(hours=4)
    two.close()


def test_gap_is_scoped_by_source_environment_and_required_window(engine, auth_components):
    from fitcheck_backend.storage.metric_collection_gap import MetricCollectionGap
    now = setup_coverage(engine)
    with unit_of_work(engine) as s:
        s.add(MetricCollectionGap(id=uuid4(), source='backend_server', environment='production', started_at=now))
        s.add(MetricCollectionGap(id=uuid4(), source='website_client', environment='test', started_at=now))
    _, row = registration_row(engine, now, now + timedelta(hours=1))
    assert row.available and row.value == 0
    assert 'collection_interruptions' not in row.coverage


def test_marker_storage_failure_does_not_block_business_or_produce_false_zero(engine, auth_components, monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy.exc import OperationalError
    import fitcheck_backend.metrics.coverage as coverage
    now = setup_coverage(engine)
    @contextmanager
    def unavailable(*args, **kwargs):
        raise OperationalError('private SQL', {}, Exception('private detail'))
        yield
    monkeypatch.setattr(coverage, 'unit_of_work', unavailable)
    disabled = runtime(engine, auth_components.mailer, False, lambda: now)
    disabled.auth.register('marker-failure@example.com', 'correct horse battery', '127.0.0.1')
    end = utcnow() + timedelta(seconds=1)
    _, row = registration_row(engine, now - timedelta(days=1), end)
    assert not row.available
    assert row.value is None
    assert row.coverage['missing_domain_registration_facts'] == 1
    disabled.close()


def test_closed_gaps_expire_in_shared_maintenance_budget(engine):
    from fitcheck_backend.storage.metric_collection_gap import MetricCollectionGap as Gap
    from fitcheck_backend.metrics.retention import cleanup_metrics
    now = utcnow()
    with unit_of_work(engine) as s:
        for days in (181, 182):
            s.add(Gap(id=uuid4(), source='backend_server', environment='test',
                started_at=now-timedelta(days=days+1), ended_at=now-timedelta(days=days)))
        s.add(Gap(id=uuid4(), source='backend_server', environment='test', started_at=now-timedelta(days=190)))
        s.add(Gap(id=uuid4(), source='backend_server', environment='test',
            started_at=now-timedelta(days=181), ended_at=now-timedelta(days=180)))
    dry = cleanup_metrics(engine, now=now, dry_run=True, limit=1)
    assert dry.processed == 1
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(Gap)) == 4
    for _ in range(2):
        result = cleanup_metrics(engine, now=now, dry_run=False, limit=1)
        assert result.processed == 1
        assert result.collection_gaps_deleted == 1
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(Gap)) == 2
        assert c.scalar(select(func.count()).select_from(Gap).where(Gap.ended_at.is_(None))) == 1


def test_current_cli_json_csv_agree_on_interruption(engine, auth_components, monkeypatch, tmp_path):
    from fitcheck_backend.metrics.__main__ import main
    now = setup_coverage(engine)
    disabled = runtime(engine, auth_components.mailer, False, lambda: now)
    end = utcnow()
    monkeypatch.setenv('FITCHECK_DATABASE_URL', engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv('FITCHECK_METRICS_DATABASE_ENVIRONMENT', 'test')
    args = ['report', '--start', (now-timedelta(days=1)).isoformat(), '--end', end.isoformat(),
        '--environment','test','--population','account']
    for fmt in ('json','csv'):
        assert main(args + ['--format',fmt,'--output',str(tmp_path / ('report.'+fmt))]) == 0
    j = next(r for r in json.loads((tmp_path/'report.json').read_text())['rows']
        if r['metric']=='registrations' and r['dimensions']['provenance']=='backend_server')
    c = next(r for r in csv.DictReader(io.StringIO((tmp_path/'report.csv').read_text()))
        if r['metric']=='registrations' and json.loads(r['dimensions'])['provenance']=='backend_server')
    assert j['available'] is False and c['available']=='False'
    assert j['value'] is None and c['value']==''
    assert j['reason']==c['reason']
    assert j['coverage']==json.loads(c['coverage'])
    disabled.close()


def test_worker_disabled_collection_records_its_own_interval(engine, monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace
    import fitcheck_backend.worker.runtime as module
    from fitcheck_backend.worker.settings import WorkerSettings
    from fitcheck_backend.storage.metric_collection_gap import MetricCollectionGap as Gap
    now = setup_coverage(engine)
    async def close():
        pass
    monkeypatch.setattr(module, 'LlmRuntime', lambda *args: SimpleNamespace(aclose=close))
    settings = Settings(database_url=engine.url.render_as_string(hide_password=False), open_ai_key='synthetic',
        metrics_enabled=False, metrics_environment='test', metrics_database_environment='test')
    worker = module.WorkerRuntime(settings, WorkerSettings(health_path=str(tmp_path/'worker-health.json')))
    async def run():
        await worker.start()
        try:
            _, row = registration_row(engine, now, utcnow())
            assert not row.available
            with engine.connect() as c:
                assert c.scalar(select(func.count()).select_from(Gap).where(Gap.ended_at.is_(None)))==1
        finally:
            await worker.aclose()
    asyncio.run(run())
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(Gap).where(Gap.ended_at.is_not(None)))==1


def test_expiring_gap_cannot_relabel_old_history_as_complete(engine):
    from fitcheck_backend.storage.metrics import MetricCollection
    from fitcheck_backend.storage.metric_collection_gap import MetricCollectionGap as Gap
    from fitcheck_backend.metrics.retention import cleanup_metrics
    now = utcnow()
    old = now - timedelta(days=200)
    with unit_of_work(engine) as s:
        s.add(MetricCollection(source='backend_server', environment='test', started_at=old, available_from=old))
        s.add(Gap(id=uuid4(), source='backend_server', environment='test',
            started_at=old+timedelta(days=1), ended_at=old+timedelta(days=2)))
    cleanup_metrics(engine, now=now, dry_run=False, limit=1)
    _, row = registration_row(engine, old+timedelta(days=1), old+timedelta(days=3))
    assert not row.available
    assert row.value is None


def test_enabled_flag_without_emission_environment_still_marks_gap(engine, auth_components):
    now = setup_coverage(engine)
    settings = Settings(database_url=engine.url.render_as_string(hide_password=False),
        auth_enabled=True, auth_secret='78'*32, auth_web_base_url='https://web.example.com',
        metrics_enabled=True, metrics_environment=None, metrics_database_environment='test')
    clock = [now]
    disabled = AuthRuntime(settings, engine=engine, mailer=auth_components.mailer, clock=lambda: clock[0])
    try:
        _, row = registration_row(engine, now, now+timedelta(hours=1))
        assert not row.available
        assert row.value is None
        assert row.coverage['collection_interruptions'][0]['source'] == 'backend_server'
    finally:
        clock[0] = now+timedelta(hours=2)
        disabled.close()

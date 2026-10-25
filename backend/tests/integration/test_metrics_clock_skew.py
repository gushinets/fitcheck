"""ANY-748: real collector → PostgreSQL → server report, synthetic owners only."""
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select, update
from fitcheck_backend.config import Settings
from fitcheck_backend.metrics.collector import MetricsCollector
from fitcheck_backend.metrics.contracts import MetricEvent, WebsiteBatch
from fitcheck_backend.metrics.repository import MetricRepository
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.metrics import MetricJournal, MetricCollection
from fitcheck_backend.storage.metric_identity import MetricIdentityTransition as Link
from test_metrics_server_report import START, END, seed_account, report, metric

pytestmark = pytest.mark.integration
RECEIVED = START + timedelta(hours=1, seconds=2)


def seed(engine, factory):
    with unit_of_work(engine) as session:
        value = seed_account(session, factory, view=False)
        MetricRepository(session).append(MetricEvent(eventId=uuid4(), name='page_viewed',
            subjectId=value[-1], occurredAt=START, properties={'campaign': 'direct'}),
            source='website_client', environment='test', received_at=START)
        # Both sources have explicit full coverage before the report start.
        session.execute(update(MetricCollection).values(available_from=START-timedelta(days=2)))
    return value


def ingest(engine, value, offset=0, *, received=RECEIVED, result=None):
    event = MetricEvent(eventId=uuid4(), name='analysis_result_viewed', subjectId=value[-1],
        occurredAt=RECEIVED+timedelta(seconds=offset), operationId=value[2].id,
        properties={'flow': 'account', 'resultId': str(result or value[3].id)})
    collector = MetricsCollector(engine, Settings(metrics_enabled=True,
        metrics_environment='test', metrics_ingest_key='synthetic-test-key'), lambda: received)
    batch = WebsiteBatch(source='website_client', events=[event])
    assert collector.ingest(batch).accepted == 1
    assert collector.ingest(batch).duplicates == 1
    return event


@pytest.mark.parametrize('offset', [0, -60, 60, -300, 300])
def test_bounded_skew_preserves_confirmed_view_and_server_time_upper_bound(engine, storage_factory, offset):
    value = seed(engine, storage_factory)
    event = ingest(engine, value, offset)
    result = report(engine, 'account')
    activation = metric(result, 'activation', population='account', provenance='backend_server')
    assert activation.available and (activation.value, activation.numerator, activation.denominator) == (100, 1, 1)
    ttv = metric(result, 'time_to_value_seconds', population='account', provenance='backend_server', percentile='p50')
    assert ttv.available and ttv.value == 3602
    assert activation.coverage['observation_time_basis'] == 'server_receipt_upper_bound'
    assert activation.coverage['client_clock_tolerance_seconds'] == 300
    with unit_of_work(engine) as session:
        stored = session.get(MetricJournal, event.event_id)
        assert stored.submitted_occurred_at == event.occurred_at
        assert stored.received_at == RECEIVED
        assert not stored.clock_adjusted
        # Retention uses the same confirmed first view, not a job completion.
        MetricRepository(session).append(MetricEvent(eventId=uuid4(), name='profile_revision_saved',
            subjectKind='account', subjectId=value[0].id, occurredAt=START+timedelta(days=7),
            properties={'revision': 2}), source='backend_server', environment='test', received_at=START+timedelta(days=7))
    retained = metric(report(engine, 'account'), 'retention', population='account', provenance='backend_server', day='7')
    assert retained.available and (retained.value, retained.numerator, retained.denominator) == (100, 1, 1)


@pytest.mark.parametrize('offset', [-301, 301, -3600, 3600])
def test_excessive_skew_preserves_raw_time_but_does_not_invent_attribution(engine, storage_factory, offset):
    value = seed(engine, storage_factory)
    event = ingest(engine, value, offset)
    activation = metric(report(engine, 'account'), 'activation', population='account', provenance='backend_server')
    assert not activation.available and activation.value is None
    assert activation.coverage['unknown_account_views']['clock_out_of_bounds'] == 1
    with unit_of_work(engine) as session:
        stored = session.get(MetricJournal, event.event_id)
        assert stored.submitted_occurred_at == event.occurred_at
        assert stored.clock_adjusted and stored.occurred_at == RECEIVED


@pytest.mark.parametrize('case', ['logout', 'switch', 'gap_same_owner', 'overlap', 'foreign_result'])
def test_clock_tolerance_never_donates_views_across_identity_boundaries(engine, storage_factory, case):
    value = seed(engine, storage_factory)
    target = None
    with unit_of_work(engine) as session:
        link = session.scalar(select(Link).where(Link.visitor_id == value[-1]))
        boundary = RECEIVED + timedelta(seconds=30)
        if case in {'logout', 'switch', 'gap_same_owner'}:
            link.ended_at = boundary
            link.end_basis = 'revoked'
        if case in {'switch', 'foreign_result', 'overlap'}:
            other = seed_account(session, storage_factory, view=False)
            other_link = session.scalar(select(Link).where(Link.visitor_id == other[-1]))
            if case == 'foreign_result':
                target = other[3].id
            else:
                other_link.visitor_id = value[-1]
                other_link.request_started_at = other_link.occurred_at = boundary if case == 'switch' else START
        if case == 'gap_same_owner':
            source = uuid4()
            session.add(Link(environment='test', visitor_id=value[-1], account_owner_id=value[0].id,
                kind='login', source_id=source, auth_session_id=source, cookie_issued_at=START,
                request_started_at=boundary+timedelta(seconds=10), occurred_at=boundary+timedelta(seconds=10),
                expires_at=END, ended_at=END, end_basis='expired'))
    # Delivery after the boundary; browser observation still belongs to the old segment.
    ingest(engine, value, received=RECEIVED+timedelta(seconds=60), result=target)
    activation = metric(report(engine, 'account'), 'activation', population='account', provenance='backend_server')
    assert activation.numerator == 0 and not activation.available
    assert sum(activation.coverage['unknown_account_views'].values()) == 1


@pytest.mark.parametrize('received,expected', [(RECEIVED, True), (RECEIVED+timedelta(minutes=2), False)])
def test_report_cutoff_uses_receipt_without_future_lookahead(engine, storage_factory, received, expected):
    from dataclasses import replace
    from fitcheck_backend.metrics.queries import load_snapshot
    from fitcheck_backend.metrics.server_calculations import confirmed_activity
    from test_metrics_server_report import options
    value = seed(engine, storage_factory)
    event = ingest(engine, value, 60, received=received)
    # Raw browser time is after this cutoff; receipt may be before or after it.
    end = RECEIVED+timedelta(seconds=30)
    with engine.connect() as connection:
        snapshot = load_snapshot(connection, replace(options('account'), end=end), 'test')
    _, views, _ = confirmed_activity(snapshot, end)
    assert [view.event_id for view in views] == ([event.event_id] if expected else [])


def test_view_before_domain_result_exists_is_unknown(engine, storage_factory):
    value = seed(engine, storage_factory)
    # Receive the observation before the immutable result's creation timestamp.
    ingest(engine, value, -60, received=RECEIVED-timedelta(seconds=3))
    activation = metric(report(engine, 'account'), 'activation', population='account', provenance='backend_server')
    assert activation.numerator == 0 and not activation.available
    assert activation.coverage['unknown_account_views']['unverified_result_job'] == 1


@pytest.mark.parametrize('boundary', [RECEIVED, RECEIVED-timedelta(seconds=2)])
def test_logout_boundary_is_exclusive_even_at_receipt_or_result_creation(engine, storage_factory, boundary):
    value = seed(engine, storage_factory)
    with unit_of_work(engine) as session:
        link = session.scalar(select(Link).where(Link.visitor_id == value[-1]))
        link.ended_at = boundary
        link.end_basis = 'revoked'
    ingest(engine, value, 60)
    activation = metric(report(engine, 'account'), 'activation', population='account', provenance='backend_server')
    assert activation.numerator == 0 and not activation.available


def test_migration_preserves_known_raw_clock_without_fabricating_adjusted_history(engine, storage_factory):
    import os
    from sqlalchemy import text
    from alembic import command
    from fitcheck_backend.storage.migrate import migration_config, run_migrations, check_schema
    value = seed(engine, storage_factory)
    normal = ingest(engine, value, -60)
    adjusted = ingest(engine, value, -3600)
    settings = Settings(database_url=os.environ['FITCHECK_TEST_DATABASE_URL'])
    with engine.connect() as connection:
        original = dict(connection.execute(text('SELECT event_id,payload_hash FROM metric_journal')).all())
    try:
        with engine.begin() as connection:
            command.downgrade(migration_config(connection), '0014')
        run_migrations(settings)
        check_schema(settings)
        with unit_of_work(engine) as session:
            assert session.get(MetricJournal, normal.event_id).submitted_occurred_at == normal.occurred_at
            legacy = session.get(MetricJournal, adjusted.event_id)
            assert legacy.submitted_occurred_at is None and legacy.clock_adjusted
            assert {row.event_id: row.payload_hash for row in session.scalars(select(MetricJournal))} == original
        # The bad historical view stays unknown even though its stored occurred_at
        # was replaced by collector receive time. The normal view still activates.
        row = metric(report(engine, 'account'), 'activation', population='account', provenance='backend_server')
        assert row.numerator == 1 and row.coverage['unknown_account_views']['missing_original_clock'] == 1
        assert row.coverage['formula_version'] == 'server_v3'
    finally:
        run_migrations(settings)

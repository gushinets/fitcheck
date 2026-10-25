"""ANY-749: synthetic PostgreSQL controls for physical calls vs logical operations."""
import csv
import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from uuid import uuid4

import pytest
from sqlalchemy import select, func, delete, text

from fitcheck_backend.metrics.csv_export import write_csv
from fitcheck_backend.operations.retention import cleanup
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import ProviderCall, Job, AnalysisRecord, Owner
from integration.test_metrics_server_report import START, END, seed_account, report, metric

pytestmark = pytest.mark.integration


def add_call(session, account, *, ordinal=1, cost=Decimal('1.25'), currency='USD', purpose='analysis.generate'):
    owner, _, job, *_ = account
    row = ProviderCall(owner_id=owner.id, job_id=job.id, request_key=None,
        provider='synthetic', model='synthetic', operation=purpose, attempt=ordinal,
        state='succeeded', created_at=job.created_at, finished_at=job.finished_at,
        input_tokens=100, output_tokens=20, cost=cost, currency=currency,
        cost_basis='estimated' if cost is not None else 'unknown')
    session.add(row)
    session.flush()
    return row


def exported_ratios(value):
    payload = value.to_json()
    selected = lambda row: row['metric'] in {'attempts_per_operation', 'cost_per_success', 'known_spend', 'provider_attempts', 'ai_tokens'} and row['dimensions'].get('source') == 'backend_server'
    rows = [row for row in payload['rows'] if selected(row)]
    output = StringIO()
    write_csv(value, output)
    csv_rows = list(csv.DictReader(StringIO(output.getvalue())))
    for expected in rows:
        actual = next(row for row in csv_rows if row['metric'] == expected['metric'] and json.loads(row['dimensions']) == expected['dimensions'])
        for key in ('value', 'numerator', 'denominator'):
            assert actual[key] == ('' if expected[key] is None else str(expected[key]))
        assert json.loads(actual['coverage']) == expected['coverage']
        assert actual['available'] == str(expected['available'])
    return rows


@pytest.mark.parametrize('population', ['account', 'all'])
@pytest.mark.parametrize('attempts', [1, 3])
def test_real_cleanup_preserves_ratios_and_json_csv(engine, storage_factory, population, attempts):
    with unit_of_work(engine) as session:
        accounts = [seed_account(session, storage_factory, day=day) for day in (0, 20)]
        for account in accounts:
            for ordinal in range(1, attempts+1):
                add_call(session, account, ordinal=ordinal)
    before = report(engine, population)
    ratio = metric(before, 'attempts_per_operation', source='backend_server', operation='analysis')
    assert (ratio.value, ratio.numerator, ratio.denominator, ratio.available) == (attempts, 2*attempts, 2, True)
    cost = metric(before, 'cost_per_success', source='backend_server', operation='analysis', currency='USD')
    assert (cost.value, cost.numerator, cost.denominator) == (Decimal('1.25')*attempts, Decimal('2.50')*attempts, 2)
    expected = exported_ratios(before)
    assert cleanup(engine, now=END, execute=True)['jobs'] == 1
    after = report(engine, population)
    assert exported_ratios(after) == expected
    assert metric(after, 'attempts_per_operation', source='backend_server', operation='analysis').coverage['unlinked_period_calls'] == 0
    assert cleanup(engine, now=END, execute=True)['jobs'] == 0
    assert exported_ratios(report(engine, population)) == expected
    with unit_of_work(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProviderCall)) == 2*attempts
        assert session.get(Job, accounts[0][2].id) is None
        assert session.get(Job, accounts[1][2].id) is not None


def test_legacy_lost_link_is_explicitly_unavailable_but_financial_totals_survive(engine, storage_factory):
    with unit_of_work(engine) as session:
        account = seed_account(session, storage_factory)
        add_call(session, account)
        lost = add_call(session, account, ordinal=2)
        lost.job_id = None  # Already lost before the migration; no safe reconstruction.
    result = report(engine, 'account')
    for name in ('attempts_per_operation', 'cost_per_success'):
        row = metric(result, name, source='backend_server', operation='analysis', **({'currency': 'USD'} if name == 'cost_per_success' else {}))
        assert not row.available and row.value is None
        assert 'link' in row.reason.lower()
        assert row.coverage['unlinked_period_calls'] == 1
    assert metric(result, 'known_spend', source='backend_server', currency='USD').value == Decimal('2.50')
    assert metric(result, 'provider_attempts', source='backend_server').value == 2
    assert metric(result, 'ai_tokens', source='backend_server', token_type='input_tokens').value == 200
    # A known analysis purpose does not poison unrelated operation kinds.
    assert metric(result, 'attempts_per_operation', source='backend_server', operation='skill_suggestions').available
    exported_ratios(result)


def test_mixed_currencies_and_unknown_price_survive_cleanup(engine, storage_factory):
    with unit_of_work(engine) as session:
        old = seed_account(session, storage_factory)
        recent = seed_account(session, storage_factory, day=20)
        add_call(session, old)
        add_call(session, old, ordinal=2, cost=Decimal('.50'), currency='EUR', purpose='analysis.audit')
        add_call(session, old, ordinal=3, cost=None, currency=None)
        add_call(session, recent)
    before = report(engine)
    expected = exported_ratios(before)
    assert metric(before, 'unpriced_calls', source='backend_server').value == 1
    assert metric(before, 'known_spend', source='backend_server', currency='USD').value == Decimal('2.50')
    assert metric(before, 'known_spend', source='backend_server', currency='EUR').value == Decimal('.50')
    assert cleanup(engine, now=END, execute=True)['jobs'] == 1
    assert exported_ratios(report(engine)) == expected


def test_provider_admission_uses_job_identity_independent_of_execution_context(engine, storage_factory):
    from dataclasses import replace
    from fitcheck_backend.budgets.types import CallBounds
    from fitcheck_backend.storage.provider_repository import ProviderLedger
    from integration.test_provider_execution import attempt
    with unit_of_work(engine) as session:
        account = storage_factory(session)
    ledger = ProviderLedger(engine)
    bounds = CallBounds(100, 100, Decimal('.001'), 'openai.luna.2026-10-16')
    first = attempt(account[0].id, account[2].id)
    call_ids = [ledger.start(first, bounds=bounds), ledger.start(replace(first, operation_id=uuid4(), physical_attempt=2), bounds=bounds)]
    with unit_of_work(engine) as session:
        assert {session.get(ProviderCall, call_id).operation_id for call_id in call_ids} == {account[2].id}


def test_owner_deletion_clears_durable_identity_but_preserves_cost(engine, storage_factory):
    with unit_of_work(engine) as session:
        account = seed_account(session, storage_factory)
        row = add_call(session, account)
    cleanup(engine, now=END, execute=True)
    with unit_of_work(engine) as session:
        assert session.get(ProviderCall, row.id).operation_id == account[2].id
        session.execute(delete(Owner).where(Owner.id == account[0].id))
    with unit_of_work(engine) as session:
        row = session.get(ProviderCall, row.id)
        assert (row.owner_id, row.job_id, row.operation_id, row.request_key) == (None, None, None, None)
        assert row.cost == Decimal('1.25') and row.input_tokens == 100
        assert session.get(AnalysisRecord, account[3].id) is None
    result = report(engine, 'account')
    assert metric(result, 'known_spend', source='backend_server', currency='USD').value == Decimal('1.25')
    assert metric(result, 'attempts_per_operation', source='backend_server', operation='analysis').denominator == 0


def test_migration_backfills_only_intact_links_and_preserves_anonymization(engine, storage_factory):
    from alembic import command
    from fitcheck_backend.storage.migrate import migration_config, run_migrations, check_schema
    from fitcheck_backend.config import Settings
    settings = Settings(database_url=engine.url.render_as_string(hide_password=False))
    with unit_of_work(engine) as session:
        owner, _, job, *_ = storage_factory(session)
    linked, unlinked, anonymous = uuid4(), uuid4(), uuid4()
    try:
        with engine.begin() as conn:
            command.downgrade(migration_config(conn), '0013')
            for call_id, owner_id, job_id in [(linked, owner.id, job.id), (unlinked, owner.id, None), (anonymous, None, None)]:
                conn.execute(text("INSERT INTO provider_calls(id,owner_id,job_id,provider,model,operation,attempt,state,input_tokens,cost,currency,created_at) VALUES (:id,:owner,:job,'synthetic','synthetic','analysis.generate',1,'succeeded',100,1.25,'USD',now())"),
                    {'id': call_id, 'owner': owner_id, 'job': job_id})
        run_migrations(settings)
        check_schema(settings)
        with engine.connect() as conn:
            rows = dict(conn.execute(text('SELECT id, operation_id FROM provider_calls')).all())
            assert rows == {linked: job.id, unlinked: None, anonymous: None}
            assert conn.scalar(text('SELECT sum(cost) FROM provider_calls')) == Decimal('3.75')
        with engine.begin() as conn:
            conn.execute(text('DELETE FROM owners WHERE id=:id'), {'id': owner.id})
        with engine.connect() as conn:
            assert conn.scalar(text('SELECT count(*) FROM provider_calls WHERE operation_id IS NOT NULL')) == 0
            assert conn.scalar(text('SELECT sum(cost) FROM provider_calls')) == Decimal('3.75')
    finally:
        run_migrations(settings)


@pytest.mark.parametrize('claim_before_cleanup', [True, False])
def test_guest_claim_preserves_cost_operation_without_account_activation(engine, storage_factory, claim_before_cleanup):
    from fitcheck_backend.storage.ownership import transfer_guest_analyses
    from fitcheck_backend.storage.models import Guest, VacancyRecord
    with unit_of_work(engine) as session:
        account = seed_account(session, storage_factory, day=20, view=False)
        owner = Owner(kind='guest'); session.add(owner); session.flush()
        identity = Guest(owner_id=owner.id, expires_at=END+timedelta(days=1), created_at=START)
        job = Job(owner_id=owner.id, type='analysis', input={'mode': 'guest'}, status='succeeded',
            idempotency_key=str(uuid4()), request_hash='b'*64, created_at=START, finished_at=START+timedelta(hours=1))
        vacancy = VacancyRecord(owner_id=owner.id, vacancy={})
        session.add_all([identity, job, vacancy]); session.flush()
        analysis = AnalysisRecord(owner_id=owner.id, job_id=job.id, job_type='analysis', vacancy_id=vacancy.id,
            snapshot={}, analysis={'score': 70}, created_at=job.finished_at)
        session.add(analysis); session.flush()
        guest = (owner, identity, job, vacancy, analysis)
        guest_call = add_call(session, guest)
        add_call(session, account)
    expected = exported_ratios(report(engine))
    if claim_before_cleanup:
        with unit_of_work(engine) as session:
            assert transfer_guest_analyses(session, guest[0].id, account[0].id) == 1
    assert cleanup(engine, now=END, execute=True)['jobs'] == 1
    if not claim_before_cleanup:
        with unit_of_work(engine) as session:
            assert transfer_guest_analyses(session, guest[0].id, account[0].id) == 1
    result = report(engine)
    assert exported_ratios(result) == expected
    assert metric(result, 'successful_operations', population='account', operation='analysis', provenance='deployment_database_scope').value == 1
    assert metric(result, 'successful_operations', population='visitor', operation='analysis', provenance='server_guest_domain').value == 1
    assert metric(result, 'activation', population='account', provenance='backend_server').numerator == 0
    with unit_of_work(engine) as session:
        call = session.get(ProviderCall, guest_call.id)
        assert call.owner_id == account[0].id and call.operation_id == guest[2].id
        assert transfer_guest_analyses(session, guest[0].id, account[0].id) == 0
    assert cleanup(engine, now=END, execute=True)['jobs'] == 0
    assert exported_ratios(report(engine)) == expected


def test_erased_result_is_not_reconstructed_by_retained_call_identity(engine, storage_factory):
    from fitcheck_backend.storage.analysis_operation import AnalysisOperationProof
    with unit_of_work(engine) as session:
        account = seed_account(session, storage_factory)
        call = add_call(session, account)
        session.execute(delete(AnalysisRecord).where(AnalysisRecord.id == account[3].id))
    cleanup(engine, now=END, execute=True)
    with unit_of_work(engine) as session:
        assert session.get(ProviderCall, call.id).operation_id == account[2].id
        assert session.get(AnalysisOperationProof, account[3].id) is None
        assert session.get(AnalysisRecord, account[3].id) is None
    result = report(engine)
    assert metric(result, 'activation', population='account', provenance='backend_server').numerator == 0
    row = metric(result, 'cost_per_success', source='backend_server', operation='analysis', currency='USD')
    assert row.value is None and not row.available
    assert row.coverage['unverifiable_cohort_calls'] == 1


def test_operator_cli_json_csv_before_after_cleanup(engine, storage_factory, monkeypatch, tmp_path):
    from fitcheck_backend.config import Settings
    from fitcheck_backend.metrics.__main__ import main
    import fitcheck_backend.metrics.__main__ as cli
    with unit_of_work(engine) as session:
        for day in (0, 20):
            add_call(session, seed_account(session, storage_factory, day=day))
    monkeypatch.setattr(cli, 'create_engine', lambda settings: engine)
    monkeypatch.setattr(cli, 'Settings', lambda: Settings(metrics_database_environment='test'))
    args = ['report', '--start', START.isoformat(), '--end', END.isoformat(), '--environment', 'test', '--population', 'all']
    def output(suffix):
        json_path, csv_path = tmp_path/f'{suffix}.json', tmp_path/f'{suffix}.csv'
        assert main(args+['--format', 'json', '--output', str(json_path)]) == 0
        assert main(args+['--format', 'csv', '--output', str(csv_path)]) == 0
        json_rows = [row for row in json.loads(json_path.read_text())['rows'] if row['metric'] in {'attempts_per_operation', 'cost_per_success'}]
        with csv_path.open() as stream:
            csv_rows = [row for row in csv.DictReader(stream) if row['metric'] in {'attempts_per_operation', 'cost_per_success'}]
        return json_rows, csv_rows
    expected = output('before')
    assert cleanup(engine, now=END, execute=True)['jobs'] == 1
    assert output('after') == expected


def test_failed_guest_without_retained_cohort_proof_is_unavailable_after_cleanup(engine):
    from fitcheck_backend.storage.models import Guest
    with unit_of_work(engine) as session:
        owner = Owner(kind='guest'); session.add(owner); session.flush()
        session.add(Guest(owner_id=owner.id, expires_at=END+timedelta(days=1)))
        job = Job(owner_id=owner.id, type='analysis', input={'mode': 'guest'}, status='failed',
            idempotency_key=str(uuid4()), request_hash='c'*64, created_at=START, finished_at=START+timedelta(hours=1),
            error={'code': 'upstream_error'})
        session.add(job); session.flush()
        call = add_call(session, (owner, None, job))
        call.state = 'failed'
    before = report(engine, 'account')
    assert metric(before, 'attempts_per_operation', source='backend_server', operation='analysis').value == 1
    assert cleanup(engine, now=END, execute=True)['jobs'] == 1
    after = report(engine, 'account')
    row = metric(after, 'attempts_per_operation', source='backend_server', operation='analysis')
    assert row.value is None and not row.available and row.coverage['unverifiable_cohort_calls'] == 1
    assert metric(after, 'known_spend', source='backend_server', currency='USD').value == Decimal('1.25')
    assert metric(after, 'provider_attempts', source='backend_server').value == 1
    with unit_of_work(engine) as session:
        retained = session.get(ProviderCall, call.id)
        assert retained.operation_id == job.id and retained.job_id is None


def test_non_job_admission_retains_its_context_operation_and_erasure_removes_it(engine, storage_factory):
    from fitcheck_backend.budgets.types import CallBounds
    from fitcheck_backend.storage.provider_repository import ProviderLedger
    from integration.test_provider_execution import attempt
    with unit_of_work(engine) as session:
        owner = storage_factory(session)[0]
    submitted = attempt(owner.id, None)
    call_id = ProviderLedger(engine).start(submitted, bounds=CallBounds(100, 100, Decimal('.001'), 'openai.luna.2026-10-16'))
    with unit_of_work(engine) as session:
        assert session.get(ProviderCall, call_id).operation_id == submitted.operation_id
        session.execute(delete(Owner).where(Owner.id == owner.id))
    with unit_of_work(engine) as session:
        assert session.get(ProviderCall, call_id).operation_id is None


@pytest.mark.parametrize('anonymous', [True, False])
def test_schema_rejects_anonymous_or_mismatched_operation_link(engine, storage_factory, anonymous):
    from sqlalchemy.exc import IntegrityError
    with unit_of_work(engine) as session:
        owner, _, job, *_ = storage_factory(session)
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(ProviderCall(owner_id=None if anonymous else owner.id,
                job_id=None if anonymous else job.id, operation_id=uuid4(), provider='synthetic',
                model='synthetic', operation='analysis.generate', attempt=1, state='succeeded'))
            session.flush()

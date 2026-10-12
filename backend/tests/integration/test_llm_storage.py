from datetime import datetime, UTC
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, inspect

from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import ProviderCall, AnalysisRecord, VacancyRecord, AnalysisAnnotation

pytestmark = pytest.mark.integration


def attempt(owner_id, job_id=None):
    from fitcheck_backend.storage.provider_repository import ProviderAttempt
    return ProviderAttempt(owner_id=owner_id, job_id=job_id, operation_id=uuid4(),
        physical_attempt=1, semantic_attempt=1, transport_attempt=1, operation='analysis.generate',
        provider='deepseek', model='deepseek-v4-flash', prompt_version='prompt.v1',
        schema_version='fitcheck.analysis.v1', policy_version='policy.v1')


def test_attempt_commits_survive_caller_rollback(engine, storage_factory):
    from fitcheck_backend.storage.provider_repository import ProviderLedger
    with unit_of_work(engine) as s:
        owner, _, job, *_ = storage_factory(s)
    ledger = ProviderLedger(engine)
    with pytest.raises(RuntimeError):
        with unit_of_work(engine):
            call_id = ledger.start(attempt(owner.id, job.id))
            ledger.finish(call_id, state='failed', input_tokens=12, output_tokens=4,
                cost=Decimal('0.001'), currency='USD', latency_ms=31, error_code='invalid_output')
            raise RuntimeError('caller failed')
    with unit_of_work(engine) as s:
        row = s.get(ProviderCall, call_id)
        assert (row.state, row.input_tokens, row.output_tokens, row.latency_ms) == ('failed', 12, 4, 31)
        assert row.policy_version == 'policy.v1' and row.prompt_version == 'prompt.v1'
        assert row.schema_version == 'fitcheck.analysis.v1'
        assert row.semantic_attempt == row.transport_attempt == row.attempt == 1
        assert row.cost == Decimal('0.001') and row.finished_at is not None


def test_ledger_rejects_foreign_job(engine, storage_factory):
    from fitcheck_backend.storage.provider_repository import ProviderLedger
    with unit_of_work(engine) as s:
        owner, *_ = storage_factory(s)
        _, _, foreign, *_ = storage_factory(s)
    with pytest.raises(ValueError, match='ownership'):
        ProviderLedger(engine).start(attempt(owner.id, foreign.id))
    with unit_of_work(engine) as s:
        assert s.scalars(select(ProviderCall)).all() == []


def test_old_provider_rows_upgrade_with_nullable_metadata(engine, storage_factory):
    with unit_of_work(engine) as s:
        owner, *_ = storage_factory(s)
        s.add(ProviderCall(owner_id=owner.id, provider='deepseek', model='old',
            operation='analysis', attempt=1, state='unknown'))
    with unit_of_work(engine) as s:
        row = s.scalar(select(ProviderCall))
        assert row.latency_ms is None and row.policy_version is None
        assert row.input_tokens is None and row.cost is None
    assert 'prompt_version' in {c['name'] for c in inspect(engine).get_columns('provider_calls')}


def test_memory_is_owner_scoped_and_stable_last_ten(engine, storage_factory):
    from fitcheck_backend.storage.calibration_repository import get_calibration
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/domain.json').read_text())
    with unit_of_work(engine) as s:
        owner, _, _, _, base, annotation = storage_factory(s)
        s.delete(annotation); s.flush(); s.delete(base); s.flush()
        other, _, _, _, base, annotation = storage_factory(s)
        s.delete(annotation); s.flush(); s.delete(base); s.flush()
        snapshot = dict(profileRevision="1", profile=fixture["profile"], vacancy=fixture["vacancy"],
            locale="en", promptVersion="prompt.v1", schemaVersion="fitcheck.analysis.v1", policyVersion="policy.v1")
        for i in range(12):
            vacancy = VacancyRecord(owner_id=owner.id, vacancy={**fixture['vacancy'], 'title': f'Job {i}'})
            s.add(vacancy); s.flush()
            row = AnalysisRecord(id=UUID(int=i + 1), owner_id=owner.id, vacancy_id=vacancy.id,
                created_at=datetime(2026, 1, 1, tzinfo=UTC), snapshot={**snapshot, 'vacancy': {**fixture['vacancy'], 'title': f'Job {i}'}},
                analysis={**fixture['analysis'], 'score': i})
            s.add(row); s.flush()
            s.add(AnalysisAnnotation(owner_id=owner.id, analysis_id=row.id,
                corrected_score=70, note=f'note {i}', feedback_created_at=datetime(2026, 1, 2, tzinfo=UTC)))
        vacancy = VacancyRecord(owner_id=other.id, vacancy=fixture['vacancy'])
        s.add(vacancy); s.flush()
        s.add(AnalysisRecord(owner_id=other.id, vacancy_id=vacancy.id,
            snapshot=snapshot, analysis=fixture['analysis']))
    with unit_of_work(engine) as s:
        entries = get_calibration(s, owner.id)
        assert len(entries) == 10
        assert [v.job_title for v in entries] == [f'Job {i}' for i in range(11, 1, -1)]
        assert entries[0].predicted_score == 11 and entries[0].corrected_score == 70
        assert entries[0].note == 'note 11'

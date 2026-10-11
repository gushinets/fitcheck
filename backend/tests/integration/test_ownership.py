from decimal import Decimal

import pytest
from sqlalchemy import select, update, delete, func

from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Owner, Guest, User, Job, AnalysisRecord, VacancyRecord, AnalysisAnnotation, ProviderCall, ProfileRevision, Profile, ImportEntry
from fitcheck_backend.storage.base import utcnow

pytestmark = pytest.mark.integration


def setup_graph(session, factory):
    guest = factory(session, kind="guest")
    user = factory(session)
    session.add_all([ProfileRevision(owner_id=guest[0].id, revision=1, profile={"guest":True}), ProfileRevision(owner_id=user[0].id, revision=1, profile={"user":True})])
    session.flush()
    session.add_all([Profile(owner_id=guest[0].id, current_revision=1), Profile(owner_id=user[0].id, current_revision=1)])
    session.execute(update(AnalysisRecord).where(AnalysisRecord.id==guest[4].id).values(profile_revision=1))
    call = ProviderCall(owner_id=guest[0].id, job_id=guest[2].id, request_key="provider-secret-key", provider="test", operation="analysis", model="test", attempt=1, state="succeeded", input_tokens=123, output_tokens=50, cost=Decimal("0.12345678"), currency="USD")
    session.add(call)
    session.add(ImportEntry(owner_id=guest[0].id, external_id="legacy-1", content_hash="a"*64, analysis_id=guest[4].id))
    session.flush()
    return guest, user, call.id


def test_transfer_guest_graph_preserves_account_profile(engine, storage_factory):
    from fitcheck_backend.storage.ownership import transfer_guest_analyses
    with unit_of_work(engine) as session:
        guest, user, call_id = setup_graph(session, storage_factory)
        guest_id, user_id, analysis_id, job_id = guest[0].id, user[0].id, guest[4].id, guest[2].id
    with unit_of_work(engine) as session:
        assert transfer_guest_analyses(session, guest_id, user_id) == 1
    with unit_of_work(engine) as session:
        analysis = session.get(AnalysisRecord, analysis_id)
        assert analysis.owner_id == user_id and analysis.profile_revision is None
        assert analysis.snapshot == {"sample":True} and analysis.analysis == {"sample":True}
        assert session.get(Job, job_id).owner_id == user_id
        assert session.get(VacancyRecord, analysis.vacancy_id).owner_id == user_id
        assert session.get(AnalysisAnnotation, analysis_id).owner_id == user_id
        assert session.get(ProviderCall, call_id).owner_id == user_id
        assert session.scalar(select(ProfileRevision.profile).where(ProfileRevision.owner_id==user_id, ProfileRevision.revision==1)) == {"user":True}
        assert transfer_guest_analyses(session, guest_id, user_id) == 0


def test_transfer_rollback_restores_every_owner(engine, storage_factory):
    from fitcheck_backend.storage.ownership import transfer_guest_analyses
    with unit_of_work(engine) as session:
        guest, user, call_id = setup_graph(session, storage_factory)
        guest_id, user_id, analysis_id = guest[0].id, user[0].id, guest[4].id
    with pytest.raises(RuntimeError):
        with unit_of_work(engine) as session:
            transfer_guest_analyses(session, guest_id, user_id)
            raise RuntimeError("abort")
    with unit_of_work(engine) as session:
        assert session.get(AnalysisRecord, analysis_id).owner_id == guest_id
        assert session.get(ProviderCall, call_id).owner_id == guest_id
        assert session.scalar(select(Guest.claimed_at).where(Guest.owner_id==guest_id)) is None


def test_pending_jobs_block_transfer(db_session, storage_factory):
    from fitcheck_backend.storage.ownership import transfer_guest_analyses, OwnershipConflict
    guest = storage_factory(db_session, kind="guest", terminal=False)
    user = storage_factory(db_session)
    with pytest.raises(OwnershipConflict):
        transfer_guest_analyses(db_session, guest[0].id, user[0].id)
    assert db_session.get(AnalysisRecord, guest[4].id).owner_id == guest[0].id


def test_key_collision_aborts_transfer(db_session, storage_factory):
    from fitcheck_backend.storage.ownership import transfer_guest_analyses, OwnershipConflict
    guest = storage_factory(db_session, kind="guest")
    user = storage_factory(db_session)
    # Input key is immutable; insert a collision rather than updating it.
    db_session.add(Job(owner_id=user[0].id, type="analysis", input={}, idempotency_key=guest[2].idempotency_key, request_hash="a"*64))
    db_session.flush()
    with pytest.raises(OwnershipConflict):
        transfer_guest_analyses(db_session, guest[0].id, user[0].id)
    assert db_session.get(Job, guest[2].id).owner_id == guest[0].id
    assert db_session.scalar(select(Guest.claimed_at).where(Guest.owner_id==guest[0].id)) is None


def test_owner_deletion_removes_personal_data_and_anonymizes_ledger(engine, storage_factory):
    from fitcheck_backend.storage.ownership import transfer_guest_analyses, delete_owner
    with unit_of_work(engine) as session:
        guest, user, call_id = setup_graph(session, storage_factory)
        transfer_guest_analyses(session, guest[0].id, user[0].id)
        delete_owner(session, user[0].id)
    with unit_of_work(engine) as session:
        for model in [Owner, User, Guest, Job, AnalysisRecord, VacancyRecord, AnalysisAnnotation, Profile, ProfileRevision, ImportEntry]:
            assert session.scalar(select(func.count()).select_from(model)) == 0
        call = session.get(ProviderCall, call_id)
        assert (call.owner_id, call.job_id, call.request_key) == (None, None, None)
        assert (call.input_tokens, call.cost) == (123, Decimal("0.12345678"))


def test_job_cleanup_preserves_analysis(db_session, storage_factory):
    graph = storage_factory(db_session)
    db_session.execute(update(AnalysisRecord).where(AnalysisRecord.id==graph[4].id).values(job_id=None, job_type=None))
    db_session.execute(delete(Job).where(Job.id==graph[2].id))
    assert db_session.get(AnalysisRecord, graph[4].id).analysis == {"sample":True}


def test_new_job_for_claimed_guest_rejected(db_session, storage_factory):
    from fitcheck_backend.storage.ownership import transfer_guest_analyses
    from fitcheck_backend.storage.job_repository import get_or_create_job
    guest = storage_factory(db_session, kind="guest")
    user = storage_factory(db_session)
    transfer_guest_analyses(db_session, guest[0].id, user[0].id)
    with pytest.raises(RuntimeError):
        get_or_create_job(db_session, guest[0].id, "skill_suggestions", "after-claim", {"locale":"ru", "specialization":"Frontend"})


def test_guest_analysis_cannot_use_account_input(db_session, storage_factory):
    from fitcheck_backend.storage.job_repository import get_or_create_job, OwnerUnavailable
    guest = storage_factory(db_session, kind="guest")
    import json
    from pathlib import Path
    vacancy = json.loads((Path(__file__).parents[1]/"fixtures/domain.json").read_text())["vacancy"]
    with pytest.raises(OwnerUnavailable):
        get_or_create_job(db_session, guest[0].id, "analysis", "wrong-mode", {"mode":"account", "profileRevision":"1", "vacancy":vacancy, "locale":"en"})


def test_cached_guest_cannot_create_job_after_other_session_claim(engine, storage_factory):
    from sqlalchemy.orm import Session
    from fitcheck_backend.storage.ownership import transfer_guest_analyses
    from fitcheck_backend.storage.job_repository import get_or_create_job, OwnerUnavailable
    with Session(engine, expire_on_commit=False) as stale:
        guest = storage_factory(stale, kind="guest")
        user = storage_factory(stale)
        stale.commit()
        stale.refresh(guest[1])
        with unit_of_work(engine) as fresh:
            transfer_guest_analyses(fresh, guest[0].id, user[0].id)
        assert guest[1].claimed_by_user_id is None  # Deliberately retained stale ORM object.
        with pytest.raises(OwnerUnavailable):
            get_or_create_job(stale, guest[0].id, "skill_suggestions", "stale-session", {"locale":"ru", "specialization":"Frontend"})


def test_cached_guest_cannot_be_reclaimed_by_another_account(engine, storage_factory):
    from sqlalchemy.orm import Session
    from fitcheck_backend.storage.ownership import transfer_guest_analyses, OwnershipConflict
    with Session(engine, expire_on_commit=False) as stale:
        guest = storage_factory(stale, kind="guest")
        first = storage_factory(stale)
        second = storage_factory(stale)
        stale.commit()
        stale.refresh(guest[1])
        with unit_of_work(engine) as fresh:
            transfer_guest_analyses(fresh, guest[0].id, first[0].id)
        assert guest[1].claimed_by_user_id is None
        with pytest.raises(OwnershipConflict):
            transfer_guest_analyses(stale, guest[0].id, second[0].id)
        stale.rollback()
        with unit_of_work(engine) as fresh:
            assert fresh.scalar(select(Guest.claimed_by_user_id).where(Guest.owner_id==guest[0].id)) == first[1].id


def test_claim_uses_current_terminal_job_state(engine, storage_factory):
    from sqlalchemy.orm import Session
    from fitcheck_backend.storage.ownership import transfer_guest_analyses
    with Session(engine, expire_on_commit=False) as stale:
        guest = storage_factory(stale, kind="guest", terminal=False)
        user = storage_factory(stale)
        stale.commit()
        stale.refresh(guest[2])
        with unit_of_work(engine) as fresh:
            fresh.execute(update(Job).where(Job.id==guest[2].id).values(status="succeeded", finished_at=utcnow()))
        assert guest[2].status == "queued"
        assert transfer_guest_analyses(stale, guest[0].id, user[0].id) == 1

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, DBAPIError

from fitcheck_backend.storage.models import AnalysisRecord, Job, ProfileRevision, VacancyRecord, AnalysisAnnotation

pytestmark = pytest.mark.integration


def test_wrong_owner_link_rejected(db_session, storage_factory):
    a = storage_factory(db_session)
    b = storage_factory(db_session)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(update(AnalysisRecord).where(AnalysisRecord.id == a[4].id).values(vacancy_id=b[3].id))


def test_wrong_job_type_and_partial_null_rejected(db_session, storage_factory):
    a = storage_factory(db_session)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(update(AnalysisRecord).where(AnalysisRecord.id == a[4].id).values(job_type=None))
    other = Job(owner_id=a[0].id, type="skill_suggestions", input={}, request_hash="a"*64, idempotency_key="other")
    db_session.add(other)
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(update(AnalysisRecord).where(AnalysisRecord.id == a[4].id).values(job_id=other.id, job_type="analysis"))


@pytest.mark.parametrize("index,model,column", [(2,Job,"input"), (3,VacancyRecord,"vacancy"), (4,AnalysisRecord,"snapshot"), (4,AnalysisRecord,"analysis")])
def test_payload_mutations_rejected(db_session, storage_factory, index, model, column):
    graph = storage_factory(db_session)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(update(model).where(model.id == graph[index].id).values({column: {"changed": True}}))
    db_session.execute(update(AnalysisAnnotation).where(AnalysisAnnotation.analysis_id == graph[4].id).values(application_status="applied"))
    assert db_session.get(AnalysisAnnotation, graph[4].id).application_status == "applied"


def test_profile_revision_mutations_rejected(db_session, storage_factory):
    graph = storage_factory(db_session)
    revision = ProfileRevision(owner_id=graph[0].id, revision=1, profile={"original": True})
    db_session.add(revision)
    db_session.flush()
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(update(ProfileRevision).where(ProfileRevision.id == revision.id).values(profile={"changed": True}))

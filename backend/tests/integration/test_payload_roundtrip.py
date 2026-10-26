from pathlib import Path
from datetime import datetime
import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError

from fitcheck_backend.contracts.domain import FreelancerProfile, Vacancy, FitAnalysis
from fitcheck_backend.contracts.resources import LegacyProfile, AnalysisSnapshot
from fitcheck_backend.storage.models import ProfileRevision, VacancyRecord, AnalysisRecord
from fitcheck_backend.storage.payloads import encode_profile, decode_profile, encode_vacancy, decode_vacancy, encode_snapshot, decode_snapshot, encode_analysis, decode_analysis

pytestmark = pytest.mark.integration


def test_full_jsonb_roundtrip_and_legacy_normalization(db_session, storage_factory):
    data = json.loads((Path(__file__).parents[1]/"fixtures/domain.json").read_text())
    data["vacancy"]["url"] = "https://example.com/jobs/task-1"
    data["analysis"]["strengthEvidence"] = [{"id":"react", "profileFields":["skills"], "taskFields":["skills"]}]
    owner = storage_factory(db_session)[0].id
    profile = LegacyProfile.model_validate(data["profile"] | {"desiredMonthlyIncome":9999})
    revision = ProfileRevision(owner_id=owner, revision=1, profile=encode_profile(profile))
    vacancy = VacancyRecord(owner_id=owner, source_url=data["vacancy"]["url"], vacancy=encode_vacancy(Vacancy.model_validate(data["vacancy"])))
    db_session.add_all([revision, vacancy])
    db_session.flush()
    snapshot = AnalysisSnapshot(profileRevision="1", profile=data["profile"], vacancy=data["vacancy"], locale="en", promptVersion="v1", schemaVersion="fitcheck.analysis.v1", policyVersion="v1")
    record = AnalysisRecord(owner_id=owner, vacancy_id=vacancy.id, profile_revision=1, snapshot=encode_snapshot(snapshot), analysis=encode_analysis(FitAnalysis.model_validate(data["analysis"])))
    db_session.add(record)
    db_session.flush()
    db_session.expire_all()
    raw_profile = db_session.scalar(select(ProfileRevision.profile).where(ProfileRevision.id==revision.id))
    assert "desiredMonthlyIncome" not in raw_profile
    assert decode_profile(raw_profile).model_dump(mode="json", by_alias=True) == data["profile"]
    assert decode_vacancy(db_session.get(VacancyRecord, vacancy.id).vacancy).model_dump(mode="json", by_alias=True) == data["vacancy"]
    assert db_session.get(VacancyRecord, vacancy.id).source_url == "https://example.com/jobs/task-1"
    loaded = db_session.get(AnalysisRecord, record.id)
    assert decode_snapshot(loaded.snapshot) == snapshot
    assert decode_analysis(loaded.analysis).model_dump(mode="json", by_alias=True) == data["analysis"]


def test_naive_datetime_rejected_at_database_boundary(db_session, storage_factory):
    owner = storage_factory(db_session)[0].id
    with pytest.raises(StatementError, match="timezone-aware"):
        with db_session.begin_nested():
            db_session.add(ProfileRevision(owner_id=owner, revision=1, profile={}, created_at=datetime(2026,1,1)))
            db_session.flush()

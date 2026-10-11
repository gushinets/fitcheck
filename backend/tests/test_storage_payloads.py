import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from fitcheck_backend.contracts.domain import FreelancerProfile, Vacancy, FitAnalysis
from fitcheck_backend.contracts.resources import AnalysisSnapshot, LegacyProfile


def fixture():
    return json.loads((Path(__file__).parent / "fixtures/domain.json").read_text())


def test_complete_dto_round_trip():
    from fitcheck_backend.storage import payloads as p
    data = fixture()
    data["analysis"]["strengthEvidence"] = [{"id": "react", "profileFields": ["skills"], "taskFields": ["skills"]}]
    for model, encode, decode, key in [(FreelancerProfile, p.encode_profile, p.decode_profile, "profile"), (Vacancy, p.encode_vacancy, p.decode_vacancy, "vacancy"), (FitAnalysis, p.encode_analysis, p.decode_analysis, "analysis")]:
        value = model.model_validate(data[key])
        encoded = encode(value)
        assert decode(encoded).model_dump(mode="json", by_alias=True) == data[key]
    assert p.encode_profile(FreelancerProfile.model_validate(data["profile"]))["skillLevels"] == {"react": "primary"}
    assert p.encode_vacancy(Vacancy.model_validate(data["vacancy"]))["fixedBudgetMax"] == 2000


def test_legacy_income_is_never_encoded():
    from fitcheck_backend.storage.payloads import encode_profile, decode_profile
    data = fixture()["profile"] | {"desiredMonthlyIncome": {"secret": "ignored"}}
    encoded = encode_profile(LegacyProfile.model_validate(data))
    assert "desiredMonthlyIncome" not in encoded
    assert decode_profile(encoded).preferred_rate == 50


def test_snapshot_version_rejected():
    from fitcheck_backend.storage.payloads import encode_snapshot, decode_snapshot, UnsupportedSnapshotVersion
    data = fixture()
    value = AnalysisSnapshot(profileRevision="1", profile=data["profile"], vacancy=data["vacancy"], locale="ru", promptVersion="v1", schemaVersion="fitcheck.analysis.v1", policyVersion="v1")
    encoded = encode_snapshot(value)
    assert decode_snapshot(encoded) == value
    with pytest.raises(UnsupportedSnapshotVersion):
        decode_snapshot(encoded | {"schemaVersion": "unknown"})
    with pytest.raises(ValidationError):
        decode_snapshot(encoded | {"profile": None})


def test_hash_is_order_independent_and_input_sensitive():
    from fitcheck_backend.storage.payloads import canonical_hash
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    base = {"locale": "ru", "profile": {"skills": ["React"]}, "promptVersion": "v1"}
    for changed in [base | {"locale": "en"}, base | {"promptVersion": "v2"}, base | {"profile": {"skills": ["Python"]}}]:
        assert canonical_hash(changed) != canonical_hash(base)
    with pytest.raises(ValueError):
        canonical_hash({"money": float("nan")})

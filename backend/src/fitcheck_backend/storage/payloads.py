"""Validated codecs at JSONB boundaries; wire field names are preserved."""
import hashlib
import json

from fitcheck_backend.contracts.domain import FreelancerProfile, Vacancy, FitAnalysis
from fitcheck_backend.contracts.resources import AnalysisSnapshot, LegacyProfile
from fitcheck_backend.contracts.imports import LegacyAnalysisSnapshot

CURRENT_SCHEMA_VERSION = "fitcheck.analysis.v1"


class UnsupportedSnapshotVersion(ValueError):
    pass


def encode_profile(value: FreelancerProfile | LegacyProfile) -> dict:
    return decode_profile(value.model_dump(mode="json", by_alias=True)).model_dump(mode="json", by_alias=True)


def decode_profile(value: dict) -> FreelancerProfile:
    return FreelancerProfile.model_validate(value)


def encode_vacancy(value: Vacancy) -> dict:
    return decode_vacancy(value.model_dump(mode="json", by_alias=True)).model_dump(mode="json", by_alias=True)


def decode_vacancy(value: dict) -> Vacancy:
    return Vacancy.model_validate(value)


def encode_snapshot(value: AnalysisSnapshot) -> dict:
    return decode_snapshot(value.model_dump(mode="json", by_alias=True)).model_dump(mode="json", by_alias=True)


def decode_snapshot(value: dict) -> AnalysisSnapshot:
    if value.get("schemaVersion") == "fitcheck.legacy-analysis.v1":
        return LegacyAnalysisSnapshot.model_validate(value)
    if value.get("schemaVersion") != CURRENT_SCHEMA_VERSION:
        raise UnsupportedSnapshotVersion("Unsupported analysis snapshot schema version")
    return AnalysisSnapshot.model_validate(value)


def encode_analysis(value: FitAnalysis) -> dict:
    return decode_analysis(value.model_dump(mode="json", by_alias=True)).model_dump(mode="json", by_alias=True)


def decode_analysis(value: dict) -> FitAnalysis:
    return FitAnalysis.model_validate(value)


def canonical_hash(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

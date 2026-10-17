from copy import deepcopy
import importlib
import pytest
from pydantic import ValidationError
from analysis_fixtures import DATA
from fitcheck_backend.storage.payloads import decode_snapshot


def contracts():
    return importlib.import_module('fitcheck_backend.contracts.imports')


def row(**changes):
    return dict(id='local-1',createdAt='2025-01-01T00:00:00Z',job=deepcopy(DATA['vacancy']),
                analysis=deepcopy(DATA['analysis']),**changes)


def test_export_envelope_limits_and_selection_identity():
    m=contracts()
    payload=dict(version=1,source='website_indexeddb_v1',sourceUserId='alice',history=[row()])
    assert m.LocalImportRequest.model_validate(payload).source_user_id=='alice'
    for change in [dict(version=2),dict(password={'hash':'secret'}),dict(history=[row(),row()]),dict(history=[{}]*1001)]:
        with pytest.raises(ValidationError):m.LocalImportRequest.model_validate(payload|change)
    assert len(m.LocalImportRequest.model_validate(payload|{'history':[{'id':'bad','analysis':{}}]}).history)==1


def test_row_preserves_feedback_evidence_and_rejects_credentials():
    m=contracts()
    value=row(profile=DATA['profile'],feedback=dict(correctedScore=62,createdAt='2025-01-02T00:00:00Z'))
    parsed=m.parse_import_row(value)
    assert parsed.created_at.year==2025 and parsed.feedback.corrected_score==62
    assert parsed.profile.skills==DATA['profile']['skills']
    legacy=deepcopy(DATA['profile']);legacy.pop('workFormats',None);legacy['desiredMonthlyIncome']=5000
    assert m.parse_import_row(value|{'profile':legacy}).profile.work_formats==['remote']
    for change in [dict(password='secret'),dict(createdAt='2025-01-01T00:00:00'),dict(analysis={'score':True})]:
        with pytest.raises(ValidationError):m.parse_import_row(value|change)


def test_legacy_snapshot_has_no_fabricated_server_metadata():
    m=contracts()
    value=m.LegacyAnalysisSnapshot(vacancy=DATA['vacancy'])
    wire=value.model_dump(mode='json')
    assert wire['profileRevision'] is None and wire['profile'] is None and wire['locale'] is None
    assert wire['promptVersion'] is None and wire['policyVersion'] is None
    assert wire['evidenceProvenance']=='unverified_legacy'
    assert decode_snapshot(wire)==value

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from fitcheck_backend.contracts.resources import ProfileUpdate, LegacyProfile
from fitcheck_backend.storage.payloads import encode_profile

DATA = json.loads((Path(__file__).parent / 'fixtures/domain.json').read_text())


def test_first_profile_requires_explicit_null_revision():
    value = ProfileUpdate.model_validate({'expectedRevision': None, 'profile': DATA['profile']})
    assert value.expected_revision is None
    assert value.model_dump()['expectedRevision'] is None
    with pytest.raises(ValidationError):
        ProfileUpdate.model_validate({'profile': DATA['profile']})


@pytest.mark.parametrize('revision', ['0', '-1', '01', '1.0', 'r1', '2147483648', 1, True])
def test_expected_revision_is_a_canonical_database_counter(revision):
    with pytest.raises(ValidationError):
        ProfileUpdate.model_validate({'expectedRevision': revision, 'profile': DATA['profile']})


def test_normalization_and_legacy_profile_use_same_storage_payload():
    legacy = LegacyProfile.model_validate({**DATA['profile'], 'desiredMonthlyIncome': 9000,
        'skills': [' React ', 'react', ' TypeScript '], 'specialization': ' Frontend developer '})
    assert encode_profile(legacy) == DATA['profile']

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from fitcheck_backend.contracts.domain import Vacancy
from fitcheck_backend.storage.payloads import encode_vacancy, decode_vacancy

DATA = json.loads((Path(__file__).parent / 'fixtures/domain.json').read_text())['vacancy']


def test_competition_and_provenance_survive_storage():
    payload = {**DATA, 'proposalCount': 248, 'averageBid': 500, 'averageBidCurrency': 'USD',
        'provenance': {'proposalCount': 'html', 'averageBid': 'html', 'title': 'json_ld'}}
    assert decode_vacancy(encode_vacancy(Vacancy.model_validate(payload))).model_dump() == payload


def test_unknown_competition_accepts_null_without_inventing_values():
    value = Vacancy.model_validate({**DATA, 'proposalCount': None, 'averageBid': None, 'averageBidCurrency': None})
    assert value.proposal_count is None and value.average_bid is None
    assert value.model_dump() == DATA


@pytest.mark.parametrize('field,value', [('proposalCount', True), ('proposalCount', -1),
    ('proposalCount', 0.5), ('averageBid', -1), ('averageBid', float('nan')),
    ('averageBidCurrency', 'GBP'), ('provenance', {'password': 'html'}),
    ('provenance', {'title': 'guessed'})])
def test_competition_values_and_provenance_are_bounded(field, value):
    with pytest.raises(ValidationError):
        Vacancy.model_validate({**DATA, field: value})


def test_legacy_vacancy_remains_byte_shape_compatible():
    assert Vacancy.model_validate(DATA).model_dump() == DATA

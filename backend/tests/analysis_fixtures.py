import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from fitcheck_backend.contracts.domain import FreelancerProfile, Vacancy, FitAnalysis

DATA = json.loads((Path(__file__).parent / 'fixtures/domain.json').read_text())


def input_value(*, profile=None, vacancy=None, locale='en', memory=None):
    from fitcheck_backend.analysis.types import AnalysisInput
    return AnalysisInput(FreelancerProfile.model_validate({**DATA['profile'], **(profile or {})}),
        Vacancy.model_validate({**DATA['vacancy'], **(vacancy or {})}), locale, memory or [])



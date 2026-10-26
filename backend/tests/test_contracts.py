import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from fitcheck_backend.contracts.domain import FreelancerProfile, Vacancy, FitAnalysis
from fitcheck_backend.contracts.resources import AnalysisStart, ProfileUpdate, LegacyImportRequest
from fitcheck_backend.contracts.jobs import JobState

DATA = json.loads((Path(__file__).parent / "fixtures/domain.json").read_text())


@pytest.mark.parametrize("model,key", [(FreelancerProfile,"profile"),(Vacancy,"vacancy"),(FitAnalysis,"analysis")])
def test_existing_domain_fixture_roundtrips(model, key):
    assert model.model_validate(DATA[key]).model_dump(mode="json", by_alias=True, exclude_none=True) == DATA[key]


@pytest.mark.parametrize("field,value", [
    ("desiredMonthlyIncome",1000),("preferredRate",True),("preferredRate",float("nan")),
    ("preferredRate",float("inf")),("preferredRate",-1),("preferredRate",100_000_001),
    ("experienceYears",61),("rateCurrency",None),("rateCurrency","GBP"),
    ("workFormats",["remote","remote"]),("skillLevels",{"React":"primary"}),
    ("skillLevels",{"python":"primary"}),("skills",[]),("skills",["x"]*51),
    ("specialization","x"*121),("englishLevel","native"),
])
def test_profile_rejects_invalid_public_input(field, value):
    with pytest.raises(ValidationError):
        FreelancerProfile.model_validate({**DATA["profile"], field:value})


@pytest.mark.parametrize("field,value", [("hourlyRateMax",100_001),("fixedBudgetMax",100_000_001),("clientRating",5.1),("clientSpend",10_000_000_001),("skills",["x"]*101),("title","x"*301),("description","x"*20_001),("url",None)])
def test_vacancy_limits(field,value):
    with pytest.raises(ValidationError):
        Vacancy.model_validate({**DATA["vacancy"],field:value})


@pytest.mark.parametrize("field,value", [("score",100.1),("score",True),("score",101),("strengths",["x"]*4),("risks",["x"]*4),("summary","x"*801)])
def test_analysis_limits(field,value):
    with pytest.raises(ValidationError):
        FitAnalysis.model_validate({**DATA["analysis"],field:value})


def test_trimming_and_optional_omission():
    profile = FreelancerProfile.model_validate({**DATA["profile"],"specialization":" Frontend ","skills":[" React ","TypeScript"]})
    assert profile.specialization == "Frontend"
    vacancy = Vacancy.model_validate(DATA["vacancy"])
    assert "hourlyRateMax" not in vacancy.model_dump(by_alias=True, exclude_none=True)


@pytest.mark.parametrize("kind", ["analysis","skill_suggestions"])
@pytest.mark.parametrize("status", ["queued","running","succeeded","failed"])
def test_job_state_types(kind,status):
    value = {"jobId":"job-1","type":kind,"status":status}
    if status == "succeeded":
        value.update({"analysisId":"analysis-1"} if kind == "analysis" else {"skills":["React"]})
        if kind == 'analysis':
            value['result'] = dict(analysisId='analysis-1',createdAt='2026-01-01T00:00:00Z',
                analysis=DATA['analysis'],applicationStatus='not_applied',snapshot=dict(profileRevision='1',
                    profile=DATA['profile'],vacancy=DATA['vacancy'],locale='en',promptVersion='prompt.v1',
                    schemaVersion='fitcheck.analysis.v1',policyVersion='policy.v1'))
    if status == "failed":
        value["error"] = {"code":"timeout","message":"Timed out","requestId":"req-1","details":[]}
    assert JobState.model_validate(value).model_dump(mode='json', by_alias=True, exclude_none=True) == value


@pytest.mark.parametrize("extra", [{"skills":["React"]},{"analysisId":"a","skills":["React"]},{"analysisId":"a","userId":"u"}])
def test_analysis_success_cannot_be_suggestions_or_extra(extra):
    with pytest.raises(ValidationError):
        JobState.model_validate({"jobId":"j","type":"analysis","status":"succeeded",**extra})


def test_suggestions_max_ten():
    with pytest.raises(ValidationError):
        JobState.model_validate({"jobId":"j","type":"skill_suggestions","status":"succeeded","skills":["x"]*11})


def test_account_analysis_server_owned_profile():
    value = {"mode":"account","vacancy":DATA["vacancy"],"profileRevision":"r1","locale":"en"}
    assert AnalysisStart.model_validate(value).model_dump(by_alias=True,exclude_none=True) == value
    for field, extra in [("profile",DATA["profile"]),("userId","other"),("memory",[])]:
        with pytest.raises(ValidationError):
            AnalysisStart.model_validate({**value,field:extra})
    guest = {"mode":"guest","vacancy":DATA["vacancy"],"profile":DATA["profile"],"locale":"ru"}
    assert AnalysisStart.model_validate(guest).root.mode == "guest"


def test_profile_revision_required():
    with pytest.raises(ValidationError):
        ProfileUpdate.model_validate({"profile":DATA["profile"]})
    assert ProfileUpdate.model_validate({"expectedRevision":"1","profile":DATA["profile"]}).expected_revision == "1"


def test_legacy_import_only_ignores_income():
    result = LegacyImportRequest.model_validate({"version":1,"source":"website_indexeddb_v1","sourceUserId":"local","profile":{**DATA["profile"],"desiredMonthlyIncome":9000},"history":[]})
    assert "desiredMonthlyIncome" not in result.model_dump_json(by_alias=True)
    with pytest.raises(ValidationError):
        LegacyImportRequest.model_validate({"version":1,"source":"website_indexeddb_v1","sourceUserId":"local","profile":DATA["profile"],"history":[],"password":"local"})


def test_import_preserves_existing_feedback_timestamp():
    entry = {"id":"h1","jobTitle":"Dashboard","score":85,"status":"GO","timestamp":"Today","createdAt":"2026-10-11T10:00:00Z","analysis":DATA["analysis"],"job":DATA["vacancy"],"feedback":{"correctedScore":75,"note":"Scope uncertain","createdAt":"2026-10-11T10:05:00Z"}}
    value = LegacyImportRequest.model_validate({"version":1,"source":"website_indexeddb_v1","sourceUserId":"local","history":[entry]})
    assert value.model_dump(mode="json",by_alias=True,exclude_none=True)["history"][0]["feedback"]["createdAt"] == "2026-10-11T10:05:00Z"


@pytest.mark.parametrize("model,key,field,value", [
    (FreelancerProfile,"profile","experienceYears",-1),
    (FreelancerProfile,"profile","skills",["x"*81]),
    (FreelancerProfile,"profile","specialization"," "),
    (FreelancerProfile,"profile","workFormats",[]),
    (Vacancy,"vacancy","id","x"*201),
    (Vacancy,"vacancy","hourlyRateMin",-1),
    (Vacancy,"vacancy","fixedBudget",-1),
    (Vacancy,"vacancy","experienceLevel","x"*101),
    (Vacancy,"vacancy","postedAgo","x"*101),
    (Vacancy,"vacancy","url","https://example.com/"+"x"*2000),
    (FitAnalysis,"analysis","label","x"*81),
    (FitAnalysis,"analysis","strengths",["x"*241]),
    (FitAnalysis,"analysis","risks",["x"*241]),
    (FitAnalysis,"analysis","breakdown",{"skills":101,"experience":0,"rate":0,"english":0,"requirements":0}),
])
def test_remaining_domain_boundaries(model,key,field,value):
    with pytest.raises(ValidationError):
        model.model_validate({**DATA[key],field:value})


def test_default_serialization_omits_absent_but_preserves_nullable_fields():
    from fitcheck_backend.contracts.resources import HistoryPage
    vacancy = Vacancy.model_validate(DATA['vacancy'])
    serialized = vacancy.model_dump(mode='json')
    assert 'url' not in serialized
    assert 'hourlyRateMax' not in serialized
    assert HistoryPage(items=[], nextCursor=None, hasMore=False).model_dump(mode='json') == {'items': [], 'nextCursor': None, 'hasMore': False}


def test_nested_http_response_omits_absent_optional_fields():
    from fastapi.testclient import TestClient
    from fitcheck_backend.api.app import create_app
    from fitcheck_backend.config import Settings
    from fitcheck_backend.contracts.resources import ExtractionResponse
    app = create_app(Settings())
    @app.get('/fixture', response_model=ExtractionResponse)
    async def fixture():
        return ExtractionResponse(vacancy=Vacancy.model_validate(DATA['vacancy']))
    response = TestClient(app).get('/fixture')
    assert response.status_code == 200
    assert response.json() == {'vacancy': DATA['vacancy']}

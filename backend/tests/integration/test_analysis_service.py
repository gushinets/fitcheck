import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from test_profile_http import profile_http,save,DATA
from analysis_fixtures import input_value
from llm_fakes import Adapter
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import ProviderCall,AnalysisRecord,VacancyRecord,AnalysisAnnotation,Job
from fitcheck_backend.contracts.domain import Vacancy

pytestmark=pytest.mark.integration


def model_reply(content):
    from fitcheck_backend.llm.types import ProviderReply
    return ProviderReply(json.dumps(content),12,4,None,None)


def service(engine, values):
    from fitcheck_backend.analysis.service import AnalysisService
    from fitcheck_backend.analysis.executor import AnalysisExecutor
    from fitcheck_backend.llm.gateway import ProviderGateway
    from fitcheck_backend.llm.policy import analysis_policy
    from fitcheck_backend.storage.provider_repository import ProviderLedger
    adapter=Adapter(values)
    return AnalysisService(engine,AnalysisExecutor(ProviderGateway(adapter,ProviderLedger(engine))),analysis_policy()),adapter


def test_service_uses_revision_memory_and_corrected_vacancy_without_publishing(profile_http):
    a,client,_,issued,headers=profile_http
    assert save(client,headers).status_code==200
    assert save(client,headers,'1',preferredRate=999).status_code==200
    owner=issued.principal.owner_id
    snapshot=dict(profileRevision='1',profile=DATA['profile'],vacancy=DATA['vacancy'],locale='en',
        promptVersion='old',schemaVersion='fitcheck.analysis.v1',policyVersion='old')
    with unit_of_work(a.engine) as s:
        vacancy=VacancyRecord(owner_id=owner,vacancy=DATA['vacancy']);s.add(vacancy);s.flush()
        row=AnalysisRecord(owner_id=owner,vacancy_id=vacancy.id,snapshot=snapshot,analysis=DATA['analysis'])
        s.add(row);s.flush()
        from fitcheck_backend.storage.base import utcnow
        s.add(AnalysisAnnotation(owner_id=owner,analysis_id=row.id,corrected_score=20,note='Prefer small projects',feedback_created_at=utcnow()))
    generate={**DATA['analysis'],'strengths':['skill:0']}
    audit={'supported':True,'unsupportedClaims':[]}
    application,adapter=service(a.engine,[model_reply(generate),model_reply(audit)]*2)
    corrected=Vacancy.model_validate({**DATA['vacancy'],'description':'User corrected the React dashboard requirements.'})
    async def run():
        first=await application.analyze(owner_id=owner,profile_revision=1,vacancy=corrected,locale='en')
        second=await application.analyze(owner_id=owner,profile_revision=1,vacancy=corrected,locale='en')
        assert first==second
        return first
    result=asyncio.run(run())
    assert result.snapshot.profile.preferred_rate==50 and result.snapshot.profile_revision=='1'
    assert result.snapshot.vacancy==corrected and result.analysis.verdict_threshold==70
    assert result.snapshot.prompt_version=='fitcheck.analysis.prompt.v2'
    assert result.snapshot.policy_version=='fitcheck.llm.policy.v2'
    request=next(m['content'] for m in adapter.calls[0]['messages'] if m['role']=='user')
    assert 'Prefer small projects' in request and 'corrected_score' in request
    with unit_of_work(a.engine) as s:
        calls=s.scalars(select(ProviderCall).order_by(ProviderCall.created_at)).all()
        assert len(calls)==4 and all(c.state=='succeeded' for c in calls)
        assert all(c.input_tokens==12 and c.owner_id==owner for c in calls)
        assert [c.schema_version for c in calls]==['fitcheck.analysis.v1','fitcheck.grounding.v1']*2
        assert len({c.request_key.split(':')[0] for c in calls})==2
        assert s.scalar(select(func.count()).select_from(AnalysisRecord))==1
        assert s.scalar(select(func.count()).select_from(Job))==0


@pytest.mark.parametrize('bad', ['missing_revision','foreign_job','wrong_job_type','missing_owner'])
def test_service_rejects_missing_or_foreign_context_before_provider(profile_http,bad,storage_factory):
    a,client,_,issued,headers=profile_http
    save(client,headers)
    owner=issued.principal.owner_id
    application,adapter=service(a.engine,[])
    kwargs=dict(owner_id=owner,profile_revision=1,vacancy=input_value().vacancy,locale='en')
    if bad=='missing_revision': kwargs['profile_revision']=99
    if bad=='missing_owner': kwargs['owner_id']=uuid4()
    if bad=='foreign_job':
        with unit_of_work(a.engine) as s:
            _,_,job,*_=storage_factory(s)
        kwargs['job_id']=job.id
    if bad=='wrong_job_type':
        with unit_of_work(a.engine) as s:
            job=Job(owner_id=owner,type='skill_suggestions',input={'sample':True},idempotency_key='wrong-kind',request_hash='a'*64)
            s.add(job);s.flush()
        kwargs['job_id']=job.id
    with pytest.raises(ValueError): asyncio.run(application.analyze(**kwargs))
    assert adapter.calls==[]
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(ProviderCall))==0


def test_failed_output_keeps_ledger_and_does_not_publish(profile_http):
    from fitcheck_backend.llm.errors import LlmError
    a,client,_,issued,headers=profile_http
    save(client,headers)
    application,_=service(a.engine,[model_reply({'bad':'output'})]*2)
    with pytest.raises(LlmError) as result:
        asyncio.run(application.analyze(owner_id=issued.principal.owner_id,profile_revision=1,
            vacancy=input_value().vacancy,locale='en'))
    assert result.value.code=='invalid_output'
    with unit_of_work(a.engine) as s:
        calls=s.scalars(select(ProviderCall)).all()
        assert len(calls)==2 and all(c.state=='failed' and c.input_tokens==12 for c in calls)
        assert s.scalar(select(func.count()).select_from(AnalysisRecord))==0


def test_overall_deadline_includes_context_reads(profile_http,monkeypatch):
    from fitcheck_backend.llm.types import OperationContext,CallBudget
    from fitcheck_backend.llm.errors import LlmError
    a,client,_,issued,headers=profile_http
    save(client,headers)
    application,adapter=service(a.engine,[model_reply({**DATA['analysis'],'strengths':[]}),model_reply({'supported':True,'unsupportedClaims':[]})])
    now=[0.0]
    def context(owner,job,policy):
        return OperationContext(owner,job,uuid4(),policy,CallBudget(8,now[0]+120,lambda:now[0]))
    def slow_memory(*args):
        now[0]+=121
        return []
    monkeypatch.setattr('fitcheck_backend.analysis.service.operation_context',context)
    monkeypatch.setattr('fitcheck_backend.analysis.service.get_calibration',slow_memory)
    with pytest.raises(LlmError) as result:
        asyncio.run(application.analyze(owner_id=issued.principal.owner_id,profile_revision=1,
            vacancy=input_value().vacancy,locale='en'))
    assert result.value.code=='timeout' and adapter.calls==[]

import asyncio
import json
from uuid import uuid4
from types import SimpleNamespace
from dataclasses import replace
import pytest
from analysis_fixtures import DATA
from llm_fakes import components
from fitcheck_backend.jobs.types import JobLease
from fitcheck_backend.jobs.envelope import execution_versions
from fitcheck_backend.jobs.errors import JobError
from fitcheck_backend.llm.types import ProviderReply


def runtime(values):
    from fitcheck_backend.analysis.service import AnalysisService
    from fitcheck_backend.analysis.executor import AnalysisExecutor
    from fitcheck_backend.skill_suggestions.service import SkillSuggestionService
    from fitcheck_backend.skill_suggestions.executor import SuggestionExecutor
    from fitcheck_backend.llm.policy import analysis_policy, suggestion_policy
    gateway, _, ledger, adapter = components(values)
    return SimpleNamespace(analysis=AnalysisService(None, AnalysisExecutor(gateway), analysis_policy()),
        suggestions=SkillSuggestionService(None, SuggestionExecutor(gateway), suggestion_policy())), ledger, adapter


def lease(kind='analysis'):
    from copy import deepcopy
    req = dict(mode='account',vacancy=DATA['vacancy'],profileRevision='1',locale='en')
    payload = dict(envelopeVersion=1, request=req, profile=DATA['profile'],
        memory=[dict(jobTitle='Prior job', predictedScore=80, correctedScore=20, note='Small tasks')],
        versions=execution_versions(kind).model_dump(mode='json'))
    if kind != 'analysis':
        payload = dict(envelopeVersion=1, request=dict(specialization='React',locale='en'), versions=execution_versions(kind).model_dump(mode='json'))
    return JobLease(uuid4(),uuid4(),kind,uuid4(),1,deepcopy(payload))


def replies():
    return [ProviderReply(json.dumps({**DATA['analysis'],'strengths':['skill:0']}),12,4,None,None),
        ProviderReply('{"supported":true,"unsupportedClaims":[]}',8,2,None,None)]


def test_execution_uses_admitted_memory_profile_and_versions():
    from fitcheck_backend.jobs.execution import FrozenJobExecutor
    value, ledger, adapter = runtime(replies())
    job = lease()
    result = asyncio.run(FrozenJobExecutor(value).execute(job))
    assert result.snapshot.profile_revision == '1' and result.snapshot.profile.preferred_rate == 50
    assert result.snapshot.prompt_version == 'fitcheck.analysis.prompt.v3'
    assert result.analysis.verdict_threshold == 70
    assert 'Small tasks' in json.dumps(adapter.calls[0]['messages'])
    assert all(row['attempt'].execution_token == job.execution_token for row in ledger.rows.values())
    assert len({row['attempt'].operation_id for row in ledger.rows.values()}) == 1


@pytest.mark.parametrize('bad', ['version','legacy','old_prompt','old_audit'])
def test_unsupported_version_spends_zero_calls(bad):
    from fitcheck_backend.jobs.execution import FrozenJobExecutor
    value, _, adapter = runtime([])
    job = lease()
    if bad == 'version': job.input['versions']['policyVersion'] = 'unknown'
    elif bad == 'legacy': job = replace(job,input=job.input['request'])
    elif bad == 'old_prompt': job.input['versions']['promptVersion'] = 'fitcheck.analysis.prompt.v2'
    else: job.input['versions']['auditPromptVersion'] = 'fitcheck.analysis.audit.v2'
    with pytest.raises(JobError): asyncio.run(FrozenJobExecutor(value).execute(job))
    assert adapter.calls == []


@pytest.mark.parametrize('manual', [False, True])
def test_durable_job_keeps_competition_in_report_and_original_snapshot(manual):
    from fitcheck_backend.jobs.execution import FrozenJobExecutor
    value, _, _ = runtime(replies())
    job = lease()
    vacancy = job.input['request']['vacancy']
    if manual:
        vacancy['description'] += '\nProposals: 248\nAverage bid: $500 USD'
    else:
        vacancy.update(proposalCount=248, averageBid=500, averageBidCurrency='USD')
    result = asyncio.run(FrozenJobExecutor(value).execute(job))
    assert '248' in result.analysis.risks[0] and '500 USD' in result.analysis.summary
    assert result.snapshot.vacancy.model_dump(mode='json') == vacancy


def test_execution_deadline_is_shared_by_generation_and_audit(monkeypatch):
    from fitcheck_backend.jobs.execution import FrozenJobExecutor
    from fitcheck_backend.llm.types import OperationContext, CallBudget
    from fitcheck_backend.llm.errors import LlmError
    value, ledger, adapter = runtime(replies())
    now = [0.0]
    def context(owner,job,policy,execution_token=None):
        return OperationContext(owner,job,uuid4(),policy,CallBudget(8,120,lambda:now[0]),execution_token)
    original = adapter.complete
    async def slow(**kwargs):
        response = await original(**kwargs)
        now[0] = 121
        return response
    monkeypatch.setattr('fitcheck_backend.jobs.execution.operation_context',context)
    adapter.complete = slow
    with pytest.raises(LlmError): asyncio.run(FrozenJobExecutor(value).execute(lease()))
    assert len(ledger.rows) == 1


def test_suggestions_use_frozen_request():
    from fitcheck_backend.jobs.execution import FrozenJobExecutor
    value, ledger, adapter = runtime([ProviderReply('{"skills":["React","TypeScript"]}',12,4,None,None)])
    assert asyncio.run(FrozenJobExecutor(value).execute(lease('skill_suggestions'))) == ['React','TypeScript']
    assert 'React' in json.dumps(adapter.calls[0]['messages'])

import asyncio
import json
import pytest
from sqlalchemy import select
from test_profile_http import profile_http
from llm_fakes import Adapter
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import ProviderCall

pytestmark=pytest.mark.integration


def test_suggestion_service_uses_owner_and_releases_database_before_provider(profile_http):
    from fitcheck_backend.skill_suggestions.service import SkillSuggestionService
    from fitcheck_backend.skill_suggestions.executor import SuggestionExecutor
    from fitcheck_backend.llm.gateway import ProviderGateway
    from fitcheck_backend.llm.policy import suggestion_policy
    from fitcheck_backend.llm.types import ProviderReply
    from fitcheck_backend.storage.provider_repository import ProviderLedger
    a,_,_,issued,_=profile_http
    adapter=Adapter([ProviderReply('{"skills":[" Python ","python","FastAPI"]}',12,4,None,None)])
    original=adapter.complete
    async def fetch(**kwargs):
        assert a.engine.pool.checkedout()==0
        request=next(m['content'] for m in kwargs['messages'] if m['role']=='user')
        assert json.loads(request)=={'specialization':'Backend developer'}
        return await original(**kwargs)
    adapter.complete=fetch
    application=SkillSuggestionService(a.engine,SuggestionExecutor(ProviderGateway(adapter,ProviderLedger(a.engine))),suggestion_policy())
    result=asyncio.run(application.suggest(owner_id=issued.principal.owner_id,specialization=' Backend developer ',locale='en'))
    assert result==['Python','FastAPI']
    with unit_of_work(a.engine) as s:
        row=s.scalar(select(ProviderCall))
        assert row.owner_id==issued.principal.owner_id and row.operation=='skill_suggestions'
        assert row.prompt_version=='fitcheck.skills.prompt.v1' and row.schema_version=='fitcheck.skills.v1'


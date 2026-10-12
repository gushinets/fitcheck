from dataclasses import replace
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from fitcheck_backend.auth.access import load_owned, require_verified, AccountDeletionService
from fitcheck_backend.auth.errors import AuthError
from fitcheck_backend.auth.types import Principal
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Owner, User, Profile, ProfileRevision, Job, AnalysisRecord, AnalysisAnnotation, ImportEntry, ProviderCall, Guest, AuthSession

pytestmark=pytest.mark.integration


def test_two_accounts_cannot_load_each_others_graph(engine,storage_factory):
    with unit_of_work(engine) as s:
        graphs=[storage_factory(s),storage_factory(s)]
        for o,u,j,v,report,annotation in graphs:
            s.add(ProfileRevision(owner_id=o.id,revision=1,profile={'sample':True}))
            s.add(Profile(owner_id=o.id,current_revision=1))
            entry=ImportEntry(owner_id=o.id,external_id='entry',content_hash='a'*64,analysis_id=report.id)
            s.add(entry);s.flush()
            principal=Principal(u.id,o.id,uuid4(),'web',u.normalized_email,True)
            resources=[(Profile,o.id),(Job,j.id),(AnalysisRecord,report.id),(AnalysisAnnotation,report.id),(ImportEntry,entry.id)]
            for model,id in resources:assert load_owned(s,model,id,principal).owner_id==o.id
            other_owner=graphs[1][0] if o.id==graphs[0][0].id else graphs[0][0]
            forged=replace(principal,owner_id=other_owner.id)
            for model,id in resources:
                with pytest.raises(AuthError) as exc:load_owned(s,model,id,forged)
                assert exc.value.code=='not_found'
            with pytest.raises(AuthError):require_verified(replace(principal,email_verified=False))


def test_delete_reauth_cascades_and_anonymizes(auth_components,storage_factory):
    a=auth_components
    issued=a.service.register('a@example.com','correct horse battery','192.0.2.1')
    with unit_of_work(a.engine) as s:
        owner,guest,job,vacancy,analysis,annotation=storage_factory(s,kind='guest')
        guest.claimed_by_user_id=issued.principal.user_id;guest.claimed_at=a.now[0]
        s.add(ProviderCall(owner_id=issued.principal.owner_id,provider='test',model='test',operation='analysis',attempt=1,state='succeeded',input_tokens=1,output_tokens=1,cost='0.01',currency='USD'))
    service=AccountDeletionService(a.engine,a.passwords,a.limiter,a.clock)
    with pytest.raises(AuthError):service.delete(issued.principal,'wrong')
    assert a.service.resolve(issued.token,'web').user_id==issued.principal.user_id
    service.delete(issued.principal,'correct horse battery')
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(User))==0
        assert s.scalar(select(func.count()).select_from(Guest))==0
        assert s.scalar(select(func.count()).select_from(AuthSession))==0
        ledger=s.scalar(select(ProviderCall))
        assert ledger.owner_id is None and ledger.job_id is None and ledger.request_key is None
    with pytest.raises(AuthError):a.service.resolve(issued.token,'web')

from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from test_profile_http import profile_http,WEB
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job

pytestmark=pytest.mark.integration


def guest(c):
    c.app.state.settings.guest_enabled=True
    boot=c.get('/v1/auth/csrf',headers={'Origin':WEB})
    result=c.post('/v1/guest-sessions',json={},headers={'Origin':WEB,'X-CSRF-Token':boot.json()['csrfToken']})
    assert result.status_code==201,result.text
    return result.json(),c.cookies.get('__Host-fitcheck_guest')


def queued(a,owner):
    with unit_of_work(a.engine) as s:
        job=Job(owner_id=owner,type='skill_suggestions',input={},idempotency_key='q',request_hash='a'*64)
        s.add(job);s.flush();return job.id


def test_guest_reuse_keeps_absolute_expiry(profile_http):
    a,c,r,_,_=profile_http
    value,token=guest(c)
    identity=r.guests.resolve(token)
    assert identity.expires_at==a.clock()+timedelta(days=1)
    a.now[0]+=timedelta(hours=1)
    second,second_token=guest(c)
    assert second_token==token and second['expiresAt']==value['expiresAt'] and value['demoLimit']==1
    from fitcheck_backend.storage.guest_access import GuestSessionRow
    with unit_of_work(a.engine) as s:
        stored=s.get(GuestSessionRow,identity.session_id)
        assert stored.token_digest!=token and token not in repr(stored.__dict__)


def test_session_creation_and_reads_require_correct_proofs(profile_http):
    a,c,r,_,h=profile_http
    c.app.state.settings.guest_enabled=True
    assert c.post('/v1/guest-sessions',json={},headers={'Origin':WEB}).status_code==403
    _,token=guest(c)
    assert c.get('/v1/jobs/'+str(uuid4()),params={'mode':'guest'}).status_code==404
    assert c.get('/v1/jobs/'+str(uuid4()),params={'mode':'guest'},headers={'Cookie':'__Host-fitcheck_guest=forged'}).status_code==401
    a.now[0]+=timedelta(days=1)
    assert c.get('/v1/jobs/'+str(uuid4()),params={'mode':'guest'}).status_code==401


def test_selected_invalid_account_has_no_guest_fallback(profile_http):
    a,c,r,_,_=profile_http
    _,token=guest(c)
    identifier=queued(a,r.guests.resolve(token).owner_id)
    c.cookies.set('__Host-fitcheck_session','invalid')
    path='/v1/jobs/'+str(identifier)
    assert c.get(path).status_code==401
    assert c.get(path,params={'mode':'account'}).status_code==401
    assert c.get(path,params={'mode':'guest'}).status_code==200
    assert c.get('/v1/history',params={'mode':'guest'}).status_code==401


def test_foreign_guest_job_returns_404(profile_http):
    a,c,r,_,_=profile_http
    _,token=guest(c)
    identifier=queued(a,r.guests.resolve(token).owner_id)
    c.cookies.delete('__Host-fitcheck_guest');guest(c)
    response=c.get('/v1/jobs/'+str(identifier),params={'mode':'guest'})
    assert response.status_code==404 and str(identifier) not in response.text


def test_revoked_claimed_sessions_and_account_only_routes(profile_http):
    from fitcheck_backend.storage.guest_access import GuestSessionRow
    from fitcheck_backend.storage.models import Guest
    a,c,r,issued,h=profile_http
    _,token=guest(c);identity=r.guests.resolve(token)
    with unit_of_work(a.engine) as s:s.get(GuestSessionRow,identity.session_id).revoked_at=a.clock()
    assert c.get('/v1/jobs/'+str(uuid4()),params={'mode':'guest'}).status_code==401
    c.cookies.delete('__Host-fitcheck_guest');_,token=guest(c);identity=r.guests.resolve(token)
    with unit_of_work(a.engine) as s:
        row=s.scalar(select(Guest).where(Guest.owner_id==identity.owner_id))
        row.claimed_by_user_id=issued.principal.user_id;row.claimed_at=a.clock()
    assert c.get('/v1/jobs/'+str(uuid4()),params={'mode':'guest'}).status_code==401
    c.cookies.delete('__Host-fitcheck_session')
    assert c.get('/v1/history').status_code==401
    assert c.put('/v1/analyses/'+str(uuid4())+'/feedback',json={'correctedScore':10},headers=h).status_code==401

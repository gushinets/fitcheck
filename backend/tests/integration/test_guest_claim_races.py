from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import select,func
from test_guest_claim_http import ready,profile_http
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import User,GuestClaimReceipt,Owner,ProfileRevision
from fitcheck_backend.guests.sessions import guest_cookie_name
from fitcheck_backend.auth.errors import AuthError
from fitcheck_backend.jobs.errors import JobError
from fitcheck_backend.auth.access import AccountDeletionService

pytestmark=pytest.mark.integration


def test_two_accounts_claim_one_guest(profile_http):
    a,c,r,h,_=ready(profile_http)
    second=a.service.register('other@example.com','correct horse battery','192.0.2.2')
    with unit_of_work(a.engine) as s:s.get(User,second.principal.user_id).email_verified_at=a.clock()
    accounts=[r.auth.session(profile_http[3].token).principal,a.service.session(second.token).principal]
    identity=r.guests.resolve(c.cookies.get(guest_cookie_name(r.settings)))
    barrier=Barrier(2)
    def claim(principal):
        barrier.wait(timeout=10)
        try:r.claims.claim(account=principal,guest=identity,idempotency_key='claim');return 'ok'
        except (AuthError,JobError):return 'denied'
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(claim,accounts))==['denied','ok']
    with unit_of_work(a.engine) as s:assert s.scalar(select(func.count()).select_from(GuestClaimReceipt))==1


def test_claim_delete_race_cannot_resurrect_data(profile_http):
    a,c,r,h,_=ready(profile_http)
    principal=r.auth.session(profile_http[3].token).principal
    identity=r.guests.resolve(c.cookies.get(guest_cookie_name(r.settings)));barrier=Barrier(2)
    def claim():
        barrier.wait(timeout=10)
        try:r.claims.claim(account=principal,guest=identity,idempotency_key='claim');return 'ok'
        except (AuthError,JobError):return 'denied'
    def erase():
        barrier.wait(timeout=10)
        AccountDeletionService(a.engine,a.passwords,a.limiter,a.clock).delete(principal,'correct horse battery')
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(claim);second=pool.submit(erase)
        first.result(timeout=15);second.result(timeout=15)
    with unit_of_work(a.engine) as s:
        assert s.get(Owner,principal.owner_id) is None
        assert s.scalar(select(GuestClaimReceipt)) is None
        assert s.scalar(select(ProfileRevision).where(ProfileRevision.owner_id==principal.owner_id)) is None


def test_two_claims_into_one_empty_account_import_one_revision(profile_http):
    from fitcheck_backend.storage.profile_repository import create_profile,get_profile
    from fitcheck_backend.contracts.domain import FreelancerProfile
    from test_profile_http import DATA
    a,c,r,h,_=ready(profile_http)
    first=r.guests.resolve(c.cookies.get(guest_cookie_name(r.settings)))
    second=r.guests.issue_or_reuse(None,client_ip='192.0.2.8').identity
    with unit_of_work(a.engine) as s:create_profile(s,second.owner_id,FreelancerProfile.model_validate({**DATA['profile'],'preferredRate':99}))
    principal=r.auth.session(profile_http[3].token).principal;barrier=Barrier(2)
    def claim(identity):
        barrier.wait(timeout=10)
        return r.claims.claim(account=principal,guest=identity,idempotency_key=str(identity.owner_id))
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(claim,[first,second]))
    assert sorted(x.profile_imported for x in results)==[False,True]
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(ProfileRevision).where(ProfileRevision.owner_id==principal.owner_id))==1
        assert get_profile(s,principal.owner_id).revision=='1'
        assert s.scalar(select(func.count()).select_from(GuestClaimReceipt))==2


def test_claim_racing_completion_has_one_complete_owner_graph(profile_http):
    from test_guest_jobs_http import prepare
    from test_profile_http import DATA
    from fitcheck_backend.storage.job_queue import JobQueue
    from fitcheck_backend.storage.job_publication import JobPublication
    from fitcheck_backend.jobs.envelope import decode_envelope
    from fitcheck_backend.analysis.service import AnalysisResult
    from fitcheck_backend.contracts.domain import FitAnalysis
    from fitcheck_backend.contracts.resources import AnalysisSnapshot
    from fitcheck_backend.storage.models import AnalysisRecord,Job,VacancyRecord
    a,c,r,h,body=prepare(profile_http)
    assert c.post('/v1/analysis-jobs',json=body,headers=h).status_code==202
    identity=r.guests.resolve(c.cookies.get(guest_cookie_name(r.settings)))
    principal=r.auth.session(profile_http[3].token).principal
    lease=JobQueue(a.engine).claim();e=decode_envelope('analysis',lease.input)
    snapshot=AnalysisSnapshot(profileRevision=e.profile_revision,profile=e.profile,vacancy=e.vacancy,locale=e.locale,promptVersion=e.versions.prompt_version,schemaVersion=e.versions.schema_version,policyVersion=e.versions.policy_version)
    barrier=Barrier(2)
    def publish():
        barrier.wait(timeout=10)
        return JobPublication(a.engine).succeed_analysis(lease,AnalysisResult(FitAnalysis.model_validate(DATA['analysis']),snapshot))
    def claim():
        barrier.wait(timeout=10)
        try:return r.claims.claim(account=principal,guest=identity,idempotency_key='race')
        except JobError as error:assert error.code=='conflict'
    with ThreadPoolExecutor(2) as pool:
        done=pool.submit(publish);claimed=pool.submit(claim)
        identifier=done.result(timeout=10);claimed.result(timeout=10)
    result=r.claims.claim(account=principal,guest=identity,idempotency_key='race')
    assert result.claimed_count==1
    with unit_of_work(a.engine) as s:
        analysis=s.get(AnalysisRecord,identifier)
        assert analysis.owner_id==s.get(Job,lease.job_id).owner_id==s.get(VacancyRecord,analysis.vacancy_id).owner_id==principal.owner_id

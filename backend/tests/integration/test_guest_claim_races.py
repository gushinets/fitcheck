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

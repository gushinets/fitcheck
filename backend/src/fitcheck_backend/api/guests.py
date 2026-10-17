from fastapi import APIRouter,Depends,Request
from fastapi.responses import JSONResponse
from ..contracts.guests import GuestSession
from ..contracts.openapi import ERRORS,SECURITY
from ..auth.crypto import cookie_options
from ..auth.errors import AuthError
from ..guests.sessions import guest_cookie_name
from .errors import ErrorEnvelope
from .dependencies import required_runtime,validate_bootstrap,client_ip

router=APIRouter(dependencies=[Depends(required_runtime)],responses={s:{'model':ErrorEnvelope,'description':c} for s,c in ERRORS.items()})


@router.post('/v1/guest-sessions',status_code=201,response_model=GuestSession,operation_id='createGuestSession',
    openapi_extra={'x-fitcheck-owner-task':'ANY-651','security':SECURITY['public'],
        'x-fitcheck-cookie-mutation':{'originRequired':True,'csrfHeader':'X-CSRF-Token'}})
def create_guest(request: Request):
    validate_bootstrap(request)
    runtime=required_runtime(request)
    if not runtime.settings.guest_enabled: raise AuthError('service_unavailable')
    issued=runtime.guests.issue_or_reuse(request.cookies.get(guest_cookie_name(runtime.settings)),client_ip=client_ip(request))
    response=JSONResponse(GuestSession(csrfToken=issued.csrf_token,expiresAt=issued.identity.expires_at,
        demoLimit=runtime.quota_policy.guest.analysis).model_dump(mode='json'),status_code=201)
    ttl=max(0,int((issued.identity.expires_at-runtime.clock()).total_seconds()))
    response.set_cookie(guest_cookie_name(runtime.settings),issued.token,max_age=ttl,**cookie_options(runtime.settings))
    return response


from ..contracts.guests import GuestClaimResult
from ..jobs.errors import JobError
from .jobs import idempotency
from .dependencies import verified_principal,validate_account_mutation
import hmac


def claim_proofs(request: Request,account=Depends(verified_principal)):
    validate_account_mutation(request,account)
    runtime=required_runtime(request)
    token=request.cookies.get(guest_cookie_name(runtime.settings),'')
    identity=runtime.guests.resolve(token,allow_claim_receipt=True)
    values=request.headers.getlist('x-guest-csrf-token')
    if len(values)!=1 or not hmac.compare_digest(values[0],runtime.guests.csrf(token)):
        raise AuthError('forbidden')
    return account,identity


@router.post('/v1/guest-claims',response_model=GuestClaimResult,operation_id='claimGuestData',
    openapi_extra={'x-fitcheck-owner-task':'ANY-651','security':SECURITY['claim'],
        'x-fitcheck-cookie-mutation':{'originRequired':True,'csrfHeader':'X-CSRF-Token','guestCsrfHeader':'X-Guest-CSRF-Token'},
        'parameters':[{'name':'Origin','in':'header','required':True,'schema':{'type':'string'}},
            {'name':'X-CSRF-Token','in':'header','required':True,'schema':{'type':'string'}},
            {'name':'X-Guest-CSRF-Token','in':'header','required':True,'schema':{'type':'string'}}]})
async def claim_guest(request: Request,proofs=Depends(claim_proofs),key=Depends(idempotency)):
    if await request.body():
        try:payload=await request.json()
        except ValueError:raise JobError('invalid_request') from None
        if payload!={}:raise JobError('invalid_request')
    runtime=required_runtime(request)
    account,identity=proofs
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(runtime.claims.claim,account=account,guest=identity,idempotency_key=key)

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

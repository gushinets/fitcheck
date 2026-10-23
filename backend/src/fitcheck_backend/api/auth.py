from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from ..contracts import resources as r
from ..contracts.openapi import ERRORS, SECURITY
from .errors import ErrorEnvelope
from .dependencies import required_runtime, account_principal, web_principal, client_ip, validate_web_origin, validate_bootstrap, validate_account_mutation
from ..auth.crypto import cookie_name, cookie_options
from ..metrics.identity import visitor_context

router = APIRouter(dependencies=[Depends(required_runtime)], responses={status: {'model': ErrorEnvelope, 'description': code} for status, code in ERRORS.items()})


def metadata(access, *, csrf=False, origin=False):
    value = {'x-fitcheck-owner-task': 'ANY-645', 'x-fitcheck-implementation': 'implemented', 'security': SECURITY[access]}
    if origin:
        value['parameters'] = [{'name':'Origin','in':'header','required':True,'schema':{'type':'string'}}]
    if csrf:
        value.setdefault('parameters', []).append({'name':'X-CSRF-Token','in':'header','required':access!='account','schema':{'type':'string'}})
        value['x-fitcheck-cookie-mutation'] = {'originRequired': True, 'csrfHeader': 'X-CSRF-Token'}
    return value


def user_resource(principal):
    return r.UserResource(id=str(principal.user_id), email=principal.email, emailVerified=principal.email_verified)


def web_session_response(request, issued, status):
    response = JSONResponse(r.SessionResource(user=user_resource(issued.principal), csrfToken=issued.csrf_token).model_dump(by_alias=True), status_code=status)
    settings = request.app.state.settings
    response.set_cookie(cookie_name(settings), issued.token, max_age=604800, **cookie_options(settings))
    response.delete_cookie(cookie_name(settings, bootstrap=True), **cookie_options(settings))
    return response


@router.get('/v1/auth/csrf', response_model=r.CsrfResource, operation_id='getAuthCsrf', openapi_extra=metadata('public', origin=True))
def bootstrap(request: Request):
    validate_web_origin(request)
    runtime = required_runtime(request)
    runtime.limiter.enforce('bootstrap', {'ip': client_ip(request)})
    cookie, csrf = runtime.crypto.issue_bootstrap()
    response = JSONResponse(r.CsrfResource(csrfToken=csrf).model_dump(by_alias=True))
    response.set_cookie(cookie_name(runtime.settings, bootstrap=True), cookie, max_age=900, **cookie_options(runtime.settings))
    return response


@router.post('/v1/auth/register', response_model=r.SessionResource, status_code=201, operation_id='register', openapi_extra=metadata('public', csrf=True, origin=True))
def register(body: r.RegistrationCredentials, request: Request):
    validate_bootstrap(request)
    runtime = required_runtime(request)
    context = visitor_context(request)
    issued = runtime.auth.register(body.email, body.password, client_ip(request), old_session_token=request.cookies.get(cookie_name(runtime.settings)))
    runtime.identity.auth(context,issued,"registered")
    return web_session_response(request, issued, 201)


@router.post('/v1/auth/login', response_model=r.SessionResource, operation_id='login', openapi_extra=metadata('public', csrf=True, origin=True))
def login(body: r.LoginCredentials, request: Request):
    validate_bootstrap(request)
    runtime = required_runtime(request)
    context = visitor_context(request)
    issued = runtime.auth.login(body.email, body.password, client_ip(request), old_session_token=request.cookies.get(cookie_name(runtime.settings)))
    runtime.identity.auth(context,issued,"login")
    return web_session_response(request, issued, 200)


@router.get('/v1/auth/session', response_model=r.SessionResource, operation_id='getAuthSession', openapi_extra=metadata('web'))
def session(request: Request, principal=Depends(web_principal)):
    runtime = required_runtime(request)
    issued = runtime.auth.session(request.cookies[cookie_name(runtime.settings)])
    return r.SessionResource(user=user_resource(issued.principal), csrfToken=issued.csrf_token)


@router.get('/v1/me', response_model=r.UserResource, operation_id='getMe', openapi_extra=metadata('account'))
def me(principal=Depends(account_principal)):
    return user_resource(principal)


@router.post('/v1/auth/logout', status_code=204, operation_id='logout', openapi_extra=metadata('web', csrf=True, origin=True))
def logout(request: Request, principal=Depends(web_principal)):
    validate_account_mutation(request, principal)
    required_runtime(request).auth.logout(principal)
    response = Response(status_code=204)
    response.delete_cookie(cookie_name(request.app.state.settings), **cookie_options(request.app.state.settings))
    return response


@router.post('/v1/auth/verify-email/request', status_code=204, operation_id='requestEmailVerification', openapi_extra=metadata('public', origin=True))
def request_verification(body: r.EmailRequest, request: Request):
    validate_web_origin(request)
    required_runtime(request).email.request_verification(body.email, client_ip(request))
    return Response(status_code=204)


@router.post('/v1/auth/verify-email', status_code=204, operation_id='verifyEmail', openapi_extra=metadata('web', csrf=True, origin=True))
def verify_email(body: r.TokenRequest, request: Request, principal=Depends(web_principal)):
    validate_account_mutation(request, principal)
    required_runtime(request).email.verify(principal, body.token, client_ip(request))
    return Response(status_code=204)


@router.post('/v1/auth/password-reset/request', status_code=204, operation_id='requestPasswordReset', openapi_extra=metadata('public', origin=True))
def request_reset(body: r.EmailRequest, request: Request):
    validate_web_origin(request)
    required_runtime(request).email.request_reset(body.email, client_ip(request))
    return Response(status_code=204)


@router.post('/v1/auth/password-reset/confirm', status_code=204, operation_id='confirmPasswordReset', openapi_extra=metadata('public', origin=True))
def confirm_reset(body: r.PasswordResetConfirm, request: Request):
    validate_web_origin(request)
    required_runtime(request).email.confirm_reset(body.token, body.password, client_ip(request))
    return Response(status_code=204)


@router.delete('/v1/me', status_code=204, operation_id='deleteMe', openapi_extra=metadata('account', csrf=True, origin=True))
def delete_me(body: r.PasswordConfirmation, request: Request, principal=Depends(account_principal)):
    validate_account_mutation(request, principal)
    required_runtime(request).deletion.delete(principal, body.password)
    response = Response(status_code=204)
    if principal.kind == 'web':
        response.delete_cookie(cookie_name(request.app.state.settings), **cookie_options(request.app.state.settings))
    return response

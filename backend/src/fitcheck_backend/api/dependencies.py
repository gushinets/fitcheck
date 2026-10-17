import hmac
from fastapi import Request
from ..auth.errors import AuthError
from ..auth.crypto import cookie_name, TOKEN_PATTERN
from ..auth.access import require_verified


def required_runtime(request: Request):
    value = request.app.state.auth_runtime
    if not request.app.state.settings.auth_enabled or value is None:
        raise AuthError('service_unavailable')
    return value


def client_ip(request: Request) -> str:
    return request.client.host if request.client else 'unknown-peer'


def _origin(request: Request) -> str:
    origins = request.headers.getlist('origin')
    if len(origins) != 1 or origins[0] not in request.app.state.settings.allowed_origins:
        raise AuthError('forbidden')
    return origins[0]


def validate_web_origin(request: Request) -> None:
    if not _origin(request).startswith(('https://', 'http://')):
        raise AuthError('forbidden')


def account_principal(request: Request):
    runtime = required_runtime(request)
    cookie = request.cookies.get(cookie_name(runtime.settings))
    authorizations = request.headers.getlist('authorization')
    if authorizations:
        raise AuthError('forbidden' if cookie is not None else 'unauthenticated')
    if cookie is not None:
        return runtime.auth.resolve(cookie, 'web')
    raise AuthError('unauthenticated')


def web_principal(request: Request):
    principal = account_principal(request)
    if principal.kind != 'web':
        raise AuthError('forbidden')
    return principal


def verified_principal(request: Request):
    return require_verified(account_principal(request))


def validate_session_csrf(request: Request, principal) -> None:
    runtime = required_runtime(request)
    tokens = request.headers.getlist('x-csrf-token')
    if principal.kind != 'web' or len(tokens) != 1 or TOKEN_PATTERN.fullmatch(tokens[0]) is None:
        raise AuthError('forbidden')
    cookie = request.cookies.get(cookie_name(runtime.settings), '')
    session = runtime.auth.session(cookie)
    if session.principal.session_id != principal.session_id or not hmac.compare_digest(tokens[0], session.csrf_token):
        raise AuthError('forbidden')


def validate_bootstrap(request: Request) -> None:
    runtime = required_runtime(request)
    validate_web_origin(request)
    tokens = request.headers.getlist('x-csrf-token')
    cookie = request.cookies.get(cookie_name(runtime.settings, bootstrap=True), '')
    if len(tokens) != 1 or not runtime.crypto.verify_bootstrap(cookie, tokens[0]):
        raise AuthError('forbidden')


def validate_account_mutation(request: Request, principal) -> None:
    validate_web_origin(request)
    validate_session_csrf(request, principal)


from typing import Literal
from ..guests.types import AccessIdentity
from ..guests.sessions import guest_cookie_name


def resolve_identity(request: Request, mode: Literal['account','guest'] | None = None):
    runtime=required_runtime(request)
    if mode is None:
        mode='account' if cookie_name(runtime.settings) in request.cookies else 'guest'
    if request.headers.getlist('authorization'):
        raise AuthError('forbidden' if request.cookies else 'unauthenticated')
    if mode=='guest':
        return runtime.guests.resolve(request.cookies.get(guest_cookie_name(runtime.settings)))
    principal=verified_principal(request)
    issued=runtime.auth.session(request.cookies[cookie_name(runtime.settings)])
    return AccessIdentity('account',principal.owner_id,principal.session_id,issued.expires_at,principal.user_id)


def validate_identity_mutation(request: Request,identity):
    runtime=required_runtime(request)
    validate_web_origin(request)
    if identity.mode=='account':
        validate_session_csrf(request,verified_principal(request))
    else:
        values=request.headers.getlist('x-csrf-token')
        token=request.cookies.get(guest_cookie_name(runtime.settings),'')
        if len(values)!=1 or not hmac.compare_digest(values[0],runtime.guests.csrf(token)):
            raise AuthError('forbidden')

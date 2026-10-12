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


def validate_extension_origin(request: Request) -> None:
    if not _origin(request).startswith('chrome-extension://'):
        raise AuthError('forbidden')


def account_principal(request: Request):
    runtime = required_runtime(request)
    cookie = request.cookies.get(cookie_name(runtime.settings))
    authorizations = request.headers.getlist('authorization')
    if len(authorizations) > 1 or cookie is not None and authorizations:
        raise AuthError('forbidden')
    if authorizations:
        parts = authorizations[0].split(' ')
        if len(parts) != 2 or parts[0].lower() != 'bearer' or not parts[1]:
            raise AuthError('unauthenticated')
        return runtime.auth.resolve(parts[1], 'extension')
    if cookie is not None:
        return runtime.auth.resolve(cookie, 'web')
    raise AuthError('unauthenticated')


def web_principal(request: Request):
    principal = account_principal(request)
    if principal.kind != 'web':
        raise AuthError('forbidden')
    return principal


def extension_principal(request: Request):
    principal = account_principal(request)
    if principal.kind != 'extension':
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
    if principal.kind == 'web':
        validate_web_origin(request)
        validate_session_csrf(request, principal)
    else:
        validate_extension_origin(request)

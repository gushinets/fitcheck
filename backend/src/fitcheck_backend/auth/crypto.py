import base64
import hashlib
import hmac
import re
import secrets

from .types import Clock

TOKEN_PATTERN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
BOOTSTRAP_PATTERN = re.compile(r'v1\.([0-9]{1,12})\.([A-Za-z0-9_-]{43})\.([A-Za-z0-9_-]{43})\Z')


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


class AuthCrypto:
    def __init__(self, secret: bytes, clock: Clock):
        if len(secret) < 32:
            raise ValueError('Authentication secret is too short')
        self._secret = secret
        self.clock = clock

    @staticmethod
    def new_token() -> str:
        return b64(secrets.token_bytes(32))

    @staticmethod
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    def _mac(self, scope: str, value: str) -> str:
        message = b'fitcheck:' + scope.encode('utf-8') + b'\x00' + value.encode('utf-8')
        return b64(hmac.digest(self._secret, message, 'sha256'))

    def session_csrf(self, raw_session: str) -> str:
        return self._mac('session-csrf', raw_session)

    def subject_digest(self, scope: str, value: str) -> str:
        return self.digest(self._mac('rate:' + scope, value))

    def issue_bootstrap(self) -> tuple[str, str]:
        payload = f'v1.{int(self.clock().timestamp())}.{self.new_token()}'
        cookie = payload + '.' + self._mac('bootstrap-sign', payload)
        return cookie, self._mac('bootstrap-csrf', cookie)

    def verify_bootstrap(self, cookie: str, csrf: str) -> bool:
        match = BOOTSTRAP_PATTERN.fullmatch(cookie)
        if match is None or TOKEN_PATTERN.fullmatch(csrf) is None:
            return False
        age = self.clock().timestamp() - int(match[1])
        if not 0 <= age < 900:
            return False
        return (hmac.compare_digest(match[3], self._mac('bootstrap-sign', cookie.rsplit('.', 1)[0]))
                and hmac.compare_digest(csrf, self._mac('bootstrap-csrf', cookie)))


def cookie_name(settings, *, bootstrap: bool = False) -> str:
    suffix = 'auth_csrf' if bootstrap else 'session'
    return ('__Host-' if settings.env == 'production' else '') + 'fitcheck_' + suffix


def cookie_options(settings) -> dict:
    return {'secure': settings.env == 'production', 'httponly': True, 'samesite': 'lax', 'path': '/'}

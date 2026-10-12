STATUS = {
    'invalid_credentials': 401, 'unauthenticated': 401, 'invalid_token': 400,
    'forbidden': 403, 'email_not_verified': 403, 'registration_conflict': 409,
    'ownership_conflict': 409, 'email_unavailable': 503, 'service_unavailable': 503,
    'rate_limited': 429, 'not_found': 404,
}


class AuthError(Exception):
    def __init__(self, code: str, *, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = STATUS[code]
        self.retry_after = retry_after

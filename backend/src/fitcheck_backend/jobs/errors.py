class JobError(Exception):
    STATUSES = {'invalid_request': 400, 'unauthenticated': 401, 'forbidden': 403,
        'not_found': 404, 'conflict': 409, 'rate_limited': 429,
        'service_unavailable': 503, 'invalid_output': 502, 'upstream': 502, 'timeout': 504}

    def __init__(self, code: str):
        if code not in self.STATUSES:
            code = 'service_unavailable'
        self.code, self.status = code, self.STATUSES[code]
        super().__init__(code)

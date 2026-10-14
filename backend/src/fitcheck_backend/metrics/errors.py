import re


class MetricsError(Exception):
    def __init__(self, code: str):
        if not isinstance(code, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,79}', code) is None:
            code = 'invalid_request'
        self.code = code
        super().__init__(code)

class QuotaError(Exception):
    def __init__(self, code, *, retry_after=None):
        if code not in {'quota_exceeded','budget_exceeded'}:
            raise ValueError('Unknown quota error')
        self.code,self.status,self.retry_after = code,429,retry_after
        super().__init__(code)

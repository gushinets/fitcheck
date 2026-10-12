class ProfileError(Exception):
    STATUS = {'not_found': 404, 'profile_revision_conflict': 409, 'service_unavailable': 503}

    def __init__(self, code: str):
        self.code = code
        self.status = self.STATUS[code]
        super().__init__(code)

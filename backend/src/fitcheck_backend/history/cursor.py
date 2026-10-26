"""Signed keyset positions bound to account, filters and ordering."""
import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime
from uuid import UUID

from ..jobs.errors import JobError


class HistoryCursor:
    def __init__(self, secret: bytes):
        self.key = hmac.digest(secret, b'fitcheck:history-cursor:v1', 'sha256')

    def encode(self, scope, created_at, record_id):
        payload = json.dumps([1, scope, created_at.isoformat(), str(record_id)], separators=(',', ':')).encode()
        return base64.urlsafe_b64encode(payload + hmac.digest(self.key, payload, 'sha256')).decode().rstrip('=')

    def decode(self, value, scope):
        try:
            raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
            payload, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(signature, hmac.digest(self.key, payload, 'sha256')):
                raise ValueError()
            version, saved_scope, timestamp, identifier = json.loads(payload)
            created_at = datetime.fromisoformat(timestamp)
            if version != 1 or saved_scope != scope or created_at.tzinfo is None:
                raise ValueError()
            return created_at, UUID(identifier)
        except (ValueError, TypeError, binascii.Error, UnicodeError):
            raise JobError('invalid_request') from None

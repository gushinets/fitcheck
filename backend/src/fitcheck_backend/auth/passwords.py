from threading import BoundedSemaphore
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError


class PasswordCodec:
    def __init__(self, *, hasher=None, limiter=None):
        self._hasher = hasher if hasher is not None else PasswordHasher(
            memory_cost=65536, time_cost=3, parallelism=4, salt_len=16, hash_len=32, type=Type.ID)
        self._limiter = limiter if limiter is not None else BoundedSemaphore(2)
        self.dummy_hash = self.hash('fitcheck-dummy-password')

    def hash(self, password: str) -> str:
        with self._limiter:
            return self._hasher.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        with self._limiter:
            try:
                return self._hasher.verify(encoded, password)
            except (VerificationError, InvalidHashError):
                return False

    def needs_rehash(self, encoded: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(encoded)
        except InvalidHashError:
            return False

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from argon2 import extract_parameters, Type
from fitcheck_backend.auth.passwords import PasswordCodec


def test_argon_parameters_and_rehash():
    codec = PasswordCodec()
    a, b = codec.hash('correct horse battery'), codec.hash('correct horse battery')
    assert a != b and codec.verify(a, 'correct horse battery')
    assert not codec.verify(a, 'wrong') and not codec.verify('malformed', 'x')
    p = extract_parameters(a)
    assert (p.type, p.memory_cost, p.time_cost, p.parallelism, p.salt_len, p.hash_len) == (Type.ID, 65536, 3, 4, 16, 32)
    assert not codec.needs_rehash(a)
    from argon2 import PasswordHasher
    assert codec.needs_rehash(PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash('password'))


def test_hashing_concurrency_never_exceeds_two():
    guard = Lock()
    release = Event()
    entered = Event()
    active = [0, 0]
    class ExpensiveHasher:
        def hash(self, value):
            if value == 'fitcheck-dummy-password':
                return 'dummy'
            with guard:
                active[0] += 1
                active[1] = max(active)
                if active[0] == 2:
                    entered.set()
            assert release.wait(5)
            with guard:
                active[0] -= 1
            return 'hash'
    codec = PasswordCodec(hasher=ExpensiveHasher())
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(codec.hash, 'password') for _ in range(6)]
        try:
            assert entered.wait(5)
        finally:
            release.set()
        assert [f.result() for f in futures] == ['hash'] * 6
    assert active[1] == 2

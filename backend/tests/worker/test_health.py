import os
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_health_requires_live_pid_and_fresh_marker(tmp_path):
    from fitcheck_backend.worker.health import WorkerHealth, healthy
    path = tmp_path/'health.json'
    now = [100.0]
    value = WorkerHealth(path,clock=lambda:now[0])
    assert not healthy(path,now=100)
    value.mark()
    assert healthy(path,now=100)
    assert not healthy(path,now=146)
    path.write_text(json.dumps({'pid':99999999,'at':100}))
    assert not healthy(path,now=100)
    value.clear()
    assert not healthy(path,now=100)


def test_missing_key_startup_removes_previous_healthy_marker(tmp_path):
    import asyncio
    import pytest
    from fitcheck_backend.worker.runtime import WorkerRuntime
    from fitcheck_backend.worker.settings import WorkerSettings
    from fitcheck_backend.worker.health import healthy
    from fitcheck_backend.config import Settings
    path = tmp_path/'health.json'
    runtime = WorkerRuntime(Settings(_env_prefix='FITCHECK_WORKER_TEST_EMPTY_',open_ai_key=None),
        WorkerSettings(health_path=str(path)))
    runtime.health.mark()
    assert healthy(path)
    with pytest.raises(ValueError): asyncio.run(runtime.start())
    assert not healthy(path)


def test_health_tracks_child_exit_without_signaling_it(tmp_path):
    from fitcheck_backend.worker.health import healthy
    path = tmp_path / 'health.json'
    child = subprocess.Popen([sys.executable, '-c',
        'import sys; print("ready", flush=True); sys.stdin.read()'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        path.write_text(json.dumps({'pid': child.pid, 'at': 100}))
        assert healthy(path, now=100)
        assert child.poll() is None
        child.communicate(timeout=5)
        assert child.returncode == 0
        assert not healthy(path, now=100)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.parametrize('handle,result,expected', [
    (None, None, False),  # Missing process or access denied.
    (2**40, 0x102, True),  # 64-bit handle must not be truncated.
    (2**40, 0, False),  # Exited, even while another handle keeps it open.
    (2**40, 0xFFFFFFFF, False),  # WAIT_FAILED is not liveness.
])
def test_windows_health_uses_nonblocking_process_query(monkeypatch, tmp_path, handle, result, expected):
    import ctypes
    from fitcheck_backend.worker import health
    kernel = SimpleNamespace(OpenProcess=Mock(return_value=handle),
        WaitForSingleObject=Mock(return_value=result), CloseHandle=Mock())
    dll = Mock(return_value=kernel)
    monkeypatch.setattr(ctypes, 'WinDLL', dll, raising=False)
    monkeypatch.setattr(health, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(health, '_open_marker', lambda path: path.open(encoding='utf-8'))
    monkeypatch.setattr(os, 'kill', Mock(side_effect=AssertionError('Health must not send Windows signals')))
    path = tmp_path / 'health.json'
    path.write_text(json.dumps({'pid': 123, 'at': 100}))
    assert health.healthy(path, now=100) is expected
    dll.assert_called_once_with('kernel32', use_last_error=True)
    kernel.OpenProcess.assert_called_once_with(0x00100000, False, 123)
    if handle:
        kernel.WaitForSingleObject.assert_called_once_with(handle, 0)
        kernel.CloseHandle.assert_called_once_with(handle)
    else:
        kernel.WaitForSingleObject.assert_not_called()
        kernel.CloseHandle.assert_not_called()


def test_windows_health_rejects_pid_overflow_before_opening_process(monkeypatch, tmp_path):
    from fitcheck_backend.worker import health
    monkeypatch.setattr(health, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(health, '_open_marker', lambda path: path.open(encoding='utf-8'))
    path = tmp_path / 'health.json'
    path.write_text(json.dumps({'pid': 2**32 + os.getpid(), 'at': 100}))
    assert not health.healthy(path, now=100)


@pytest.mark.parametrize('operation', ['mark', 'clear'])
def test_probe_reader_serializes_replace_and_shutdown_cleanup(tmp_path, operation):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from fitcheck_backend.worker.health import WorkerHealth, healthy
    path = tmp_path / 'health.json'
    marker = WorkerHealth(path)
    marker.mark()
    script = """
import sys
from fitcheck_backend.worker.health import _open_marker
with _open_marker(sys.argv[1]) as stream:
    print('ready', flush=True)
    sys.stdin.readline()
    assert stream.read()
"""
    child = subprocess.Popen([sys.executable, '-c', script, str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        assert child.stdout.readline().strip() == 'ready'
        write = pool.submit(getattr(marker, operation))
        if sys.platform == 'win32':
            # The writer must wait for the real probe's open handle to close.
            with pytest.raises(TimeoutError):
                write.result(timeout=0.05)
        child.communicate(input='done\n', timeout=10)
        assert child.returncode == 0
        write.result(timeout=10)
        assert healthy(path) is (operation == 'mark')
        marker.clear()
        assert not path.exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
        pool.shutdown(wait=True)


@pytest.mark.parametrize('wait_result', [0, 0x80, 0x102])
def test_windows_marker_mutex_releases_handles_and_bounds_wait(monkeypatch, tmp_path, wait_result):
    import ctypes
    from fitcheck_backend.worker import health
    handle = 2**40
    kernel = SimpleNamespace(CreateMutexW=Mock(return_value=handle),
        WaitForSingleObject=Mock(return_value=wait_result), ReleaseMutex=Mock(), CloseHandle=Mock())
    monkeypatch.setattr(ctypes, 'WinDLL', Mock(return_value=kernel), raising=False)
    monkeypatch.setattr(health, 'sys', SimpleNamespace(platform='win32'))
    def operation():
        with health._marker_lock(tmp_path / 'health.json'):
            raise ValueError('body failed')
    if wait_result == 0x102:
        with pytest.raises(TimeoutError): operation()
        kernel.ReleaseMutex.assert_not_called()
    else:
        with pytest.raises(ValueError, match='body failed'): operation()
        kernel.ReleaseMutex.assert_called_once_with(handle)
    kernel.WaitForSingleObject.assert_called_once_with(handle, 5000)
    kernel.CloseHandle.assert_called_once_with(handle)


def test_concurrent_health_probes_and_writer_do_not_crash(tmp_path):
    from fitcheck_backend.worker.health import WorkerHealth, healthy
    path = tmp_path / 'health.json'
    stop = tmp_path / 'stop'
    marker = WorkerHealth(path)
    marker.mark()
    script = '''
import sys
from pathlib import Path
from fitcheck_backend.worker.health import healthy
assert healthy(sys.argv[1])
print('ready', flush=True)
count = 0
while not Path(sys.argv[2]).exists():
    count += healthy(sys.argv[1])
print(count, flush=True)
'''
    child = subprocess.Popen([sys.executable, '-c', script, str(path), str(stop)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        for _ in range(5000):
            marker.mark()
        assert healthy(path)
        marker.clear()
        assert not path.exists()
        stop.touch()
        output, _ = child.communicate(timeout=10)
        assert child.returncode == 0 and int(output.strip()) > 0
        assert not path.with_suffix('.tmp').exists()
    finally:
        stop.touch()
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)


@pytest.mark.parametrize('operation', ['mark', 'clear'])
def test_health_recovers_after_reader_exits_with_open_handle(tmp_path, operation):
    from fitcheck_backend.worker.health import WorkerHealth, healthy
    path = tmp_path / 'health.json'
    now = [100.0]
    marker = WorkerHealth(path, clock=lambda: now[0])
    script = '''
import os, sys, time
from fitcheck_backend.worker.health import _open_marker
with _open_marker(sys.argv[1]) as stream:
    print('ready', flush=True)
    time.sleep(0.3)
    os._exit(17)
'''
    for _ in range(10):
        now[0] = 100.0
        marker.mark()
        child = subprocess.Popen([sys.executable, '-c', script, str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == 'ready'
            now[0] = 200.0
            # On Windows this waits for the abandoned mutex, then accesses the
            # file before wait()/communicate() confirms full process teardown.
            getattr(marker, operation)()
            child.communicate(timeout=10)
            assert child.returncode == 17
            assert healthy(path, now=200) is (operation == 'mark')
            marker.clear()
            assert not path.exists() and not path.with_suffix('.tmp').exists()
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)


@pytest.mark.parametrize('operation', ['mark', 'clear'])
@pytest.mark.parametrize('persistent', [False, True])
def test_windows_sharing_errors_are_bounded_and_recoverable(monkeypatch, tmp_path, caplog, operation, persistent):
    from contextlib import nullcontext
    from pathlib import Path
    from fitcheck_backend.worker import health
    path = tmp_path / 'health.json'
    now = [100.0]
    marker = health.WorkerHealth(path, clock=lambda: now[0])
    marker.mark()
    now[0] = 200.0
    monkeypatch.setattr(health, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(health, '_marker_lock', lambda _: nullcontext())
    delays = []
    monkeypatch.setattr(health.time, 'sleep', delays.append)
    method = 'replace' if operation == 'mark' else 'unlink'
    original = getattr(Path, method)
    calls = []
    error = PermissionError('reader handle is closing')
    error.winerror = 32
    def change(*args, **kwargs):
        calls.append(True)
        if persistent or len(calls) <= 2:
            raise error
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, method, change)
        assert getattr(marker, operation)() is (not persistent)
    if persistent:
        assert len(calls) == 7 and sum(delays) < 0.3
        assert json.loads(path.read_text())['at'] == 100.0
        assert 'health marker temporarily unavailable' in caplog.text
    else:
        assert len(delays) == 2
    # A later pass recovers, including deletion of any unpublished temp file.
    assert marker.mark() and json.loads(path.read_text())['at'] == 200.0
    assert marker.clear()
    assert not path.exists() and not path.with_suffix('.tmp').exists()


@pytest.mark.parametrize('platform,winerror', [('win32', 87), ('darwin', 32)])
def test_health_filesystem_failure_is_reported_without_stopping_worker(monkeypatch, tmp_path, caplog, platform, winerror):
    from contextlib import nullcontext
    from pathlib import Path
    from fitcheck_backend.worker import health
    monkeypatch.setattr(health, 'sys', SimpleNamespace(platform=platform))
    monkeypatch.setattr(health, '_marker_lock', lambda _: nullcontext())
    error = PermissionError('unrelated filesystem failure')
    error.winerror = winerror
    monkeypatch.setattr(Path, 'replace', Mock(side_effect=error))
    assert health.WorkerHealth(tmp_path / 'health.json').mark() is False
    assert 'health marker temporarily unavailable' in caplog.text


@pytest.mark.parametrize('crash', [False, True])
def test_health_path_is_exclusive_across_worker_processes(tmp_path, crash):
    from fitcheck_backend.worker.health import WorkerHealth, healthy
    path = tmp_path / 'health.json'
    script = '''
import os, sys
from fitcheck_backend.worker.health import WorkerHealth
health = WorkerHealth(sys.argv[1])
health.claim()
health.mark()
print('ready', flush=True)
sys.stdin.readline()
if sys.argv[2] == 'crash': os._exit(17)
health.close()
'''
    child = subprocess.Popen([sys.executable, '-c', script, str(path), 'crash' if crash else 'normal'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    second = WorkerHealth(path)
    try:
        assert child.stdout.readline().strip() == 'ready'
        with pytest.raises(RuntimeError, match='already in use'):
            second.claim()
        assert second.mark() is False and second.clear() is False
        assert healthy(path)
        child.communicate(input='stop\n', timeout=10)
        assert child.returncode == (17 if crash else 0)
        second.claim()
        assert second.mark() and healthy(path)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
        second.close()
    assert not path.exists()


@pytest.mark.parametrize('error', [PermissionError('read only'), OSError(28, 'disk full'), FileNotFoundError('removed')])
def test_health_io_failure_does_not_fabricate_freshness_and_can_recover(tmp_path, monkeypatch, error):
    from pathlib import Path
    from fitcheck_backend.worker.health import WorkerHealth, healthy
    path = tmp_path / 'health.json'
    clock = [100.0]
    marker = WorkerHealth(path, clock=lambda: clock[0])
    marker.mark()
    clock[0] = 200.0
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'replace', Mock(side_effect=error))
        patch.setattr(Path, 'unlink', Mock(side_effect=error))
        assert marker.mark() is False
        assert marker.clear() is False
        assert not healthy(path, now=200)
    assert marker.mark() and healthy(path, now=200)
    marker.close()
    assert not path.exists()


@pytest.mark.parametrize('payload', ['null', '{', 'x' * 4097,
    '{"pid":1,"at":' + '9' * 500 + '}',
    '{"pid":' + '9' * 500 + ',"at":100}'])
def test_invalid_marker_always_returns_unhealthy(tmp_path, payload):
    from fitcheck_backend.worker.health import healthy
    path = tmp_path / 'health.json'
    path.write_text(payload)
    assert not healthy(path, now=100)


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows mutex wait timeout')
def test_live_reader_timeout_expires_health_then_recovers(tmp_path):
    from fitcheck_backend.worker.health import WorkerHealth, healthy
    path = tmp_path / 'health.json'
    clock = [100.0]
    marker = WorkerHealth(path, clock=lambda: clock[0])
    marker.mark()
    script = '''
import sys
from fitcheck_backend.worker.health import _open_marker
with _open_marker(sys.argv[1]):
    print('ready', flush=True)
    sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, '-c', script, str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        clock[0] = 200.0
        assert marker.mark() is False
        assert child.poll() is None
        child.communicate(input='release\n', timeout=10)
        assert child.returncode == 0
        assert not healthy(path, now=200)
        assert marker.mark() and healthy(path, now=200)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
        marker.close()

"""Start the public module entry point against disposable PostgreSQL."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


pytestmark = pytest.mark.integration


@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize('reader_mode', ['none', 'crash', 'slow'])
def test_worker_module_starts_and_exits_cleanly(engine, tmp_path, sig, reader_mode):
    if reader_mode == 'slow' and sys.platform != 'win32':
        pytest.skip('Native Windows mutex timeout scenario')
    backend = Path(__file__).resolve().parents[2]
    health = tmp_path / 'worker-health.json'
    env = {k: v for k, v in os.environ.items()
        if not k.startswith(('FITCHECK_', 'OPEN_AI_'))}
    env.update(PYTHONPATH=str(backend / 'src'), OPEN_AI_KEY='cli-test-no-provider-calls',
        FITCHECK_DATABASE_URL=engine.url.render_as_string(hide_password=False),
        FITCHECK_ENV='test', FITCHECK_WORKER_HEALTH_PATH=str(health),
        FITCHECK_WORKER_POLL_INTERVAL='0.05', FITCHECK_WORKER_DRAIN_SECONDS='0.1')
    command = [sys.executable, '-m', 'fitcheck_backend.worker']
    if sys.platform == 'win32':
        # send_signal(SIGTERM) forcefully terminates Windows processes. Deliver
        # to the installed Python handler instead, without changing worker code.
        bootstrap = '''
import _thread, runpy, sys, threading
signum = int(sys.argv[1])
def stop():
    sys.stdin.readline()
    _thread.interrupt_main(signum)
threading.Thread(target=stop, daemon=True).start()
runpy.run_module('fitcheck_backend.worker', run_name='__main__')
'''
        command = [sys.executable, '-c', bootstrap, str(int(sig))]
    process = subprocess.Popen(command, cwd=backend, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    slow_reader = None
    try:
        deadline = time.monotonic() + 15
        while not health.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert health.exists(), 'Worker CLI did not become healthy'
        for _ in range(30):
            probe = subprocess.run([sys.executable, '-m', 'fitcheck_backend.worker.health'],
                cwd=backend, env=env, capture_output=True, timeout=10)
            assert probe.returncode == 0
            assert process.poll() is None, 'Health probes must not stop the worker'
        if reader_mode == 'none':
            second = subprocess.Popen(command, cwd=backend, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                assert second.wait(timeout=10) == 1
                second.communicate(timeout=5)
            finally:
                if second.poll() is None:
                    second.kill()
                    second.communicate(timeout=5)
            assert process.poll() is None
            probe = subprocess.run([sys.executable, '-m', 'fitcheck_backend.worker.health'],
                cwd=backend, env=env, capture_output=True, timeout=10)
            assert probe.returncode == 0, 'Rejected worker must not clear the active marker'
        if reader_mode == 'crash':
            script = '''
import os, sys, time
from fitcheck_backend.worker.health import _open_marker
with _open_marker(sys.argv[1]) as stream:
    print('ready', flush=True)
    time.sleep(0.3)
    os._exit(17)
'''
            for _ in range(5):
                reader = subprocess.Popen([sys.executable, '-c', script, str(health)],
                    cwd=backend, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    assert reader.stdout.readline().strip() == b'ready'
                    reader.communicate(timeout=10)
                    assert reader.returncode == 17
                finally:
                    if reader.poll() is None:
                        reader.kill()
                        reader.communicate(timeout=10)
                assert process.poll() is None, 'Crashing health reader must not stop worker'
            for _ in range(30):
                probe = subprocess.run([sys.executable, '-m', 'fitcheck_backend.worker.health'],
                    cwd=backend, env=env, capture_output=True, timeout=10)
                assert probe.returncode == 0 and process.poll() is None
        if reader_mode == 'slow':
            script = """
import sys, time
from fitcheck_backend.worker.health import _open_marker
with _open_marker(sys.argv[1]):
    print('ready', flush=True)
    time.sleep(8.0)
"""
            slow_reader = subprocess.Popen([sys.executable, '-c', script, str(health)],
                cwd=backend, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert slow_reader.stdout.readline().strip() == b'ready'
            probe = subprocess.run([sys.executable, '-m', 'fitcheck_backend.worker.health'],
                cwd=backend, env=env, capture_output=True, timeout=8)
            assert probe.returncode == 1 and process.poll() is None
            assert slow_reader.poll() is None
        if sys.platform == 'win32':
            # In the slow-reader case, stop while the reader still owns mutex.
            process.communicate(input=b'stop\n', timeout=12)
        else:
            process.send_signal(sig)
            process.communicate(timeout=10)
        if slow_reader is not None:
            slow_reader.communicate(timeout=10)
            assert slow_reader.returncode == 0
        assert process.returncode == 0
        assert not health.exists()
    finally:
        if slow_reader is not None and slow_reader.poll() is None:
            slow_reader.kill()
            slow_reader.communicate(timeout=10)
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)

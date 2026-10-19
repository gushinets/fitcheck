"""Start the public module entry point against disposable PostgreSQL."""
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time

import pytest
from worker_cli_helpers import worker_command


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
    command = worker_command(sig)
    streams = []
    def output_files(role):
        handles = [(tmp_path / f'{role}.{name}.log').open('wb') for name in ('stdout', 'stderr')]
        streams.extend(handles)
        return handles
    stdout, stderr = output_files('primary')
    process = subprocess.Popen(command, cwd=backend, env=env, stdin=subprocess.PIPE,
        stdout=stdout, stderr=stderr)
    slow_reader = None
    try:
        deadline = time.monotonic() + 45
        while not health.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert health.exists(), f'Worker CLI did not become healthy (exit={process.poll()}); see subprocess logs'
        for _ in range(30):
            probe = subprocess.run([sys.executable, '-m', 'fitcheck_backend.worker.health'],
                cwd=backend, env=env, capture_output=True, timeout=10)
            assert probe.returncode == 0
            assert process.poll() is None, 'Health probes must not stop the worker'
        if reader_mode == 'none':
            # This process must reject startup and needs no signal delivery
            # helper; exercise the public module entry point directly.
            second_stdout, second_stderr = output_files('second')
            second = subprocess.Popen([sys.executable, '-m', 'fitcheck_backend.worker'], cwd=backend, env=env, stdin=subprocess.PIPE,
                stdout=second_stdout, stderr=second_stderr)
            try:
                assert second.wait(timeout=45) == 1
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
        for stream in streams:
            stream.close()
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            report = backend / 'reports' / 'worker-cli' / tmp_path.name
            report.mkdir(parents=True, exist_ok=True)
            for log in tmp_path.glob('*.log'):
                shutil.copy2(log, report / log.name)

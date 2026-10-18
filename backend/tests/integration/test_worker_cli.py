"""Start the public module entry point against disposable PostgreSQL."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.skipif(sys.platform == 'win32',
    reason='POSIX subprocess signals; Windows handler fallback is covered in unit tests')]


@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM])
def test_worker_module_starts_and_exits_cleanly(engine, tmp_path, sig):
    backend = Path(__file__).resolve().parents[2]
    health = tmp_path / 'worker-health.json'
    env = {k: v for k, v in os.environ.items()
        if not k.startswith(('FITCHECK_', 'OPEN_AI_'))}
    env.update(PYTHONPATH=str(backend / 'src'), OPEN_AI_KEY='cli-test-no-provider-calls',
        FITCHECK_DATABASE_URL=engine.url.render_as_string(hide_password=False),
        FITCHECK_ENV='test', FITCHECK_WORKER_HEALTH_PATH=str(health),
        FITCHECK_WORKER_POLL_INTERVAL='0.05', FITCHECK_WORKER_DRAIN_SECONDS='0.1')
    process = subprocess.Popen([sys.executable, '-m', 'fitcheck_backend.worker'],
        cwd=backend, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 15
        while not health.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert health.exists(), 'Worker CLI did not become healthy'
        process.send_signal(sig)
        process.communicate(timeout=10)
        assert process.returncode == 0
        assert not health.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)

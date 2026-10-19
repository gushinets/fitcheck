import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from worker_cli_helpers import WINDOWS_SIGNAL_BOOTSTRAP


@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM])
def test_signal_helper_does_not_hold_interpreter_open_after_startup_failure(tmp_path, sig):
    backend = Path(__file__).resolve().parents[2]
    env = {key: value for key, value in os.environ.items()
        if not key.startswith(('FITCHECK_', 'OPEN_AI_'))}
    env.update(PYTHONPATH=str(backend / 'src'), OPEN_AI_KEY='',
        FITCHECK_WORKER_HEALTH_PATH=str(tmp_path / 'health.json'))
    child = subprocess.Popen([sys.executable, '-c', WINDOWS_SIGNAL_BOOTSTRAP, str(int(sig))],
        cwd=backend, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Keep stdin open: a daemon control reader is waiting when the real CLI
        # rejects the absent key. Exit must not depend on the parent closing it.
        assert child.wait(timeout=45) == 1
        _, stderr = child.communicate(timeout=5)
        assert b'Worker startup/runtime unavailable' in stderr
        assert b'Fatal Python error' not in stderr
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)

import os
from pathlib import Path
import subprocess
import sys


def test_explicit_integration_requires_database():
    env = dict(os.environ)
    env.pop("FITCHECK_TEST_DATABASE_URL", None)
    result = subprocess.run([sys.executable, "-m", "pytest", "-m", "integration", "tests/integration/test_migrations.py::test_bootstrap_reupgrade_and_drift", "-q"], cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "FITCHECK_TEST_DATABASE_URL is required" in result.stdout
    assert "skipped" not in result.stdout

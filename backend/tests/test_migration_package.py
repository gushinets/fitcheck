import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_installed_package_has_migrations(tmp_path):
    """Catch missing wheel resources and dependence on checkout/cwd."""
    uv = shutil.which("uv")
    assert uv, "uv is required to verify the distributable wheel"
    root = Path(__file__).parents[1]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("FITCHECK_DATABASE_URL", None)
    env.setdefault("UV_CACHE_DIR", "/private/tmp/fitcheck-uv-cache" if sys.platform=="darwin" else str(tmp_path/"cache"))
    def run(args, *, cwd=root):
        result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
        assert result.returncode==0, result.stdout+result.stderr
        return result
    run([uv, "build", "--wheel", "--out-dir", str(tmp_path/"dist")])
    run([uv, "venv", "--python", sys.executable, str(tmp_path/"venv")])
    python = str(tmp_path/"venv/bin/python")
    exported = run([uv, "export", "--locked", "--no-dev", "--no-emit-project", "--format", "requirements-txt"])
    requirements = tmp_path/"requirements.txt"
    requirements.write_text(exported.stdout)
    run([uv, "pip", "install", "--python", python, "-r", str(requirements), str(next((tmp_path/"dist").glob("*.whl")))])
    run([python, "-c", "from pathlib import Path; import fitcheck_backend; from alembic.config import Config; from alembic.script import ScriptDirectory; p=Path(fitcheck_backend.__file__).parent/'_migrations'; assert (p/'env.py').is_file(); c=Config(str(p/'alembic.ini')); c.set_main_option('script_location',str(p)); assert ScriptDirectory.from_config(c).get_current_head()=='0003'"], cwd=tmp_path)
    result = subprocess.run([python, "-m", "fitcheck_backend.storage.migrate", "upgrade"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode==1
    assert "FITCHECK_DATABASE_URL is required" in result.stderr
    assert "Traceback" not in result.stderr and "FileNotFoundError" not in result.stderr

import os
import json


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
    runtime = WorkerRuntime(Settings(_env_prefix='FITCHECK_WORKER_TEST_EMPTY_',deepseek_api_key=None),
        WorkerSettings(health_path=str(path)))
    runtime.health.mark()
    assert healthy(path)
    with pytest.raises(ValueError): asyncio.run(runtime.start())
    assert not healthy(path)

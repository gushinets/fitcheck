import asyncio
from types import SimpleNamespace

import pytest

from fitcheck_backend.worker.runtime import WorkerRuntime


@pytest.mark.parametrize('health_fails,llm_fails', [(True, False), (False, True), (True, True)])
def test_runtime_attempts_all_cleanup_even_when_an_earlier_step_fails(health_fails, llm_fails):
    events = []
    def close_health():
        events.append('health')
        if health_fails:
            raise RuntimeError('health cleanup failed')
    async def close_llm():
        events.append('llm')
        if llm_fails:
            raise RuntimeError('llm cleanup failed')
    runtime = WorkerRuntime.__new__(WorkerRuntime)
    runtime.health = SimpleNamespace(close=close_health)
    runtime.llm = SimpleNamespace(aclose=close_llm)
    runtime.engine = SimpleNamespace(dispose=lambda: events.append('db'))
    with pytest.raises(RuntimeError):
        asyncio.run(runtime.aclose())
    assert events == ['health', 'llm', 'db']


def test_closing_health_prevents_late_background_updates(tmp_path):
    from fitcheck_backend.worker.health import WorkerHealth
    path = tmp_path / 'health.json'
    health = WorkerHealth(path)
    health.claim()
    health.mark()
    health.close()
    assert health.mark() is False
    assert not path.exists()
    # The OS lock is released, while the stable guard inode remains reusable.
    replacement = WorkerHealth(path)
    try:
        replacement.claim()
        assert replacement.mark()
    finally:
        replacement.close()


def test_cancelled_background_publish_cannot_recreate_closed_marker(tmp_path, monkeypatch):
    from pathlib import Path
    from threading import Event
    from fitcheck_backend.worker.health import WorkerHealth
    entered, released = Event(), Event()
    original = Path.replace
    def replace(source, target):
        entered.set()
        assert released.wait(2)
        return original(source, target)
    monkeypatch.setattr(Path, 'replace', replace)
    marker = WorkerHealth(tmp_path / 'health.json')
    async def run():
        update = asyncio.create_task(asyncio.to_thread(marker.mark))
        close = None
        try:
            while not entered.is_set(): await asyncio.sleep(0)
            update.cancel()
            close = asyncio.create_task(asyncio.to_thread(marker.close))
            released.set()
            await close
            with pytest.raises(asyncio.CancelledError): await update
            assert marker.mark() is False
            assert not marker.path.exists()
        finally:
            released.set()
            await asyncio.gather(update, *([close] if close else []), return_exceptions=True)
    asyncio.run(run())

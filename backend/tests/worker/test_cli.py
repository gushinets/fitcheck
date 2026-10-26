import asyncio
import signal

import pytest

from fitcheck_backend.worker import __main__ as cli


@pytest.mark.parametrize('fallback', [False, True])
@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM])
def test_cli_signals_request_graceful_shutdown_and_restore_handlers(monkeypatch, fallback, sig):
    previous = {s: object() for s in (signal.SIGINT, signal.SIGTERM)}
    handlers = dict(previous)
    native_handlers = {}
    monkeypatch.setattr(signal, 'getsignal', handlers.__getitem__)
    monkeypatch.setattr(signal, 'signal', lambda s, handler: handlers.__setitem__(s, handler))
    events = []

    class Runner:
        def request_shutdown(self):
            events.append('shutdown')
            self.stopped.set()

        async def run_forever(self):
            self.stopped = asyncio.Event()
            events.append('running')
            if fallback:
                handlers[sig](sig, None)
            else:
                native_handlers[sig]()
            await asyncio.wait_for(self.stopped.wait(), 1)
            events.append('drained')

    class Runtime:
        def __init__(self, settings): pass
        async def start(self): return Runner()
        async def aclose(self): events.append('closed')

    monkeypatch.setattr(cli, 'WorkerRuntime', Runtime)
    async def run():
        loop = asyncio.get_running_loop()
        def add(s, handler):
            if fallback:
                raise NotImplementedError
            native_handlers[s] = handler
        monkeypatch.setattr(loop, 'add_signal_handler', add)
        monkeypatch.setattr(loop, 'remove_signal_handler', lambda s: native_handlers.pop(s))
        await cli.main()
    asyncio.run(run())
    assert events == ['running', 'shutdown', 'drained', 'closed']
    assert handlers == previous and not native_handlers


def test_cli_restores_fallback_handlers_and_closes_runtime_on_failure(monkeypatch):
    previous = {s: object() for s in (signal.SIGINT, signal.SIGTERM)}
    handlers = dict(previous)
    monkeypatch.setattr(signal, 'getsignal', handlers.__getitem__)
    monkeypatch.setattr(signal, 'signal', lambda s, handler: handlers.__setitem__(s, handler))
    closed = []
    class Runner:
        def request_shutdown(self): pass
        async def run_forever(self): raise RuntimeError('worker failed')
    class Runtime:
        def __init__(self, settings): pass
        async def start(self): return Runner()
        async def aclose(self): closed.append(True)
    monkeypatch.setattr(cli, 'WorkerRuntime', Runtime)
    async def run():
        def unsupported(*args): raise NotImplementedError
        monkeypatch.setattr(asyncio.get_running_loop(), 'add_signal_handler', unsupported)
        with pytest.raises(RuntimeError, match='worker failed'):
            await cli.main()
    asyncio.run(run())
    assert handlers == previous and closed == [True]

import asyncio
import logging
import signal
from contextlib import contextmanager
from ..config import Settings
from .runtime import WorkerRuntime


@contextmanager
def shutdown_signals(runner):
    loop = asyncio.get_running_loop()
    installed = []
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous = signal.getsignal(sig)
            try:
                loop.add_signal_handler(sig, runner.request_shutdown)
                native = True
            except NotImplementedError:
                # Windows event loops do not implement add_signal_handler.
                # Schedule the same graceful drain on the running event loop.
                signal.signal(sig, lambda signum, frame: loop.call_soon_threadsafe(runner.request_shutdown))
                native = False
            installed.append((sig, previous, native))
        yield
    finally:
        for sig, previous, native in reversed(installed):
            if native:
                loop.remove_signal_handler(sig)
            signal.signal(sig, previous)


async def main():
    runtime = WorkerRuntime(Settings())
    try:
        runner = await runtime.start()
        with shutdown_signals(runner):
            await runner.run_forever()
    finally:
        await runtime.aclose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try: asyncio.run(main())
    except Exception:
        logging.getLogger('fitcheck.worker').error('Worker startup/runtime unavailable')
        raise SystemExit(1) from None

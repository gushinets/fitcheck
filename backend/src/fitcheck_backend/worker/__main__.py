import asyncio
import logging
import signal
from ..config import Settings
from .runtime import WorkerRuntime


async def main():
    runtime = WorkerRuntime(Settings())
    try:
        runner = await runtime.start()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM,signal.SIGINT): loop.add_signal_handler(sig,runner.request_shutdown)
        await runner.run_forever()
    finally:
        await runtime.aclose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try: asyncio.run(main())
    except Exception:
        logging.getLogger('fitcheck.worker').error('Worker startup/runtime unavailable')
        raise SystemExit(1) from None

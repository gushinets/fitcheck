"""Deliver signals to Python handlers without a buffered stdin reader at exit."""
import sys


WINDOWS_SIGNAL_BOOTSTRAP = '''
import _thread, os, runpy, sys, threading
signum = int(sys.argv[1])
def stop():
    # Buffered stdin.readline() can hold its I/O lock during interpreter
    # shutdown if worker startup fails before the parent requests shutdown.
    if os.read(sys.stdin.fileno(), 1):
        _thread.interrupt_main(signum)
threading.Thread(target=stop, daemon=True).start()
runpy.run_module('fitcheck_backend.worker', run_name='__main__')
'''


def worker_command(sig):
    if sys.platform == 'win32':
        # send_signal(SIGTERM) forcibly terminates Windows; use its Python handler.
        return [sys.executable, '-c', WINDOWS_SIGNAL_BOOTSTRAP, str(int(sig))]
    return [sys.executable, '-m', 'fitcheck_backend.worker']

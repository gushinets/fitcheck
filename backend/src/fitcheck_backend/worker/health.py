import json
import hashlib
import logging
import math
import os
import sys
from contextlib import contextmanager
from pathlib import Path
import time
from uuid import uuid4

logger = logging.getLogger('fitcheck.worker')
_FILE_RETRY_DELAYS = (0.005, 0.01, 0.02, 0.04, 0.08, 0.1)


def _windows_process_alive(pid):
    import ctypes
    from ctypes import wintypes

    if pid > 0xFFFFFFFF:
        return False
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    # SYNCHRONIZE only: inspect process state without sending console signals
    # or obtaining permission to terminate/modify the process.
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        # A process handle is signaled on exit. With a zero timeout, only
        # WAIT_TIMEOUT proves it is still running; errors fail closed.
        return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        kernel32.CloseHandle(handle)


def _process_alive(pid):
    if sys.platform == 'win32':
        return _windows_process_alive(pid)
    os.kill(pid, 0)
    return True


@contextmanager
def _marker_lock(path):
    if sys.platform != 'win32':
        yield
        return

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    # Serialize the entire file-handle lifetime, not just JSON parsing. Windows
    # can retain a replaced file's name until its last reader closes, even with
    # FILE_SHARE_DELETE. A named kernel mutex coordinates separate CLI processes
    # without leaving a lock file and is released if an owner process crashes.
    key = hashlib.sha256(os.path.normcase(os.path.abspath(path)).encode('utf-8')).hexdigest()
    handle = kernel32.CreateMutexW(None, False, 'Local\\FitCheckHealth-' + key)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        result = kernel32.WaitForSingleObject(handle, 5000)
        # WAIT_OBJECT_0 or WAIT_ABANDONED: both grant ownership.
        if result not in (0, 0x80):
            if result == 0x102:
                raise TimeoutError('Health marker lock timed out')
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = True
        yield
    finally:
        if acquired:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


@contextmanager
def _open_marker(path):
    with _marker_lock(path):
        with Path(path).open(encoding='utf-8') as stream:
            yield stream


class WorkerHealth:
    def __init__(self,path,*,clock=time.time,max_age=45):
        self.path,self.clock,self.max_age = Path(path),clock,max_age
        self.boot_id = str(uuid4())

    def _change(self, operation):
        try:
            with _marker_lock(self.path):
                for attempt in range(len(_FILE_RETRY_DELAYS) + 1):
                    try:
                        operation()
                        return True
                    except PermissionError as exc:
                        if sys.platform != 'win32' or getattr(exc, 'winerror', None) not in (5, 32, 33):
                            raise
                        # An abandoned mutex grants ownership before Windows
                        # necessarily finishes closing the dead reader's files.
                        if attempt == len(_FILE_RETRY_DELAYS):
                            break
                        time.sleep(_FILE_RETRY_DELAYS[attempt])
        except TimeoutError:
            if sys.platform != 'win32':
                raise
        # Monitoring contention must not terminate queue processing or final
        # cleanup. Keep the old timestamp: an unrefreshed marker expires, and a
        # later iteration can recover. Do not mask unrelated filesystem errors.
        logger.warning('Worker health marker temporarily unavailable')
        return False

    def mark(self):
        def publish():
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(pid=os.getpid(),at=self.clock(),bootId=self.boot_id,maxAge=self.max_age)),encoding='utf-8')
            temporary.replace(self.path)
        return self._change(publish)

    def clear(self):
        def remove():
            self.path.unlink(missing_ok=True)
            self.path.with_suffix('.tmp').unlink(missing_ok=True)
        return self._change(remove)


def healthy(path,*,now=None):
    try:
        with _open_marker(path) as stream:
            value = json.load(stream)
        age = (time.time() if now is None else now) - value['at']
        max_age = value.get('maxAge',45)
        if not math.isfinite(age) or not math.isfinite(max_age) or not 0 <= age <= max_age or max_age <= 0:
            return False
        if type(value['pid']) is not int or value['pid'] <= 0: return False
        return _process_alive(value['pid'])
    except (OSError,ValueError,TypeError,KeyError):
        return False


if __name__ == '__main__':
    raise SystemExit(0 if healthy(os.environ.get('FITCHECK_WORKER_HEALTH_PATH','/tmp/fitcheck-worker-health.json')) else 1)

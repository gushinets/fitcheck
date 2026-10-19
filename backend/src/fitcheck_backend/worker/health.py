import json
import math
import os
import sys
from pathlib import Path
import time
from uuid import uuid4


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


class WorkerHealth:
    def __init__(self,path,*,clock=time.time,max_age=45):
        self.path,self.clock,self.max_age = Path(path),clock,max_age
        self.boot_id = str(uuid4())

    def mark(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(pid=os.getpid(),at=self.clock(),bootId=self.boot_id,maxAge=self.max_age)))
        temporary.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)


def healthy(path,*,now=None):
    try:
        value = json.loads(Path(path).read_text())
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

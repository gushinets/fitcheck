import json
import math
import os
import sys
from contextlib import contextmanager
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


@contextmanager
def _open_marker(path):
    if sys.platform != 'win32':
        with Path(path).open(encoding='utf-8') as stream:
            yield stream
        return

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    # GENERIC_READ, FILE_SHARE_READ | WRITE | DELETE, OPEN_EXISTING.
    # Python's ordinary open does not share delete access on Windows. A probe
    # must allow the writer's atomic replace and shutdown unlink while reading.
    handle = kernel32.CreateFileW(str(Path(path).absolute()), 0x80000000, 0x7,
        None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel32.CloseHandle(handle)
        raise
    # The CRT fd owns the handle after open_osfhandle succeeds.
    try:
        stream = os.fdopen(fd, encoding='utf-8')
    except BaseException:
        os.close(fd)
        raise
    with stream:
        yield stream


class WorkerHealth:
    def __init__(self,path,*,clock=time.time,max_age=45):
        self.path,self.clock,self.max_age = Path(path),clock,max_age
        self.boot_id = str(uuid4())

    def mark(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(pid=os.getpid(),at=self.clock(),bootId=self.boot_id,maxAge=self.max_age)),encoding='utf-8')
        temporary.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)


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

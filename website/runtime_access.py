"""Keep installed source unchanged while a native server can execute it.

Servers take shared ownership before importing application modules and release
it only after process cleanup. Publication stops authenticated servers first,
then takes exclusive ownership, then the ordinary financial cache lock. This
lock is separate from per-port launcher locks and the financial cache lock.
"""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time


def _windows_lock(handle, exclusive):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class Overlapped(ctypes.Structure):
        _fields_ = [('internal', ctypes.c_size_t), ('internal_high', ctypes.c_size_t),
                    ('offset', wintypes.DWORD), ('offset_high', wintypes.DWORD),
                    ('event', wintypes.HANDLE)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    lock = kernel.LockFileEx
    lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                     wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
    lock.restype = wintypes.BOOL
    unlock = kernel.UnlockFileEx
    unlock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                       wintypes.DWORD, ctypes.POINTER(Overlapped)]
    unlock.restype = wintypes.BOOL
    native = wintypes.HANDLE(msvcrt.get_osfhandle(handle.fileno()))
    region = Overlapped()
    if not lock(native, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(region)):
        error = ctypes.get_last_error()
        if error in (32, 33, 997):
            raise BlockingIOError(errno.EAGAIN, 'Source ownership is held.')
        raise ctypes.WinError(error)
    return lambda: unlock(native, 0, 1, 0, ctypes.byref(region))


@contextmanager
def ownership(root, *, exclusive=False, timeout=30, allow_pending=False):
    """Own source for execution or publication; fail closed on partial deploys."""
    root = Path(root)
    data = root / 'data'
    data.mkdir(parents=True, exist_ok=True)
    handle = (data / 'website-source.lock').open('a+b')
    release = None
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == 'nt':
                    release = _windows_lock(handle, exclusive)
                else:
                    import fcntl
                    fcntl.flock(handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                    release = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
                break
            except (BlockingIOError, OSError) as error:
                if error.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= deadline:
                    raise RuntimeError('The runtime still owns its source. Stop its terminal, then retry deployment.') from None
                time.sleep(min(.05, max(0, deadline - time.monotonic())))
        if not allow_pending and (data / 'deployment.pending.json').exists():
            raise RuntimeError('Source deployment is unfinished. Run tools/deploy.py again before starting the server.')
        yield
    finally:
        if release:
            release()
        handle.close()

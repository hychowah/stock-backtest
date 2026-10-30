"""Coordinate shared backtest files across threads and local server processes.

Lock order is process-local reentrant lock, project file lock, then database
connections and worker pools. Keep ownership until workers finish and database
connections close. Nested preparation in the same thread reuses ownership.
The build subprocess reads under its parent's ownership and does not acquire it.
"""
from contextlib import contextmanager
import errno
from functools import wraps
import os
from threading import RLock, local
import time

from paths import ROOT


class WorkspaceAccess:
    def __init__(self,path):
        self.path=path;self.lock=RLock();self.state=local()

    @contextmanager
    def hold(self,timeout=30):
        message='Another backtest or data operation owns the shared cache. Let it finish, then retry.'
        deadline=time.monotonic()+timeout
        if not self.lock.acquire(timeout=timeout):raise ValueError(message)
        handle=None;locked=False
        try:
            if getattr(self.state,'held',False):
                yield;return
            self.path.parent.mkdir(parents=True,exist_ok=True)
            handle=self.path.open('a+b')
            if not self.path.stat().st_size:handle.write(b'0');handle.flush()
            while True:
                try:
                    handle.seek(0)
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    locked=True;break
                except OSError as error:
                    if error.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):raise
                    if time.monotonic()>=deadline:raise ValueError(message) from None
                    time.sleep(min(.05,max(0,deadline-time.monotonic())))
            self.state.held=True
            try:yield
            finally:self.state.held=False
        finally:
            if locked:
                if os.name=='nt':
                    handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_UN)
            if handle:handle.close()
            self.lock.release()


workspace=WorkspaceAccess(ROOT/'data'/'website-data-0.lock')


def access(timeout=30):
    """Own all shared raw/prepared cache resources for one complete operation."""
    return workspace.hold(timeout)


def exclusive(function):
    """Keep standalone preparation under the same ownership as local servers."""
    @wraps(function)
    def guarded(*args,**kwargs):
        with access():return function(*args,**kwargs)
    return guarded


@contextmanager
def daily():
    """Open a daily database and retain ownership through its final close.

    Fixed schedules and random batches use this same boundary. Their worker
    pools must finish before leaving the context; workers do not acquire locks.
    """
    import schedules
    with access():
        db=schedules.connect()
        try:yield db
        finally:db.close()

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
import uuid

from backtest.paths import ROOT

# A source-bound observer requires this protocol, not a directory marker.
OBSERVATION_PROTOCOL = 1


class Contention(ValueError):
    """Ownership was not acquired before the admission deadline."""


def _file_lock(handle, acquire):
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, (fcntl.LOCK_EX | fcntl.LOCK_NB) if acquire else fcntl.LOCK_UN)


def _contended(error):
    return error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)


class WorkspaceAccess:
    def __init__(self,path, *, read_only=False):
        self.path=path;self.lock=RLock();self.state=local()
        # Read-only observers lock existing files. They never initialize files
        # or publish live intent. The ordinary ownership contract is unchanged.
        self.read_only = read_only

    @property
    def intents(self):
        return self.path.with_name(self.path.name + '.live')

    def live_pending(self):
        """Inspect OS-owned leases. Crashed owners leave inactive files.

        Inspection never waits for a live owner. Unknown/unreadable lease state
        defers observers. Only the creator removes a lease, after releasing it.
        """
        try:
            paths = list(self.intents.iterdir())
        except FileNotFoundError:
            return False
        except OSError:
            return True
        for path in paths:
            try:
                if path.is_symlink() or not path.is_file():
                    return True
                with path.open('rb' if self.read_only else 'r+b', buffering=0) as handle:
                    try:
                        _file_lock(handle, True)
                    except OSError:
                        return True
                    _file_lock(handle, False)
            except FileNotFoundError:
                continue
            except OSError:
                return True
        return False

    @contextmanager
    def _intent(self):
        self.intents.mkdir(parents=True, exist_ok=True)
        path = self.intents / (uuid.uuid4().hex + '.lease')
        handle = path.open('x+b', buffering=0)
        locked = False
        try:
            # Lock the byte even before its first write. This also covers a
            # crash during publication. A concurrent probe releases promptly.
            while not locked:
                try:
                    _file_lock(handle, True); locked = True
                except OSError as error:
                    if not _contended(error): raise
                    time.sleep(.001)
            handle.write(b'0')
            yield
        finally:
            try:
                if locked: _file_lock(handle, False)
            finally:
                handle.close()
                try: path.unlink()
                except FileNotFoundError: pass
                except PermissionError:
                    # Windows may still have a short-lived probe handle open.
                    # The closed lease is inactive and safe to leave behind.
                    pass

    @contextmanager
    def observe(self):
        """Borrow the coordinator without waiting; yield a conflict checkpoint.

        Normal operations announce intent before waiting for either lock.
        An observer must checkpoint between bounded work units and close its
        handles on conflict. This is cooperative handoff, not zero-delay access.
        Never nest an ordinary operation inside an observation.
        """
        def checkpoint():
            if self.live_pending():
                raise ValueError('Live work has priority over input observation.')
        checkpoint()
        if getattr(self.state, 'held', False):
            raise ValueError('Observation must own a separate request scope.')
        with self._hold(0):
            self.state.observing = True
            try:
                checkpoint()
                yield checkpoint
                checkpoint()
            finally:
                self.state.observing = False

    @contextmanager
    def hold(self,timeout=30):
        if self.read_only:
            raise ValueError('Read-only coordination supports observation only.')
        if getattr(self.state, 'observing', False):
            raise ValueError('Live operations cannot nest inside observations.')
        if getattr(self.state, 'held', False):
            with self._hold(timeout): yield
        else:
            # Announce before the local lock too, so waiting threads have the
            # same priority as independent processes. Keep intent through close.
            with self._intent():
                with self._hold(timeout): yield

    @contextmanager
    def _hold(self,timeout):
        message='Another backtest or data operation owns the shared cache. Let it finish, then retry.'
        deadline=time.monotonic()+timeout
        if not self.lock.acquire(timeout=timeout):raise Contention(message)
        handle=None;locked=False
        try:
            if getattr(self.state,'held',False):
                yield;return
            if not self.read_only:self.path.parent.mkdir(parents=True,exist_ok=True)
            handle=self.path.open('rb' if self.read_only else 'a+b')
            if not self.path.stat().st_size:
                if self.read_only:raise ValueError('Observation lock is not initialized.')
                handle.write(b'0');handle.flush()
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
                    if time.monotonic()>=deadline:raise Contention(message) from None
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
    from backtest.inputs import daily as daily
    with access():
        db=daily.connect()
        try:yield db
        finally:db.close()

"""Contain one experimental method process and all of its descendants.

Windows uses an owned Job Object. POSIX uses a new process session for tests.
The child waits for GO before attachment or creating workers. Native shutdown waits for job emptiness. Linux confirms cooperative session
closure and known descendants only; session escape prevention is unsupported.
"""
import ctypes
from contextlib import suppress
from dataclasses import dataclass
import json
import os
from queue import Empty, Full, Queue
import signal
import subprocess
from threading import Thread
import time

# Registration precedes process creation. A failed constructor can expose its
# retained owner on the original exception for adoption by a workspace owner.
_pending_processes = {}


@dataclass(frozen=True)
class ProcessLimits:
    """Bounds for known cooperative workers; not a filesystem/hostile-code sandbox.

    Native jobs enforce committed memory, active processes and CPU rate across
    ordinary descendants. Resident memory, disk and threads need separate
    qualification. POSIX sessions do not prevent descendant escape.
    """
    committed_bytes: int
    processes: int
    cpu_percent: int
    output_bytes: int = 1024 * 1024
    frame_bytes: int = 64 * 1024
    queued_events: int = 128
    close_seconds: float = 5.

    def __post_init__(self):
        if (any(type(v) is not int or v <= 0 for v in (self.committed_bytes,
                self.processes, self.cpu_percent, self.output_bytes, self.frame_bytes, self.queued_events))
                or self.cpu_percent > 100 or self.frame_bytes > self.output_bytes
                or not 0 < self.close_seconds <= 30):
            raise ValueError('Unsupported process limits.')


class OwnedProcess:
    def __init__(self, command, *, env=None, limits=None):
        self.job = None
        self.limits = limits
        self.output_bytes = 0
        self.failure = None
        self.eof = self.descendants_empty = False
        self.closed = False
        self._known = {}
        self.reader = None
        self.process = None
        self.events = Queue(maxsize=limits.queued_events if limits else 128)
        _pending_processes[id(self)] = self
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding='utf-8', errors='replace', bufsize=1, env=env,
                start_new_session=os.name!='nt',
                creationflags=0x4 if os.name == 'nt' else 0)  # CREATE_SUSPENDED
            if os.name == 'nt':
                self._assign_job()
                self._resume()
            self.reader = Thread(target=self._read, daemon=True)
            self.reader.start()
        except BaseException as error:
            if self.process is None:
                _pending_processes.pop(id(self), None)
                raise
            # Preserve the initialization exception while attempting complete
            # tree closure. Never let a second failure orphan this owner.
            with suppress(BaseException): self.terminate()
            with suppress(BaseException): self.close()
            if not self.closed:
                error.owned_process = self
            raise

    def _assign_job(self):
        from ctypes import wintypes as w
        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),
                ('flags',w.DWORD),('minimum_working_set',ctypes.c_size_t),
                ('maximum_working_set',ctypes.c_size_t),('active_limit',w.DWORD),
                ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class Counters(ctypes.Structure):
            _fields_ = [(name,ctypes.c_uint64) for name in
                        ('read_operations','write_operations','other_operations',
                         'read_bytes','write_bytes','other_bytes')]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic',BasicLimits),('io',Counters),
                ('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                ('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p,w.LPCWSTR)
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = (w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD)
        kernel.AssignProcessToJobObject.argtypes = (w.HANDLE,w.HANDLE)
        kernel.TerminateJobObject.argtypes = (w.HANDLE,w.UINT)
        kernel.QueryInformationJobObject.argtypes = (w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p)
        kernel.CloseHandle.argtypes = (w.HANDLE,)
        job = kernel.CreateJobObjectW(None,None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        self.kernel, self.job = kernel, job
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if self.limits is not None:
            limits.basic.flags |= 0x8 | 0x200  # active processes, job committed memory
            limits.basic.active_limit = self.limits.processes
            limits.job_memory = self.limits.committed_bytes
        try:
            if not kernel.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.AssignProcessToJobObject(job,w.HANDLE(int(self.process._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
            if self.limits is not None:
                class CpuRate(ctypes.Structure):
                    _fields_ = [('flags', w.DWORD), ('rate', w.DWORD)]
                cpu = CpuRate(0x1 | 0x4, self.limits.cpu_percent * 100)
                if not kernel.SetInformationJobObject(job, 15, ctypes.byref(cpu), ctypes.sizeof(cpu)):
                    raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            # Constructor failure uses the same registered closure path.
            raise

    def _resume(self):
        """Start the primary thread only after containment and limits exist.

        A Windows venv redirector can spawn the interpreter before Python reads
        GO. Suspending at process creation closes that pre-bootstrap race.
        Popen closes its original thread handle; reopen the unique primary
        thread of this still-suspended process through documented APIs.
        """
        from ctypes import wintypes as w
        class Entry(ctypes.Structure):
            _fields_ = [(name, w.DWORD) for name in ('size', 'usage', 'tid', 'pid')] + [
                ('base', w.LONG), ('delta', w.LONG), ('flags', w.DWORD)]
        kernel = self.kernel
        kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
        kernel.Thread32First.argtypes = kernel.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
        kernel.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenThread.restype = w.HANDLE
        kernel.ResumeThread.argtypes = [w.HANDLE]
        kernel.ResumeThread.restype = w.DWORD
        snapshot = kernel.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == w.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        identities = []
        try:
            entry = Entry(); entry.size = ctypes.sizeof(entry)
            present = kernel.Thread32First(snapshot, ctypes.byref(entry))
            while present:
                if entry.pid == self.process.pid: identities.append(entry.tid)
                present = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        if len(identities) != 1:
            raise OSError('Suspended experimental primary thread is unavailable.')
        handle = kernel.OpenThread(0x2, False, identities[0])  # THREAD_SUSPEND_RESUME
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        try:
            if kernel.ResumeThread(handle) != 1:
                raise OSError('Experimental primary thread was not suspended exactly once.')
        finally:
            kernel.CloseHandle(handle)

    def _read(self):
        try:
            frame = self.limits.frame_bytes if self.limits else 64 * 1024
            maximum = self.limits.output_bytes if self.limits else 8 * 1024 * 1024
            while True:
                # Bound allocations before JSON decoding, including no-newline
                # output. On overflow keep draining, never grow the queue.
                line = self.process.stdout.readline(frame + 1)
                if not line:
                    self.eof = True
                    break
                self.output_bytes += len(line.encode('utf-8'))
                if len(line.encode('utf-8')) > frame or self.output_bytes > maximum:
                    self.failure = 'limit'
                if self.failure:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    event = dict(event='worker_log',text=line.rstrip())
                if not isinstance(event, dict):
                    self.failure = 'protocol'; continue
                try:
                    self.events.put_nowait(event)
                except Full:
                    self.failure = 'limit'
        except (OSError, ValueError):
            self.failure = self.failure or 'child_failed'
        finally:
            # EOF is independent of queue capacity and the leader's exit.
            pass

    def start(self):
        self.process.stdin.write('GO\n')
        self.process.stdin.flush()
        self.process.stdin.close()

    def event(self, timeout=.25):
        if self.failure:
            return dict(event='failed', reason=self.failure)
        try:
            return self.events.get(timeout=timeout)
        except Empty:
            return None if self.eof else {}

    def terminate(self):
        if self.job is not None:
            if not self.kernel.TerminateJobObject(self.job,1):
                raise ctypes.WinError(ctypes.get_last_error())
        elif os.name != 'nt':
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid,signal.SIGKILL)
            # Include previously observed descendants that changed session.
            # Identity is the PID plus kernel start ticks, never a bare PID.
            for pid in self._session_members():
                with suppress(ProcessLookupError): os.kill(pid, signal.SIGKILL)
        if self.process.poll() is None:
            # Also covers a suspended root whose job assignment failed.
            self.process.kill()
        self.process.wait(timeout=self._close_seconds)
        self.wait_empty()

    @property
    def _close_seconds(self):
        return self.limits.close_seconds if self.limits else 30.

    def _session_members(self):
        """Confirm cooperative Linux session closure, including leader-first exit.

        This does not claim containment of processes that change session. Those
        guarantees are explicitly unsupported in the capability report.
        """
        from pathlib import Path
        rows = {}
        for path in Path('/proc').glob('[0-9]*/stat'):
            try:
                fields = path.read_text().rsplit(')', 1)[1].split()
                rows[int(path.parent.name)] = (int(fields[1]), int(fields[3]), fields[19], fields[0])
            except (FileNotFoundError, ProcessLookupError):
                continue
        members = {pid for pid, row in rows.items() if row[1] == self.process.pid
                   or self._known.get(pid) == row[2]}
        while True:
            expanded = members | {pid for pid, row in rows.items() if row[0] in members}
            if expanded == members: break
            members = expanded
        for pid in members:
            self._known[pid] = rows[pid][2]
            if rows[pid][1] != self.process.pid and rows[pid][3] != 'Z':
                self.failure = self.failure or 'unsupported'
        return [pid for pid in members if rows[pid][3] != 'Z']

    def wait_empty(self):
        if self.job is None:
            if os.name != 'nt':
                deadline = time.monotonic() + self._close_seconds
                while self._session_members():
                    if time.monotonic() > deadline:
                        raise TimeoutError('Experimental session closure is unconfirmed.')
                    time.sleep(.01)
                self.descendants_empty = True
            return
        from ctypes import wintypes as w
        class Accounting(ctypes.Structure):
            _fields_ = [(name,ctypes.c_int64) for name in
                        ('user_time','kernel_time','period_user','period_kernel')] + [
                        (name,w.DWORD) for name in
                        ('faults','total','active','terminated')]
        deadline = time.monotonic()+self._close_seconds
        while True:
            value = Accounting()
            if not self.kernel.QueryInformationJobObject(self.job,1,ctypes.byref(value),ctypes.sizeof(value),None):
                raise ctypes.WinError(ctypes.get_last_error())
            if value.active == 0:
                self.descendants_empty = True
                return
            if time.monotonic()>deadline:
                raise TimeoutError('Experimental descendants did not release their ownership.')
            time.sleep(.05)

    def tree_usage(self):
        """Sample every current job member, including orphaned ordinary children.

        Samples cannot establish instantaneous thread/resident-memory peaks.
        Linux session escape remains unsupported; no silent fallback to leader.
        """
        if os.name == 'nt':
            from ctypes import wintypes as w
            from bench_baseline import windows_processes
            size = self.limits.processes if self.limits else 512
            class Pids(ctypes.Structure):
                _fields_ = [('assigned', w.DWORD), ('count', w.DWORD),
                            ('pids', ctypes.c_size_t * size)]
            value = Pids()
            if self.job is None or not self.kernel.QueryInformationJobObject(
                    self.job, 3, ctypes.byref(value), ctypes.sizeof(value), None):
                raise OSError('Experimental process membership is unavailable.')
            rows = windows_processes(include_pids=value.pids[:value.count])
            return dict(processes=len(rows), threads=sum(row['threads'] for row in rows.values()),
                        resident_bytes=sum(row['working_set'] for row in rows.values()),
                        private_bytes=sum(row['private_bytes'] for row in rows.values()))
        from pathlib import Path
        rows = []
        for pid in self._session_members():
            try:
                fields = {}
                for line in (Path('/proc') / str(pid) / 'status').read_text().splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1); fields[key] = value.strip()
                rows.append((int(fields['Threads']), int(fields.get('VmRSS', '0 kB').split()[0]) * 1024))
            except (FileNotFoundError, ProcessLookupError):
                continue
        return dict(processes=len(rows), threads=sum(row[0] for row in rows),
                    resident_bytes=sum(row[1] for row in rows), private_bytes=None)

    def _close_handles(self):
        for stream in (self.process.stdin,self.process.stdout):
            if stream is not None and not stream.closed:
                stream.close()
        if self.job is not None:
            if not self.kernel.CloseHandle(self.job):
                raise ctypes.WinError(ctypes.get_last_error())
            self.job = None

    def _pipe_eof(self):
        """Windows nonblocking CRT reads can report EAGAIN at a broken pipe."""
        from ctypes import wintypes as w
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.PeekNamedPipe.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD,
                                        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        handle = w.HANDLE(msvcrt.get_osfhandle(self.process.stdout.fileno()))
        if kernel.PeekNamedPipe(handle, None, 0, None, None, None):
            return False
        code = ctypes.get_last_error()
        if code == 109: return True  # ERROR_BROKEN_PIPE confirms writer closure
        raise ctypes.WinError(code)

    def close(self):
        if self.closed:
            return
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=self._close_seconds)
            except subprocess.TimeoutExpired:
                self.terminate()
        if self.job is not None:
            # A broken method may have exited without closing its own workers.
            # They still belong to this job, even after the leader has exited.
            if not self.kernel.TerminateJobObject(self.job,0):
                raise ctypes.WinError(ctypes.get_last_error())
            self.wait_empty()
        elif os.name!='nt':
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid,signal.SIGKILL)
            for pid in self._session_members():
                with suppress(ProcessLookupError): os.kill(pid, signal.SIGKILL)
            self.wait_empty()
        if self.reader is not None and self.reader.ident is not None:
            self.reader.join(timeout=self._close_seconds)
        elif not self.eof:
            # Initialization can fail before the reader starts. Read bounded
            # bytes directly, without another thread or an unbounded wait.
            os.set_blocking(self.process.stdout.fileno(), False)
            deadline = time.monotonic() + self._close_seconds
            drained = 0
            while not self.eof:
                if time.monotonic() > deadline or drained > (self.limits.output_bytes if self.limits else 8 * 1024**2):
                    raise TimeoutError('Experimental output closure is unconfirmed.')
                try: part = os.read(self.process.stdout.fileno(), 64 * 1024)
                except BlockingIOError:
                    if os.name == 'nt' and self._pipe_eof():
                        self.eof = True
                    else: time.sleep(.01)
                    continue
                if not part: self.eof = True
                drained += len(part)
        if self.reader is not None and self.reader.is_alive():
            raise TimeoutError('Experimental process log reader did not close.')
        self._close_handles()
        self.closed = (self.process.poll() is not None and self.eof
                       and self.descendants_empty and self.job is None)
        if not self.closed:
            raise TimeoutError('Experimental closure is unconfirmed.')
        _pending_processes.pop(id(self), None)

    def capabilities(self):
        native = os.name == 'nt' and self.limits is not None
        def item(bound, status, mechanism):
            return dict(bound=bound, status=status, mechanism=mechanism,
                        scope='worker_and_ordinary_descendants_including_compiler')
        return dict(
            containment=item(None, 'hard' if os.name == 'nt' else 'unsupported',
                             'Windows job' if os.name == 'nt' else 'cooperative Linux session; escape possible'),
            committed_memory=item(self.limits.committed_bytes if self.limits else None,
                                  'hard' if native else 'unsupported', 'Windows job committed-memory limit'),
            processes=item(self.limits.processes if self.limits else None,
                           'hard' if native else 'unsupported', 'Windows job active-process limit'),
            cpu_rate=item(self.limits.cpu_percent if self.limits else None,
                         'hard' if native else 'unsupported', 'Windows job CPU hard cap'),
            resident_memory=item(None, 'unsupported', 'committed memory is not resident memory'),
            threads=item(None, 'unsupported', 'environment settings are not a hard thread limit'),
            disk=item(None, 'unsupported', 'directory sampling is not a quota'),
            transport=item(self.limits.output_bytes if self.limits else 8 * 1024 * 1024,
                           'hard', 'bounded frames, total bytes and pending event queue'))

    def closure(self):
        return dict(leader_exit=self.process.poll(), eof=self.eof,
                    reader_stopped=self.reader is None or not self.reader.is_alive(),
                    streams_closed=all(stream is None or stream.closed for stream in
                                       (self.process.stdin, self.process.stdout)),
                    descendants_empty=self.descendants_empty,
                    descendant_scope='job' if os.name == 'nt' else 'cooperative_session_only',
                    native_handles_released=self.job is None, closed=self.closed)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

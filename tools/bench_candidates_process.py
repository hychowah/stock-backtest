"""Contain one experimental method process and all of its descendants.

Windows uses an owned Job Object. POSIX uses a new process session for tests.
The child waits for GO before attachment or creating workers. Shutdown waits
for every owned descendant before the caller can release financial ownership.
"""
import ctypes
from contextlib import suppress
import json
import os
from queue import Empty, Queue
import signal
import subprocess
from threading import Thread
import time


class OwnedProcess:
    def __init__(self, command, *, env=None):
        self.job = None
        self.events = Queue()
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf-8', errors='replace', bufsize=1, env=env,
            start_new_session=os.name!='nt')
        try:
            if os.name == 'nt':
                self._assign_job()
            self.reader = Thread(target=self._read, daemon=True)
            self.reader.start()
        except BaseException:
            self.process.kill()
            self.process.wait()
            self._close_handles()
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
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if not kernel.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.AssignProcessToJobObject(job,w.HANDLE(int(self.process._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            kernel.CloseHandle(job)
            raise
        self.kernel, self.job = kernel, job

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    event = dict(event='worker_log',text=line.rstrip())
                self.events.put(event)
        finally:
            self.events.put(None)

    def start(self):
        self.process.stdin.write('GO\n')
        self.process.stdin.flush()
        self.process.stdin.close()

    def event(self, timeout=.25):
        try:
            return self.events.get(timeout=timeout)
        except Empty:
            return {}

    def terminate(self):
        if self.job is not None:
            if not self.kernel.TerminateJobObject(self.job,1):
                raise ctypes.WinError(ctypes.get_last_error())
        elif self.process.poll() is None:
            os.killpg(self.process.pid,signal.SIGKILL)
        self.process.wait(timeout=30)
        self.wait_empty()

    def wait_empty(self):
        if self.job is None:
            return
        from ctypes import wintypes as w
        class Accounting(ctypes.Structure):
            _fields_ = [(name,ctypes.c_int64) for name in
                        ('user_time','kernel_time','period_user','period_kernel')] + [
                        (name,w.DWORD) for name in
                        ('faults','total','active','terminated')]
        deadline = time.monotonic()+30
        while True:
            value = Accounting()
            if not self.kernel.QueryInformationJobObject(self.job,1,ctypes.byref(value),ctypes.sizeof(value),None):
                raise ctypes.WinError(ctypes.get_last_error())
            if value.active == 0:
                return
            if time.monotonic()>deadline:
                raise TimeoutError('Experimental descendants did not release their ownership.')
            time.sleep(.05)

    def _close_handles(self):
        for stream in (self.process.stdin,self.process.stdout):
            if stream is not None and not stream.closed:
                stream.close()
        if self.job is not None:
            self.kernel.CloseHandle(self.job)
            self.job = None

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=30)
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
        self.reader.join(timeout=30)
        if self.reader.is_alive():
            raise TimeoutError('Experimental process log reader did not close.')
        self._close_handles()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

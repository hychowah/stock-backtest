"""Persistent contained trial workers and explicit provisional-completion leases.

The session retains source/financial ownership. This pool never prepares inputs,
opens a financial coordinator, commits a checkpoint or accesses a user store.
Only one batch is active. Every submitted or unreleased task owns a fixed slot
and its full encoded-byte reservation until computation and file removal end.
"""
from contextlib import suppress
from copy import deepcopy
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import shutil
import subprocess
import sys
from threading import Thread
import time

import backtest_control
from numerical_execution import ExecutionPolicy
import numerical_trial
from numerical_runtime import ClosureError, encoded, write_payload
from process_owner import process_metrics
import trial_checkpoints

FRAME_BYTES = 16*1024
REQUEST_BYTES = 1024*1024
_PENDING = {}


class _Worker:
    def __init__(self, pool, index, launch):
        self.pool, self.index = pool, index
        self.process = self.reader = None
        self.parent_writer = None
        self.ready = None
        self.slot = None
        self.eof = False
        self.closed_event = False
        self._launch(launch)

    def _launch(self, launch):
        environment = dict(os.environ, NUMBA_NUM_THREADS=str(self.pool.policy.provider_limits['threads']),
            OMP_NUM_THREADS=str(self.pool.policy.provider_limits['threads']), OPENBLAS_NUM_THREADS='1',
            MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
        command = [self.pool.python, '-I', '-B', str(self.pool.root/'scripts'/'numerical_trial_worker.py'), str(launch)]
        startup = {}
        if os.name == 'nt':
            import ctypes as c
            from ctypes import wintypes as w
            kernel = c.WinDLL('kernel32', use_last_error=True)
            kernel.GetCurrentProcess.restype = w.HANDLE
            kernel.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE, c.POINTER(w.HANDLE),
                                               w.DWORD, w.BOOL, w.DWORD]
            kernel.CloseHandle.argtypes = [w.HANDLE]
            current, sentinel = kernel.GetCurrentProcess(), w.HANDLE()
            if not kernel.DuplicateHandle(current, current, current, c.byref(sentinel), 0x100000, True, 0):
                raise c.WinError(c.get_last_error())
            information = subprocess.STARTUPINFO()
            information.lpAttributeList = dict(handle_list=[sentinel.value])
            startup['startupinfo'] = information
            command += ['handle', str(sentinel.value)]
            try:
                self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, env=environment, **startup)
            finally: kernel.CloseHandle(sentinel)
        else:
            reader, self.parent_writer = os.pipe()
            command += ['pipe', str(reader)]
            try:
                self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, env=environment, pass_fds=(reader,))
            finally: os.close(reader)
        # No new session, process group or job. Native redirectors inherit the
        # runtime job and POSIX descendants remain in its existing session.
        self.reader = Thread(target=self._read, name='trial-response-'+str(self.index), daemon=True)
        self.reader.start()

    def _put(self, event):
        try: self.pool.events.put_nowait((self.index, event))
        except Full: self.pool.transport_failure = True

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(FRAME_BYTES+1)
                if not line: break
                if len(line) > FRAME_BYTES: self.pool.transport_failure = True; continue
                try: event = json.loads(line)
                except (ValueError, UnicodeError): self.pool.transport_failure = True; continue
                if type(event) is not dict: self.pool.transport_failure = True; continue
                if event.get('event') == 'closed': self.closed_event = True
                self._put(event)
        except (OSError, ValueError): self.pool.transport_failure = True
        finally:
            self.eof = True
            self._put(dict(event='eof'))

    def send(self, event):
        try:
            self.process.stdin.write(encoded(event, FRAME_BYTES-1)+b'\n')
            self.process.stdin.flush()
        except OSError:
            raise RuntimeError('Trial worker command transport failed.') from None


class Completion:
    """One validated artifact. Release removes owned bytes and its reservation."""
    def __init__(self, batch, slot, specification, event):
        self.batch, self.slot, self.specification = batch, slot, deepcopy(specification)
        self.number = specification['number']
        self.measurements = deepcopy(event.get('measurements', {}))
        self.work_and_seal_seconds = event.get('work_and_seal_seconds')
        self.flush_seconds = event.get('flush_seconds')
        self.stream = None
        self.released = False
        pool = batch.pool
        try:
            self.stream = pool._artifact_path(slot).open('rb')
            self.artifact = numerical_trial.open_artifact(self.stream, event['descriptor'],
                expected_spec=specification, limits=pool.policy.artifact_limits, checkpoint=pool.checkpoint)
        except BaseException:
            if self.stream is not None: self.stream.close()
            raise

    def release(self):
        if self.released: return
        self.stream.close()
        self.batch.pool._remove_slot(self.slot)
        self.batch.reservations.pop(self.slot)
        self.batch.completions.pop(self.slot, None)
        self.released = True
        self.batch.pool._reservation_stats(self.batch)


class Batch:
    def __init__(self, pool, specifications):
        self.pool = pool
        self.specifications = [numerical_trial._specification(spec) for spec in specifications]
        if not self.specifications or len(self.specifications) > 100:
            raise ValueError('Choose one to one hundred recorded trials.')
        if len({value['number'] for value in self.specifications}) != len(self.specifications):
            raise ValueError('Duplicate recorded trial number in a batch.')
        if len({value['calculation_identity'] for value in self.specifications}) != 1:
            raise ValueError('Recorded trials belong to different calculation identities.')
        self.reservations, self.completions = {}, {}
        self.next_task = self.completed_count = 0
        self.entered = self.iterated = self.finished = False

    def __enter__(self):
        if self.pool.active is not None: raise ValueError('Trial pool already has an active batch.')
        self.pool.checkpoint()
        if self.pool.closed or self.pool.poisoned: raise ValueError('Trial pool is closed or poisoned.')
        self.pool.active = self; self.entered = True
        try: self.pool.start(required_workers=min(self.pool.policy.workers, len(self.specifications)))
        except BaseException as error: self.pool._fail(error)
        return self

    def _admit(self):
        pool = self.pool
        for worker in pool.workers:
            pool.checkpoint()
            if worker.slot is not None or self.next_task == len(self.specifications): continue
            available = next((slot for slot in range(pool.policy.identity['pending_slots'])
                              if slot not in self.reservations), None)
            if available is None: break
            if shutil.disk_usage(pool.scratch).free < pool.policy.artifact_limits['max_bytes']:
                raise ValueError('Insufficient observed filesystem capacity for the next artifact reservation.')
            spec = self.specifications[self.next_task]
            self.reservations[available] = spec
            pool._reservation_stats(self)
            write_payload(pool._spec_path(available), spec, REQUEST_BYTES)
            worker.slot = available
            pool._send(worker, dict(command='trial', slot=available))
            self.next_task += 1

    def completed(self):
        if not self.entered or self.iterated: raise ValueError('Enter a batch and consume it once.')
        self.iterated = True
        try:
            while self.completed_count < len(self.specifications):
                self._admit()
                if not any(worker.slot is not None for worker in self.pool.workers):
                    raise ValueError('Release a completion before requesting more bounded work.')
                worker, event = self.pool._event()
                if self.pool._stage(worker,event): continue
                if event.get('event') != 'completed':
                    raise RuntimeError('Trial worker failed or returned an unexpected response.')
                if set(event) != {'event', 'slot', 'descriptor', 'work_and_seal_seconds',
                                  'flush_seconds', 'measurements'}:
                    raise ValueError('Malformed trial completion response.')
                slot = event['slot']
                if type(slot) is not int or slot != worker.slot or slot not in self.reservations:
                    raise ValueError('Trial worker returned a different reserved task slot.')
                completion = Completion(self, slot, self.reservations[slot], event)
                self.completions[slot] = completion
                worker.slot = None; self.completed_count += 1
                self.pool.stats['completed_trials'] += 1
                self.pool.stats['last_worker_measurements'][str(worker.index)] = completion.measurements
                yield completion
            self.finished = True
        except BaseException as error:
            self.pool._fail(error)

    def __exit__(self, kind, error, traceback):
        if error is not None or not self.finished:
            self.pool._fail(error or RuntimeError('Trial batch was abandoned before completion.'))
        try:
            for completion in list(self.completions.values()): completion.release()
        except BaseException as failure: self.pool._fail(failure)
        self.pool.active = None


class TrialPool:
    def __init__(self, *, source_root, scratch, reference, source_identity, compiler_identity,
                 policy, checkpoint=backtest_control.checkpoint, python=None):
        if not isinstance(policy, ExecutionPolicy): raise ValueError('Choose a resolved numerical execution policy.')
        self.root, self.scratch = Path(source_root).absolute(), Path(scratch).absolute()
        self.reference, self.source_identity = deepcopy(reference), deepcopy(source_identity)
        self.compiler_identity = deepcopy(compiler_identity)
        self.policy, self.checkpoint, self.python = policy, checkpoint, str(python or sys.executable)
        self.events = Queue(maxsize=policy.workers*3+1)
        self.workers = []
        self.active = None
        self.started = self.closed = self.poisoned = self.transport_failure = False
        self.stats = dict(started_workers=0, completed_trials=0, reserved_slots=0, reserved_bytes=0,
            peak_reserved_slots=0, peak_reserved_bytes=0, readiness=[], last_worker_measurements={},
            coordinator_process_sample=process_metrics(), worker_stages={})
        self.scratch.mkdir(parents=True, exist_ok=False)
        _PENDING[id(self)] = self

    @property
    def execution_identity(self):
        # Resource samples, timeouts and admission-only memory allowance are
        # deliberately absent. D binds this stable section to its checkpoints.
        return self.policy.execution_identity(self.compiler_identity)

    def _spec_path(self, slot): return self.scratch/('slot-'+str(slot)+'.json')
    def _artifact_path(self, slot): return self.scratch/('slot-'+str(slot)+'.evidence')

    def _send(self, worker, event): worker.send(event)

    def _event(self, deadline=None):
        while True:
            self.checkpoint()
            if self.transport_failure: raise RuntimeError('Bounded trial worker transport failed.')
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('Trial worker cold initialization exceeded its configured allowance.')
            try: index, event = self.events.get(timeout=.05)
            except Empty: continue
            if type(index) is not int or not 0 <= index < len(self.workers):
                raise ValueError('Unknown trial worker response owner.')
            return self.workers[index], event

    def _reservation_stats(self, batch):
        slots = len(batch.reservations)
        self.stats.update(reserved_slots=slots, reserved_bytes=slots*self.policy.artifact_limits['max_bytes'])
        for name in ('slots', 'bytes'):
            key = 'reserved_'+name
            self.stats['peak_'+key] = max(self.stats['peak_'+key], self.stats[key])

    def _stage(self, worker, event):
        if event.get('event') != 'stage': return False
        if set(event) != {'event','stage'} or event['stage'] not in (
                'source-owned','attaching','initializing','calculating'):
            raise ValueError('Invalid bounded trial worker stage.')
        self.stats['worker_stages'][str(worker.index)] = event['stage']
        return True

    def _remove_slot(self, slot):
        # Only fixed files created by this pool/worker can be removed.
        self._artifact_path(slot).unlink(missing_ok=True)
        self._spec_path(slot).unlink(missing_ok=True)

    def start(self, *, required_workers=None):
        self.checkpoint()
        if self.closed or self.poisoned: raise ValueError('Trial pool is closed or poisoned.')
        target = self.policy.workers if required_workers is None else required_workers
        if type(target) is not int or not 1 <= target <= self.policy.workers:
            raise ValueError('Invalid required worker count within declared pool capacity.')
        if len(self.workers) >= target: return self
        launch = self.scratch/'worker.json'
        configuration = dict(source_root=str(self.root), scratch=str(self.scratch), reference=self.reference,
            source=trial_checkpoints.digest(trial_checkpoints.canonical(self.source_identity)),
            provider_limits=self.policy.provider_limits, artifact_limits=self.policy.artifact_limits,
            slots=self.policy.identity['pending_slots'], close_seconds=self.policy.close_seconds)
        expected = dict(generation=self.reference['identity'], source=configuration['source'], backend='rust' if self.policy.backend=='rust' else 'numba',
                        compiler=self.compiler_identity['signature'], threads=self.policy.provider_limits['threads'])
        try:
            write_payload(launch, configuration, REQUEST_BYTES)
            # First readiness is the cold-cost probe. Do not duplicate an
            # unmeasured compiler/provider footprint just because CPUs exist.
            for index in range(len(self.workers), target):
                self.checkpoint()
                worker = _Worker.__new__(_Worker)
                self.workers.append(worker)  # Adopt before any constructor can fail.
                _Worker.__init__(worker, self, index, launch)
                deadline = time.monotonic()+self.policy.start_seconds
                while True:
                    owner, event = self._event(deadline)
                    if owner is not worker or not self._stage(owner,event): break
                if owner is not worker or event.get('event') != 'ready':
                    raise RuntimeError('Trial worker failed before readiness.')
                if any(event.get(key) != value for key, value in expected.items()):
                    raise ValueError('Trial worker readiness differs from its expected execution identity.')
                if type(event.get('pid')) is not int: raise ValueError('Invalid trial worker readiness PID.')
                worker.ready = deepcopy(event)
                self.stats['readiness'].append(deepcopy(event))
                self.stats['started_workers'] += 1
                if index == 0:
                    self.stats['cold_admission'] = self.policy.admit_cold_worker(event['measurements'])
            self.started = True
            return self
        except BaseException as error: self._fail(error)

    def batch(self, recorded_specifications): return Batch(self, recorded_specifications)

    def _fail(self, primary):
        self.poisoned = True
        try: self.close()
        except BaseException as cleanup:
            if isinstance(cleanup, ClosureError): cleanup.primary_error = primary; raise cleanup from primary
            raise ClosureError(self, primary, cleanup) from cleanup
        raise primary

    def close(self):
        if self.closed: return
        _PENDING[id(self)] = self
        try:
            (self.scratch/'cancel').touch(exist_ok=True)
            deadline = time.monotonic()+self.policy.close_seconds
            for worker in self.workers:
                if worker.parent_writer is not None:
                    os.close(worker.parent_writer); worker.parent_writer = None
                if worker.process is None: continue
                if worker.process.poll() is None:
                    with suppress(OSError, ValueError, RuntimeError): worker.send(dict(command='close'))
            for worker in self.workers:
                process = worker.process
                if process is None: continue
                try: process.wait(timeout=max(.001, deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    # Only this pool's contained child; never the application
                    # server. Its existing runtime remains the terminal owner.
                    process.kill(); process.wait(timeout=self.policy.close_seconds)
                if worker.reader is not None:
                    worker.reader.join(timeout=self.policy.close_seconds)
                    if worker.reader.is_alive(): raise TimeoutError('Trial response reader closure is unconfirmed.')
                if not worker.eof: raise TimeoutError('Trial worker transport EOF is unconfirmed.')
                for stream in (process.stdin, process.stdout):
                    if stream is not None and not stream.closed:
                        # A dead child can leave a buffered command. Its flush
                        # error is not a missing process/EOF/reader proof.
                        try: stream.close()
                        except OSError:
                            # Native buffered pipe close can raise EINVAL or a
                            # broken-pipe error after it has closed the handle.
                            # Require the actual closed state, not an errno.
                            if not stream.closed: raise
                if any(stream is not None and not stream.closed for stream in (process.stdin,process.stdout)):
                    raise TimeoutError('Trial worker stream closure is unconfirmed.')
                process.wait()
                if os.name == 'nt' and getattr(process, '_handle', None) is not None:
                    process._handle.Close()
            if self.active is not None:
                for completion in self.active.completions.values():
                    if completion.stream is not None: completion.stream.close()
                for slot in list(self.active.reservations): self._remove_slot(slot)
                self.active.reservations.clear(); self.active.completions.clear()
                self._reservation_stats(self.active)
            for index in range(self.policy.identity['pending_slots']): self._remove_slot(index)
            for index in range(self.policy.identity['pending_slots']):
                self._spec_path(index).with_suffix('.pending').unlink(missing_ok=True)
            for name in ('worker.json', 'worker.pending', 'cancel'):
                (self.scratch/name).unlink(missing_ok=True)
            self.scratch.rmdir()
            self.closed = True
            _PENDING.pop(id(self), None)
        except BaseException as error:
            raise ClosureError(self, cleanup_error=error) from error

    def measurements(self):
        return dict(**deepcopy(self.stats), policy=self.policy.diagnostics(), closed=self.closed,
                    poisoned=self.poisoned, worker_pids=[worker.process.pid for worker in self.workers
                                                       if worker.process is not None])

    def closure(self):
        return dict(closed=self.closed, workers=[dict(pid=worker.process.pid,
            exit=worker.process.poll(), eof=worker.eof,
            reader_stopped=worker.reader is None or not worker.reader.is_alive(),
            streams_closed=all(stream is None or stream.closed for stream in
                               (worker.process.stdin, worker.process.stdout)),
            native_handles_released=os.name != 'nt' or getattr(worker.process._handle, 'closed', False))
            for worker in self.workers if worker.process is not None])

"""Explicit, persistent numerical child; no application route or job service.

One active synchronous call, no backlog. Child holds source then financial
ownership through idle reuse. Closing confirms process/descendant/transport exit.
Never dispatch while the calling thread already owns the financial coordinator.
"""
from contextlib import suppress
from copy import deepcopy
import json
import math
import os
from pathlib import Path
from queue import Full, Queue
from threading import Event, Lock, RLock
import sys
import time
import numerical_transfer
from numerical_execution import ExecutionPolicy

from process_owner import OwnedProcess

MAX_REQUEST_BYTES = 1024*1024
MAX_PAYLOAD_BYTES = 64*1024**2
FRAME_BYTES = 16*1024
_PENDING = {}


def encoded(value, limit):
    payload = json.dumps(value,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(payload) > limit: raise ValueError('Numerical IPC payload exceeds its byte bound.')
    return payload


PUBLISH_RETRY_DELAYS = (.05, .1, .2, .4, .4, .4, .4)


def _pending_write(path, data):
    if os.name != 'nt':
        with path.open('wb') as handle:handle.write(data)
        return
    # CRT open can erase the original WinError and leave only EACCES. Preserve
    # the actual native denial class; never infer a sharing lock from errno 13.
    import ctypes as c
    from ctypes import wintypes as w
    import msvcrt
    kernel=c.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    kernel.CreateFileW.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE]
    native=kernel.CreateFileW(str(path),0x40000000,1,None,2,0x80,None)
    if native == c.c_void_p(-1).value:raise c.WinError(c.get_last_error())
    try:descriptor=msvcrt.open_osfhandle(native,os.O_WRONLY|os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(native);raise
    try:stream=os.fdopen(descriptor,'wb')
    except BaseException:
        os.close(descriptor);raise
    with stream:stream.write(data)


def write_payload(path, value, limit, *, checkpoint=None):
    """Publish one bounded complete protocol value atomically.

    Recognized Windows sharing failures receive bounded cancellable retries.
    Failure preserves prior published content and returns no completion indication.
    Diagnostics contain a source-owned role and phase, never arbitrary paths.
    """
    import backtest_control
    import diagnostics
    checkpoint = checkpoint or backtest_control.checkpoint
    data = encoded(value, limit)
    path = Path(path)
    temporary = path.with_suffix('.pending')
    roles = {'launch.json':'launch', 'request.json':'request', 'payload.json':'payload',
             'stats.json':'statistics', 'diagnostics.json':'diagnostics', 'worker.json':'worker-launch'}
    role = roles.get(path.name, 'trial-request' if path.name.startswith('slot-') else 'protocol')
    for attempt in range(len(PUBLISH_RETRY_DELAYS)+1):
        checkpoint()
        phase = 'pending-write'
        try:
            _pending_write(temporary,data)
            checkpoint()
            phase = 'replace'
            temporary.replace(path)
            return
        except OSError as error:
            details = dict(role=role, phase=phase, attempt=attempt+1,
                           exception=type(error).__name__, errno=error.errno,
                           winerror=getattr(error, 'winerror', None))
            error.numerical_publication = details
            retry = isinstance(error, PermissionError) and details['winerror'] in (5, 32, 33)
            diagnostics.event('numerical.publication_retry' if retry else 'numerical.publication_failed', **details)
            if not retry or attempt == len(PUBLISH_RETRY_DELAYS): raise
            deadline = time.monotonic()+PUBLISH_RETRY_DELAYS[attempt]
            while True:
                checkpoint()
                remaining = deadline-time.monotonic()
                if remaining <= 0: break
                time.sleep(min(.025, remaining))


def read_payload(path, limit):
    with path.open('rb') as handle: data = handle.read(limit+1)
    if len(data) > limit: raise ValueError('Numerical IPC payload exceeds its byte bound.')
    return json.loads(data)


class ClosureError(TimeoutError):
    """Cleanup is unconfirmed; retain the runtime and retry close explicitly.

    primary_error preserves the operation outcome but is not raised as Cancelled
    until closure is established. Application callers must not infer completion.
    """
    def __init__(self, runtime, primary_error=None, cleanup_error=None):
        super().__init__('Numerical cleanup is unconfirmed. Retry close after the active operation settles.')
        self.numerical_runtime = runtime
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error



class RuntimeProcess(OwnedProcess):
    """Keep containment; use finite frames/queue for a long-lived transport.

    Total diagnostic bytes are counted without a lifetime byte limit. Each
    frame is bounded before decode. One acknowledged callback is in flight.
    """
    def __init__(self, *args, close_seconds=30., **kwargs):
        self.close_seconds = close_seconds
        super().__init__(*args,**kwargs)

    @property
    def _close_seconds(self): return self.close_seconds

    def _created(self):
        self.events = Queue(maxsize=16)

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(FRAME_BYTES+1)
                if not line:
                    self.eof = True; break
                self.output_bytes += len(line.encode('utf-8'))
                if len(line.encode('utf-8')) > FRAME_BYTES:
                    self.failure = 'protocol'; continue
                try: event = json.loads(line)
                except ValueError:
                    self.failure = 'protocol'; continue
                if not isinstance(event,dict):
                    self.failure = 'protocol'; continue
                try: self.events.put_nowait(event)
                except Full: self.failure = 'protocol'
        except (OSError,ValueError): self.failure = self.failure or 'child_failed'

    def capabilities(self):
        result = super().capabilities()
        result['transport'].update(bound=FRAME_BYTES,
            mechanism='16 KiB frames and 16 pending events; no lifetime output byte cap')
        return result

    def start(self):
        self.process.stdin.write('GO\n'); self.process.stdin.flush()


class NumericalRuntime:
    """Explicit capability compatible with the shared calculate adapter.

    source_root must contain this source bootstrap. scratch must be a new private
    directory. session_factory is a trusted injected capability, never user form
    input. Tests can supply their own source-owned fictional Session factory.
    The parent retains this owner on failed closure; close() can be retried.
    """
    def __init__(self, *, source_root, scratch, generation_path=None, checkpoint_path=None,
                 threads=None, python=None, preparation_status=False, session_factory='numerical_session:Session',
                 session_options=None, coordinator=None, start_seconds=120., close_seconds=30.,preparation_profile=None):
        self.root, self.scratch = Path(source_root).absolute(), Path(scratch).absolute()
        options = deepcopy(session_options or {})
        policy = ExecutionPolicy.from_configuration(dict(options,threads=threads,start_seconds=start_seconds,close_seconds=close_seconds))
        threads = policy.provider_limits['threads']
        options['execution'] = policy.settings
        if preparation_profile is None:
            preparation_profile=policy.backend
        if preparation_profile is not None and preparation_profile!=policy.backend:
            raise ValueError('Runtime execution differs from its preparation profile.')
        if any(type(value) not in (int,float) or not math.isfinite(value) or value <= 0
               for value in (start_seconds,close_seconds)):
            raise ValueError('Invalid numerical lifecycle timeout.')
        self.coordinator = coordinator
        self.configuration = dict(source_root=str(self.root),scratch=str(self.scratch),threads=threads,
            generation_path=str(generation_path or self.root/'data'/'numerical'),
            checkpoint_path=str(checkpoint_path or self.root/'data'/'numerical-trials.sqlite'),
            cache_lock=str(coordinator.path if coordinator is not None else self.root/'data'/'website-data-0.lock'),
            preparation_status=preparation_status,session_factory=session_factory,session_options=options,
            preparation_profile=preparation_profile,
            execution_origin=dict(provenance=deepcopy(policy.provenance),observations=deepcopy(policy.observations)),
            close_seconds=close_seconds)
        encoded(self.configuration,MAX_REQUEST_BYTES)
        self.python = str(python or sys.executable)  # Never resolve a venv redirector/symlink.
        self.start_seconds,self.close_seconds = start_seconds,close_seconds
        self.state = 'new'
        self.owner = None
        self.diagnostics = []
        self.last_stats = {}
        self.last_stage = 'new'
        self._go_sent = False
        self._closure = RLock()
        self._call = Lock(); self._state = RLock(); self._write = Lock(); self._stop = Event()

    def _admit(self):
        coordinators = [self.coordinator]
        loaded = sys.modules.get('cache_access')
        if loaded is not None: coordinators.append(loaded.workspace)
        if any(value is not None and getattr(value.state,'held',False) for value in coordinators):
            raise ValueError('Release calling-thread financial ownership before numerical dispatch.')

    def _check_cancel(self,cancelled=None):
        import backtest_control
        backtest_control.checkpoint()
        if self._stop.is_set() or cancelled is not None and cancelled():
            raise backtest_control.Cancelled()

    def start(self, *, cancelled=None):
        self._admit()
        if not self._call.acquire(blocking=False):
            raise ValueError('Numerical runtime already has one active call.')
        try:
            try: return self._start_owned(cancelled)
            except BaseException as error:
                primary,secondary = self._observed_error(error,cancelled)
                self._raise_after_cleanup(primary,secondary)
        finally: self._call.release()

    def _observed_error(self,error,cancelled=None):
        # Stop can break a transport during startup or a stalled callback.
        # Observe the caller predicate before classifying that pipe failure.
        if isinstance(error,(OSError,RuntimeError)) and not isinstance(error,ClosureError):
            try: self._check_cancel(cancelled)
            except BaseException as observed: return observed,[error]
        return error,[]

    def _start_owned(self,cancelled=None):
        # The operation lock spans constructor creation, adoption and readiness.
        # close cannot report success while a constructor can still return an owner.
        self._check_cancel(cancelled)
        with self._state:
            if self.state == 'ready': return self
            if self.state != 'new': raise ValueError('Numerical runtime cannot start in its current state.')
            self.state = 'starting'
            _PENDING[id(self)] = self
        self.scratch.mkdir(parents=True,exist_ok=False)
        write_payload(self.scratch/'launch.json',self.configuration,MAX_REQUEST_BYTES)
        environment = dict(os.environ,NUMBA_NUM_THREADS=str(self.configuration['threads']),
            OMP_NUM_THREADS=str(self.configuration['threads']),OPENBLAS_NUM_THREADS='1',
            MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
        try:
            owner = RuntimeProcess([self.python,'-I','-B',str(self.root/'scripts'/'numerical_runtime_child.py'),
                                     str(self.scratch/'launch.json')],env=environment,close_seconds=self.close_seconds)
        except BaseException as error:
            with self._state: self.owner = getattr(error,'owned_process',None)
            raise
        with self._state: self.owner = owner
        self._check_cancel(cancelled)
        owner.start()
        self._go_sent = True
        deadline = time.monotonic()+self.start_seconds
        while True:
            self._check_cancel(cancelled)
            if time.monotonic() > deadline:
                raise TimeoutError('Numerical runtime initialization timed out at '+self.last_stage+'.')
            event = self._event()
            if event.get('event') == 'diagnostic': self._diagnostic(event); continue
            if event.get('event') == 'ready':
                self._check_cancel(cancelled)
                with self._state:
                    if self._stop.is_set() or self.state != 'starting':
                        import backtest_control
                        raise backtest_control.Cancelled()
                    self.last_stats = read_payload(self.scratch/'stats.json',MAX_REQUEST_BYTES) if event.get('stats') else {}
                    self.state = 'ready'
                return self
            if event.get('event') == 'error':
                if event.get('category') == 'contention':
                    import cache_access
                    raise cache_access.Contention('Another process owns the candidate financial cache.')
                raise ValueError(event.get('message','Numerical initialization failed.'))

    def _diagnostic(self,event):
        self.last_stage = str(event.get('stage','unknown'))[:128]
        self.diagnostics.append(event)
        if len(self.diagnostics)>128: del self.diagnostics[:-128]
        write_payload(self.scratch/'diagnostics.json',self.diagnostics,MAX_REQUEST_BYTES)

    def _send(self, event):
        data = encoded(event,FRAME_BYTES).decode('utf-8')+'\n'
        with self._write:
            self.owner.process.stdin.write(data); self.owner.process.stdin.flush()

    def _event(self):
        event = self.owner.event(.05)
        if event is None or event.get('event') == 'failed':
            raise RuntimeError('Numerical child exited or its bounded transport failed.')
        return event

    def inspect(self):
        """Inspect current preparation under the child's financial ownership."""
        deadline = time.monotonic() + 30
        return self.calculate('__inspect__', {}, cancelled=lambda: time.monotonic() >= deadline)

    def calculate(self, mode, options, progress=None, configuration=None, *, planned=None,
                  capture=None, cancelled=None):
        """Return the existing fixed/random payload after child calculation.

        Caller cancellation is optional and also respects backtest_control's
        current context. A callback failure cancels/drains the child before it
        propagates. Navigation policy stays with the caller, not this runtime.
        """
        return self._calculate(mode,options,progress,configuration,planned=planned,
            capture=capture,cancelled=cancelled)

    def calculate_into(self, mode, options, destination, progress=None, configuration=None, *, planned=None,
                       max_bytes, piece_bytes=1024*1024, record_bytes=8*1024*1024, cancelled=None):
        """Receive complete evidence into provisional caller-owned binary storage.

        No complete-trial capture is accepted here. The caller publishes only
        after success. Eager callers keep their existing request and graph limits.
        """
        import result_evidence
        if destination is None:raise ValueError('Choose an evidence destination.')
        result_evidence._limits(max_bytes,piece_bytes,record_bytes)
        return self._calculate(mode,options,progress,configuration,planned=planned,cancelled=cancelled,
            destination=destination,limits=dict(max_bytes=max_bytes,piece_bytes=piece_bytes,record_bytes=record_bytes))

    def _calculate(self, mode, options, progress, configuration, *, planned=None,
                   capture=None, cancelled=None, destination=None, limits=None):
        self._admit()
        if not self._call.acquire(blocking=False): raise ValueError('Numerical runtime already has one active call.')
        primary_error = None
        cancel_sent = False
        cancel_deadline = None
        try:
            if self.state == 'new': self._start_owned(cancelled)
            with self._state:
                if self.state != 'ready': raise ValueError('Numerical runtime is stopping or closed.')
            request = dict(mode=mode,options=deepcopy(options),
                planned=deepcopy(planned) if destination is None else None,capture=capture is not None)
            receiver=None
            if destination is not None:
                receiver=numerical_transfer.Receiver(destination,self.scratch,max_bytes=limits['max_bytes'],
                    checkpoint=lambda:self._check_cancel(cancelled))
                request.update(operation='evidence',limits=limits,planned=None,
                    plan_reference=numerical_transfer.stage_plan(self.scratch,planned,
                        lambda:self._check_cancel(cancelled)) if planned is not None else None)
            write_payload(self.scratch/'request.json',request,MAX_REQUEST_BYTES)
            with self._state:
                self._check_cancel(cancelled)
                if self.state != 'ready':raise ValueError('Numerical runtime is stopping or closed.')
                self.state = 'running'
            self._send(dict(command='calculate'))
            while True:
                try:
                    self._check_cancel(cancelled)
                except BaseException as error:
                    if primary_error is None: primary_error = error
                if primary_error is not None and not cancel_sent:
                    cancel_deadline = time.monotonic()+self.close_seconds
                    self._send(dict(command='cancel')); cancel_sent = True
                if cancel_deadline is not None and time.monotonic() > cancel_deadline:
                    raise TimeoutError('Numerical cancellation did not reach a checkpoint before closure.')
                event = self._event()
                kind = event.get('event')
                if not kind: continue
                if kind == 'diagnostic':
                    self._diagnostic(event)
                elif kind in ('configuration','progress','capture'):
                    try:
                        if primary_error is None:
                            value = read_payload(self.scratch/'payload.json',MAX_PAYLOAD_BYTES)
                            if kind == 'configuration' and configuration is not None: configuration(value)
                            elif kind == 'progress' and progress is not None: progress(value)
                            elif kind == 'capture' and capture is not None: capture(event['number'],value)
                    except BaseException as error:
                        if primary_error is None: primary_error = error
                    self._send(dict(command='ack'))
                elif kind in ('transfer_begin','transfer_piece','transfer_end') and receiver is not None:
                    if primary_error is not None:continue
                    try:
                        operation,sequence=receiver.accept(event)
                        if kind=='transfer_end':
                            receiver.finish()
                            import result_evidence
                            reader=result_evidence.Reader(destination,**limits,checkpoint=lambda:self._check_cancel(cancelled))
                    except BaseException as error:
                        # Caller-owned receiver failures have the same priority
                        # as progress/capture failures, including concurrent Stop.
                        primary_error=error
                        raise
                    self._check_cancel(cancelled)
                    self._send(dict(command='transfer_ack',operation=operation,sequence=sequence))
                elif kind in ('result','error','cancelled'):
                    self.last_stats = read_payload(self.scratch/'stats.json',MAX_REQUEST_BYTES) if event.get('stats') else {}
                    if primary_error is not None: raise primary_error
                    if kind == 'cancelled':
                        import backtest_control
                        raise backtest_control.Cancelled()
                    if kind == 'error' and event.get('category') == 'unavailable':
                        import backtest_jobs
                        raise backtest_jobs.Unavailable('Candidate inputs changed. Rebuild from the data panel.')
                    if kind == 'error': raise ValueError(event.get('message','Numerical calculation failed.'))
                    if receiver is not None:
                        transfer=receiver.finish()
                        result=dict(transfer=transfer,manifest=reader.manifest,metadata=reader.metadata)
                    else:result = read_payload(self.scratch/'payload.json',MAX_PAYLOAD_BYTES)
                    self._check_cancel(cancelled)
                    with self._state:
                        if self._stop.is_set() or self.state != 'running':
                            import backtest_control
                            raise backtest_control.Cancelled()
                        self.state = 'ready'
                    return result
                else: raise RuntimeError('Unknown numerical child event.')
        except BaseException as error:
            secondary = []
            if primary_error is None:
                primary_error,secondary = self._observed_error(error,cancelled)
            elif error is not primary_error: secondary.append(error)
            self._raise_after_cleanup(primary_error,secondary)
        finally:
            self._call.release()

    def _raise_after_cleanup(self,primary,secondary=()):
        try: self._close_owned()
        except BaseException as cleanup_error:
            # Cancellation is not a completed outcome while ownership is unknown.
            self.state = 'failed-closure'
            _PENDING[id(self)] = self
            failure = ClosureError(self,primary,cleanup_error)
            self._record_secondary(failure,[*secondary,cleanup_error])
            raise failure from cleanup_error
        self._record_secondary(primary,secondary)
        raise primary

    def _record_secondary(self,primary,secondary):
        if not secondary:return
        primary.runtime_secondary_errors = tuple(secondary[-8:])
        for error in secondary[-8:]:
            # Diagnostics must not replace the established operation outcome.
            with suppress(BaseException):
                self._diagnostic(dict(event='diagnostic',stage='cleanup-secondary',error_type=type(error).__name__))

    def _close_owned(self):
        with self._closure: self._finish_close()

    def _finish_close(self):
        # Caller holds the operation lock, so no late constructor/adoption exists.
        with self._state:
            if self.state == 'closed' and (self.owner is None or self.owner.closed): return
            self.state = 'stopping'; self._stop.set()
        if self.owner is not None:
            if self.owner.process.poll() is None:
                if not self._go_sent: self.owner.terminate()
                else:
                    with suppress(OSError,ValueError): self._send(dict(command='close'))
            try: self.owner.close()
            except BrokenPipeError as error:
                # An interrupted buffered write can raise while closing stdin,
                # after process/domain exit. Retry the COMPLETE owner proof;
                # this pipe error alone never establishes successful closure.
                self.owner.close()
                with suppress(BaseException):
                    self._diagnostic(dict(event='diagnostic',stage='cleanup-secondary',error_type=type(error).__name__))
        if self.scratch.exists():numerical_transfer.cleanup(self.scratch)
        with self._state: self.state = 'closed'
        _PENDING.pop(id(self),None)

    def close(self):
        with self._state:
            self._stop.set()
            if self.state != 'closed':
                self.state = 'stopping'; _PENDING[id(self)] = self
        if not self._call.acquire(timeout=self.close_seconds):
            # A constructor/callback can still be active. Retain this runtime
            # even if no owner has been adopted yet. Never claim terminal close.
            cleanup_error = None
            with self._closure:
                with self._state: owner = self.owner
                if owner is not None:
                    try: owner.terminate()
                    except BaseException as error: cleanup_error = error
            with self._state: self.state = 'failed-closure'
            _PENDING[id(self)] = self
            raise ClosureError(self,cleanup_error=cleanup_error)
        try:
            try: self._close_owned()
            except BaseException as error:
                with self._state: self.state = 'failed-closure'
                _PENDING[id(self)] = self
                raise ClosureError(self,cleanup_error=error) from error
        finally: self._call.release()

    def closure(self):
        return dict(state=self.state,process=self.owner.closure() if self.owner is not None else None)

    def __enter__(self): return self.start()
    def __exit__(self,*exc): self.close()

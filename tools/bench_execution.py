"""Own a complete disposable comparison; real measurement admission stays closed.

A source-bound cooperative observation provider is qualified only on disposable
participating fixtures. Declared limits and sampled enforcement do not qualify
a real three-gigabyte capture or installed website availability.
"""
from contextlib import suppress
from dataclasses import asdict, dataclass
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import sys
import time

import bench_admission as admission
from bench_comparison import ComparisonError, ComparisonLedger, ComparisonProtocol, digest, encoded
from bench_candidates_process import OwnedProcess, ProcessLimits
import bench_execution_inputs as inputs
from bench_execution_policy import _memory

# An unconfirmed child close must survive caller scope exit and garbage
# collection. Explicit successful closure is the only removal path.
_pending_measurements = {}


def environment(envelope):
    """Freeze interpreter/compiler versions and this operation's exact bounds."""
    return dict(python=sys.version, platform=sys.platform,
                packages={name: version(name) for name in ('numpy', 'numba', 'llvmlite')},
                envelope=asdict(envelope),
                tool_sources={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted(Path(__file__).parent.glob('bench_*.py'))})


@dataclass(frozen=True)
class ExecutionEnvelope:
    """Explicit comparison bounds. This declaration is never an admission token."""
    database_bytes: int
    output_bytes: int
    sampled_memory_bytes: int
    wall_seconds: float
    threads: int
    processes: int = 8
    cpu_percent: int = 25
    log_bytes: int = 1024 * 1024
    close_seconds: float = 5.
    sampled_tree_threads: int = 64

    def __post_init__(self):
        for value in (self.database_bytes, self.output_bytes, self.sampled_memory_bytes,
                      self.threads, self.sampled_tree_threads):
            if type(value) is not int or value <= 0:
                raise ComparisonError('unsupported')
        if (self.threads > 4 or type(self.wall_seconds) not in (int, float)
                or not math.isfinite(self.wall_seconds) or self.wall_seconds <= 0):
            raise ComparisonError('unsupported')
        try:
            self.process_limits()
        except ValueError:
            raise ComparisonError('unsupported') from None

    def process_limits(self):
        return ProcessLimits(self.sampled_memory_bytes, self.processes,
                             self.cpu_percent, output_bytes=self.log_bytes,
                             close_seconds=self.close_seconds)


class _ExecutionBudget(inputs._Budget):
    def __init__(self, cancel, envelope, started):
        super().__init__(cancel)
        self.envelope, self.started = envelope, started
        self.database_bytes, self.output_bytes = envelope.database_bytes, envelope.output_bytes

    def check(self, folder=None):
        if self.cancel():
            raise inputs.ExecutionInputError('cancelled')
        if (time.monotonic() - self.started > self.envelope.wall_seconds
                or inputs._memory_bytes() > self.envelope.sampled_memory_bytes):
            raise inputs.ExecutionInputError('limit')
        if folder is not None:
            total = 0
            for path in folder.rglob('*'):
                inputs._inside(folder, path.relative_to(folder).as_posix())
                try:
                    if path.is_file(): total += path.stat().st_size
                except FileNotFoundError:
                    # Owned SQLite journals can disappear between samples.
                    continue
            inputs._require(total <= self.output_bytes, 'limit')


class _ExecutionWorkspace(inputs.CapturedWorkspace):
    def __init__(self, *args, envelope, **kwargs):
        super().__init__(*args, **kwargs)
        self.envelope, self.started = envelope, time.monotonic()

    def _budget(self):
        return _ExecutionBudget(self.cancel, self.envelope, self.started)


class MeasurementExecution:
    """Own one isolated comparison and all resources through confirmed closure.

    Inputs, source, engines, private files, evidence and shutdown have one owner.
    Capture evidence is not current freshness. Successful fixture execution does
    not admit real measurements. No CLI, runtime locator or qualification flag
    can open admission. Tests patch admission only inside disposable fixtures.

    coordinated_observation_root requires participating, source-bound ownership.
    fixture_observation_root retains uncoordinated disposable legacy fixtures.
    Neither option opens admission or qualifies a production resource envelope.
    A comparison is single-use; a retry gets a new workspace and bracket.
    """
    def __init__(self, capture, source, output, protocol, envelope, *,
                 fixture_observation_root=None, coordinated_observation_root=None, cancel=None):
        self.capture, self.source, self.output = capture, source, output
        self.protocol, self.envelope = protocol, envelope
        if (fixture_observation_root is None) == (coordinated_observation_root is None):
            raise ComparisonError('unsupported')
        self.observation_root = coordinated_observation_root or fixture_observation_root
        self.observation_mode = 'coordinated' if coordinated_observation_root is not None else 'fixture'
        self.cancel = cancel or (lambda: False)
        self._workspace = self._owned = self._ledger = None
        self._active = self._used = False
        self._release = None
        self._policy_signature = None
        self._result = None
        self._finalized = False
        self._terminal_error = None
        self._child_failure = None
        self._entered = False
        self._priority = None
        self._resources = []
        self._peaks = dict(processes=0, threads=0, resident_bytes=0, private_bytes=0)

    def __enter__(self):
        # Reject before reading paths, loading a manifest, or creating output.
        admission.require_execution()
        if self._used or not isinstance(self.protocol, ComparisonProtocol) or not isinstance(self.envelope, ExecutionEnvelope):
            raise ComparisonError('unsupported')
        self._used = True
        declaration = self.protocol.value
        version = declaration.pop('version', None)
        if version != 1 or ComparisonProtocol.freeze(**declaration).identity != self.protocol.identity:
            raise ComparisonError('mismatch')
        if self.envelope.wall_seconds > declaration['whole_seconds']:
            raise ComparisonError('infeasible_costs')
        if declaration['environment'] != environment(self.envelope):
            raise ComparisonError('mismatch')
        self._ledger = ComparisonLedger(self.protocol)
        self._workspace = _ExecutionWorkspace(self.capture, self.source, self.output,
            envelope=self.envelope, cancel=self.cancel)
        try:
            began = time.monotonic()
            workspace = self._workspace.__enter__()
            self._entered = True
            _pending_measurements[id(self)] = self
            manifest = json.loads(workspace.manifest_bytes)
            self.binding = dict(capture_id=workspace.capture_id, financial_generation=workspace.identity,
                                sources=digest(manifest['originals']['sources']))
            if self.binding != self.protocol.value['binding']:
                raise ComparisonError('mismatch')
            observation = inputs._path(self.observation_root)
            if observation == workspace.capture or observation.is_relative_to(workspace.root):
                raise ComparisonError('unsupported')
            self.observation_root = observation
            if self.observation_mode == 'coordinated':
                # This reads verified coordination source only. Observation
                # itself remains in each timed child request.
                import cache_access
                expected = manifest['originals']['sources'].get('scripts/cache_access.py')
                if not expected or hashlib.sha256(Path(cache_access.__file__).read_bytes()).hexdigest() != expected:
                    raise ComparisonError('unsupported')
                self._priority = cache_access.WorkspaceAccess(observation / 'data/website-data-0.lock')
            self._tools = workspace._folder / 'tools'
            self._tools.mkdir()
            self._tool_hashes = {}
            for path in Path(__file__).parent.glob('bench_*.py'):
                data = path.read_bytes()
                self._tool_hashes[path.name] = hashlib.sha256(data).hexdigest()
                (self._tools / path.name).write_bytes(data)
                if hashlib.sha256(path.read_bytes()).hexdigest() != self._tool_hashes[path.name]:
                    raise ComparisonError('mismatch')
            if self._tool_hashes != declaration['environment']['tool_sources']:
                raise ComparisonError('mismatch')
            (workspace._folder / 'protocol.json').write_bytes(self.protocol.declaration)
            self._release = workspace._register_resource('measurement', self._close_child)
            self._ledger.charge('attachment', time.monotonic() - began)
            self._active = True
            self._persist('attached')
            return self
        except BaseException:
            error = sys.exc_info()
            self.__exit__(*error)
            raise

    def _check(self):
        if not self._active:
            raise ComparisonError('inactive')
        if self.cancel():
            raise ComparisonError('cancelled')
        if self._priority is not None and self._priority.live_pending():
            raise ComparisonError('busy')
        self._ledger.check()
        self._workspace._budget().check(self._workspace._folder)

    def _persist(self, status, error=None):
        if self._workspace is None or not hasattr(self._workspace, '_folder'):
            return
        value = dict(status=status, scope='disposable_fixture', execution_admission='unavailable',
            production_freshness='cooperative_source_only' if self._priority else 'unavailable',
            production_resources='unqualified', resource_records=self._resources,
            envelope=asdict(self.envelope),
            resource_observation='controller_and_leader_sampled; native_job_limits_when_available',
            protocol=self.protocol.identity, costs=dict(self._ledger.costs), events=list(self._ledger.events))
        value['step_costs'] = self._ledger.step_costs
        if error is not None:
            value.update(reason=getattr(error, 'reason', 'unexpected'), error_type=type(error).__name__)
        if self._child_failure is not None:
            value['child_failure'] = dict(self._child_failure)
        if self._result is not None:
            value['result'] = self._result
        target = self._workspace._folder / 'comparison.json'
        temporary = target.with_suffix('.building')
        temporary.write_bytes(encoded(value))
        temporary.replace(target)

    def _command(self, request):
        return [sys.executable, '-I', '-B', '-c',
            'import runpy,sys; sys.path.insert(0,sys.argv[1]); '
            'runpy.run_module("bench_execution_worker",run_name="__main__")',
            str(self._tools), str(request)]

    def _close_child(self):
        if self._owned is None:
            return
        owned = self._owned
        failure = None
        for attempt in range(2):
            try:
                if owned.process.poll() is None:
                    owned.terminate()
                owned.close()
            except BaseException as error:
                failure = failure or error
            if owned.closed:
                self._resources.append(dict(capabilities=owned.capabilities(), closure=owned.closure()))
                self._resources[-1]['sampled_peaks'] = dict(self._peaks)
                self._owned = None
                return
        raise ComparisonError('closure_pending') from failure

    def _step(self, step, reference):
        self._check()
        self._ledger.begin(step)
        self._persist('running')
        workspace = self._workspace
        folder = workspace._folder / step
        folder.mkdir()
        began = time.monotonic()
        with workspace.writable_daily() as daily:
            for table in inputs.artifacts.DERIVED:
                daily.execute('DELETE FROM ' + table)
            daily.commit()
            database = Path(daily.execute('PRAGMA database_list').fetchone()[2])
        self._ledger.charge('clone', time.monotonic() - began)
        request = dict(version=1, step=step, database=str(database),
            capture=str(workspace.capture), source=str(workspace.source_snapshot),
            sources=json.loads(workspace.manifest_bytes)['originals']['sources'],
            tools=self._tool_hashes, binding=self.binding,
            configuration=self.protocol.value['configuration'],
            observation_root=str(self.observation_root),
            observation_mode=self.observation_mode,
            captured_freshness=workspace.captured_freshness,
            captured_metadata=workspace.captured_metadata,
            reference=reference, threads=self.envelope.threads)
        request['request_budget'] = self._ledger.remaining('request')
        request_path = folder / 'request.json'
        request_path.write_bytes(encoded(request))
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith('BACKTEST_BASELINE_')}
        for name in ('NUMBA_NUM_THREADS', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                     'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            environment[name] = str(self.envelope.threads)
        environment.update(PYTHONDONTWRITEBYTECODE='1', NUMBA_CACHE_DIR=str(folder / 'compiler'),
                           MPLCONFIGDIR=str(folder / 'config'))
        temporary = folder / 'temporary'; temporary.mkdir()
        environment.update(TMPDIR=str(temporary), TEMP=str(temporary), TMP=str(temporary))
        phase_started = time.monotonic()
        try:
            self._owned = OwnedProcess(self._command(request_path), env=environment,
                                       limits=self.envelope.process_limits())
        except BaseException as error:
            self._owned = getattr(error, 'owned_process', None)
            raise
        self._owned.start()
        eof = False
        phases = ('setup', 'proof', 'request', 'collection', 'shutdown')
        phase_index = 0
        final = None
        while True:
            self._check()
            elapsed = time.monotonic() - phase_started
            allocation = self._ledger.remaining(phases[phase_index])
            if elapsed > allocation:
                raise ComparisonError('limit')
            code = self._owned.process.poll()
            usage = self._owned.tree_usage()
            for key, value in usage.items():
                if value is not None: self._peaks[key] = max(self._peaks[key], value)
            if (usage['processes'] > self.envelope.processes
                    or usage['threads'] > self.envelope.sampled_tree_threads
                    or usage['resident_bytes'] > self.envelope.sampled_memory_bytes):
                raise ComparisonError('limit')
            if code is None:
                try:
                    if _memory(self._owned.process.pid) > self.envelope.sampled_memory_bytes:
                        raise ComparisonError('limit')
                except OSError:
                    if self._owned.process.poll() is None:
                        raise ComparisonError('limit') from None
            event = self._owned.event(timeout=.02)
            if event is None:
                eof = True
            elif event:
                if event.get('event') == 'failed':
                    self._child_failure = dict(reason=event.get('reason', 'child_failed'),
                                               error_type=event.get('error_type', 'Exception'))
                    raise ComparisonError(event.get('reason', 'child_failed'))
                if event.get('event') == 'phase':
                    if event.get('name') != phases[phase_index] or phase_index >= len(phases) - 1:
                        raise ComparisonError('protocol')
                    self._ledger.charge(phases[phase_index], time.monotonic() - phase_started)
                    phase_index += 1
                    phase_started = time.monotonic()
                elif event.get('event') == 'complete':
                    if final is not None or phase_index != 4:
                        raise ComparisonError('protocol')
                    final = event
                else:
                    raise ComparisonError('protocol')
            if code is not None and eof:
                if code or final is None:
                    raise ComparisonError('child_failed')
                break
        self._close_child()
        self._ledger.charge('shutdown', time.monotonic() - phase_started)
        self._check()
        value = json.loads((folder / 'result.json').read_bytes())
        if final['sha256'] != digest(value) or value['binding'] != self.binding:
            raise ComparisonError('mismatch')
        if self._policy_signature is None:
            self._policy_signature = value['policy_signature']
        if value['policy_signature'] != self._policy_signature:
            raise ComparisonError('mismatch')
        self._ledger.finish(step, dict(financial_agreement=value['financial_agreement'], closed=True,
            request_seconds=value['request_seconds'], evidence_sha256=final['sha256']))
        self._persist('running')
        return dict(path=str(folder / 'result.json'), sha256=final['sha256'])

    def compare(self):
        self._check()
        if self._ledger.events:
            raise ComparisonError('inactive')
        reference = None
        try:
            for step in self.protocol.value['order']:
                result = self._step(step, reference)
                if reference is None:
                    reference = result
            self._persist('awaiting_closure')
            return self
        except BaseException as error:
            self._ledger.stop(getattr(error, 'reason', 'unexpected'))
            with suppress(OSError):
                self._persist('stopped', error)
            raise

    @property
    def result(self):
        if self._result is None or not self._finalized or self._ledger.stopped:
            raise ComparisonError('incomplete')
        return json.loads(encoded(self._result))

    def __exit__(self, kind, error, traceback):
        if not self._entered:
            return False
        # A cleanup retry can finish closure, but cannot erase a failed body.
        if error is not None and self._terminal_error is None:
            self._terminal_error = error
            self._ledger.stop(getattr(error, 'reason', 'unexpected'))
            self._result = None
        terminal = self._terminal_error
        began = time.monotonic()
        try:
            self._close_child()
        except BaseException as close_error:
            with suppress(OSError):
                self._persist('closure_pending', close_error)
            # Registered resource retains workspace ownership until explicit retry.
            if error is None:
                raise
            return False
        if self._release:
            self._release()
        self._active = False
        try:
            self._workspace.__exit__(type(terminal) if terminal else kind,
                                     terminal or error, terminal.__traceback__ if terminal else traceback)
            self._entered = False
            _pending_measurements.pop(id(self), None)
        except BaseException as close_error:
            self._persist('stopped', close_error)
            raise
        if terminal is None:
            try:
                self._ledger.charge('finalization', time.monotonic() - began)
                self._result = self._ledger.result(closed=True)
                self._persist('complete')
                self._finalized = True
            except BaseException as failure:
                self._result = None
                self._terminal_error = failure
                self._ledger.stop(getattr(failure, 'reason', 'unexpected'))
                with suppress(OSError):
                    self._persist('stopped', failure)
                raise
        else:
            with suppress(OSError):
                self._persist('stopped', terminal)
        return False

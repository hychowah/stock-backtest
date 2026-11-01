"""Own source-only policy attachment; no calculation or freshness protocol.

The child imports actual private application source. Its process contains import
side effects. A binding is captured provenance, never permission to run an engine.
"""
from contextlib import suppress
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import re
import sys
import time
from types import MappingProxyType
import uuid

if __name__ != '__main__':
    from bench_candidates_process import OwnedProcess
import bench_execution_inputs as inputs_module
import bench_input_artifacts as artifacts
from bench_input_store import _memory_bytes

MAX_CHILD_MEMORY = 128 * 1024 ** 2
MAX_ATTACH_SECONDS = 10.
_SUPPORT = ('bench_execution_policy.py', 'bench_policy_program.py',
            'bench_candidates_policy.py', 'bench_candidates_process.py',
            'bench_execution_inputs.py', 'bench_input_artifacts.py', 'bench_input_store.py')
_SHA = re.compile(r'[0-9a-f]{64}')
_REASONS = frozenset(('inactive', 'incomplete', 'unsupported', 'mismatch',
                     'cancelled', 'limit', 'protocol', 'child_failed'))


class ExecutionPolicyError(ValueError):
    """Expected attachment failure with a stable sanitized reason."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Execution policy: ' + reason)


def _require(value, reason='protocol'):
    if not value:
        raise ExecutionPolicyError(reason)


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _memory(pid):
    """Sample the owned child's current memory, not its transient peak."""
    if os.name != 'nt':
        return int(Path(f'/proc/{pid}/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    import ctypes
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_ = [('cb', w.DWORD), ('faults', w.DWORD)] + [(name, ctypes.c_size_t)
            for name in ('peak', 'working', 'pool_peak', 'pool', 'nonpaged_peak',
                         'nonpaged', 'pagefile', 'pagefile_peak')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    psapi.GetProcessMemoryInfo.argtypes = (w.HANDLE, ctypes.c_void_p, w.DWORD)
    handle = kernel.OpenProcess(0x1010, False, pid)
    if not handle:
        raise OSError('Child memory unavailable')
    try:
        value = Counters(); value.cb = ctypes.sizeof(value)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(value), value.cb):
            raise OSError('Child memory unavailable')
        return value.working
    finally:
        kernel.CloseHandle(handle)


def _verify_sources(root, sources):
    _require(isinstance(sources, dict) and bool(sources), 'incomplete')
    by_name = {}
    for relative, expected in sources.items():
        try:
            path = inputs_module._inside(root, relative)
        except inputs_module.ExecutionInputError as error:
            raise ExecutionPolicyError('unsupported') from error
        _require(path.is_file(), 'incomplete')
        _require(_hash(path) == expected, 'mismatch')
        parts=list(Path(relative).parts)
        name = ('.'.join(parts[:-1] if parts[-1]=='__init__.py' else [*parts[:-1],path.stem]) if parts[0]=='backtest' else path.stem)
        _require(name not in by_name, 'unsupported')
        by_name[name] = path
    return by_name


def _validate_binding(value, request):
    _require(isinstance(value, dict) and set(value) ==
        {'version', 'capture_id', 'financial_generation', 'policy_signature',
         'policy_sources', 'identity'})
    _require(type(value['version']) is int and value['version'] == 1)
    for name in ('capture_id', 'financial_generation'):
        _require(value[name] == request[name], 'mismatch')
    _require(isinstance(value['policy_signature'], str) and _SHA.fullmatch(value['policy_signature']))
    sources = value['policy_sources']
    expected_paths = {'backtest/financial/books.py','backtest/financial/metrics.py','backtest/financial/rules.py','backtest/screening.py','scripts/research.py','scripts/revalue.py','scripts/run.py','scripts/schedules.py'}
    _require(isinstance(sources, dict) and set(sources) == expected_paths, 'unsupported')
    _require(all(request['sources'].get(name) == sha for name, sha in sources.items()), 'mismatch')
    payload = {key: item for key, item in value.items() if key != 'identity'}
    _require(value['identity'] == artifacts.digest(payload), 'mismatch')
    return value


class CapturedPolicy:
    """Own one source-only policy process for an active captured workspace.

    The process constructs the actual PolicyProgram from verified private source.
    Its binding describes captured source and financial identity. It does not
    validate current raw freshness, load candidate inputs, execute financial
    requests, admit benchmarks or qualify general execution isolation.

    One use per instance. No financial command or original-runtime locator is
    accepted. Outer workspace closure also closes an escaped policy scope.
    """
    def __init__(self, inputs):
        _require(isinstance(inputs, inputs_module.CapturedWorkspace), 'unsupported')
        self._inputs = inputs
        self._used = self._active = False
        self._owned = self._folder = self._binding = None
        self.exit_code = None
        self._closed = False
        self._release = None
        self._program_evidence = None

    def _check(self):
        _require(self._inputs._active and not self._closed, 'inactive')
        if self._inputs.cancel and self._inputs.cancel():
            raise ExecutionPolicyError('cancelled')

    @property
    def binding(self):
        self._check()
        _require(self._active, 'inactive')
        _require(self._owned.process.poll() is None, 'child_failed')
        return self._binding

    def _record(self, status, error=None):
        if self._folder is None:
            return
        value = dict(status=status, current_raw_freshness='unavailable',
                     execution_admission='unavailable', exit_code=self.exit_code)
        if self._binding is not None:
            value['binding_identity'] = self._binding['identity']
        if self._program_evidence is not None:
            value['program_evidence'] = self._program_evidence
        if error is not None:
            value.update(reason=error.reason if isinstance(error, ExecutionPolicyError) else 'unexpected',
                         error_type=type(error).__name__)
        try:
            (self._folder / 'attempt.json').write_bytes(artifacts.encoded(value))
        except OSError:
            if error is None:
                raise

    def __enter__(self):
        _require(not self._used, 'inactive')
        self._used = True
        self._check()
        try:
            self._release = self._inputs._register_resource('policy', self.close)
            return self._attach()
        except inputs_module.ExecutionInputError as error:
            translated = ExecutionPolicyError('inactive' if error.reason == 'busy' else
                error.reason if error.reason in _REASONS else 'incomplete')
            with suppress(BaseException): self.close(translated)
            raise translated from error
        except (FileNotFoundError, NotADirectoryError, UnicodeDecodeError, json.JSONDecodeError) as error:
            translated = ExecutionPolicyError('incomplete')
            with suppress(BaseException): self.close(translated)
            raise translated from error
        except BaseException as error:
            with suppress(BaseException): self.close(error)
            raise

    def _attach(self):
        budget = inputs_module._Budget(self._inputs.cancel)
        manifest = json.loads(self._inputs.manifest_bytes)
        sources = manifest['originals']['sources']
        root = self._inputs.source_snapshot
        _verify_sources(root, sources)
        self._folder = inputs_module._inside(self._inputs._folder, 'policy-' + uuid.uuid4().hex)
        self._folder.mkdir()
        support = self._folder / 'tools'; support.mkdir()
        hashes = {}
        origin = Path(__file__).resolve().parent
        for name in _SUPPORT:
            self._check(); budget.check(self._inputs._folder)
            data = (origin / name).read_bytes()
            hashes[name] = hashlib.sha256(data).hexdigest()
            target = support / name
            target.write_bytes(data)
            _require(_hash(origin / name) == hashes[name] == _hash(target), 'mismatch')
        self._request = dict(version=1, capture_id=manifest['capture_id'],
            financial_generation=manifest['financial_generation'], source=str(root),
            sources=sources, tools=hashes)
        request = self._folder / 'request.json'
        request.write_bytes(artifacts.encoded(self._request))
        self._sources, self._support = sources, hashes
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith('BACKTEST_BASELINE_')}
        environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONWARNINGS='error::ResourceWarning')
        command = [sys.executable, '-I', '-B', '-W', 'error::ResourceWarning',
                   '-c', 'import runpy,sys; sys.path.insert(0,sys.argv[1]); '
                   'runpy.run_module("bench_execution_policy",run_name="__main__")',
                   str(support), str(request)]
        try:
            try:
                self._owned = OwnedProcess(command, env=environment)
            except BaseException as error:
                self._owned = getattr(error, 'owned_process', None)
                raise
        except OSError as error:
            raise ExecutionPolicyError('child_failed') from error
        self._owned.start()
        event = self._monitor()
        _require(set(event) == {'event', 'binding', 'modules', 'memory_bytes', 'program_evidence'}, 'protocol')
        _require(event['event'] == 'attached', 'protocol')
        _require(type(event['memory_bytes']) is int and 0 < event['memory_bytes'] <= MAX_CHILD_MEMORY, 'limit')
        modules = event['modules']
        _require(isinstance(modules, dict) and bool(modules), 'incomplete')
        _require(all(sources.get(name) == sha for name, sha in modules.items()), 'mismatch')
        _require({'scripts/schedules.py', 'scripts/research.py', 'backtest/financial/metrics.py',
                  'backtest/financial/books.py', 'scripts/run.py', 'scripts/revalue.py'} <= modules.keys(), 'incomplete')
        self._binding = _freeze(_validate_binding(event['binding'], self._request))
        evidence = event['program_evidence']
        _require(isinstance(evidence, dict) and set(evidence) ==
            {'signature', 'expressions', 'python', 'decisions', 'statuses', 'sources', 'constants', 'bankruptcy'}, 'protocol')
        _require(evidence['signature'] == self._binding['policy_signature'] and
            evidence['sources'] == dict(self._binding['policy_sources']), 'mismatch')
        self._program_evidence = evidence
        self._active = True
        self._record('attached')
        return self

    def _monitor(self):
        """EOF and process exit are independent; neither consumes the other."""
        began = time.monotonic()
        eof = False
        while True:
            self._check()
            if time.monotonic() - began > MAX_ATTACH_SECONDS:
                raise ExecutionPolicyError('limit')
            code = self._owned.process.poll()
            if code is not None:
                self.exit_code = code
            if code is None:
                try:
                    _require(_memory(self._owned.process.pid) <= MAX_CHILD_MEMORY, 'limit')
                except OSError as error:
                    if self._owned.process.poll() is None:
                        raise ExecutionPolicyError('limit') from error
            event = self._owned.event(timeout=.02)
            if event is None:
                eof = True
            elif event:
                _require(isinstance(event, dict), 'protocol')
                if event.get('event') == 'failed':
                    reason = event.get('reason')
                    raise ExecutionPolicyError(reason if isinstance(reason, str) and reason in _REASONS else 'protocol')
                _require(event.get('event') == 'attached', 'protocol')
                _require(code is None, 'child_failed')
                return event
            if code is not None and eof:
                raise ExecutionPolicyError('child_failed')

    def _closure_confirmed(self):
        owned = self._owned
        return owned is None or owned.closed

    def close(self, error=None):
        """Release ownership only after the child, reader and handles close.

        Signalling and evidence errors remain reportable, but cannot skip reaping.
        An unconfirmed close keeps its registration and can be retried. The
        enclosing workspace also retains ownership until that retry succeeds.
        """
        if self._closed:
            return
        self._active = False
        failure = None
        if self._owned is not None:
            try:
                (self._folder / 'stop').touch()
            except BaseException as caught:
                failure = caught
            force = error is not None or failure is not None
            # A partial OwnedProcess.close may fail after terminating the child
            # but before reader/handle closure. Retry that same owner's cleanup.
            for attempt in range(2):
                if force or attempt:
                    try:
                        self._owned.terminate()
                    except BaseException as caught:
                        failure = failure or caught
                try:
                    self._owned.close()
                except BaseException as caught:
                    failure = failure or caught
                if self._closure_confirmed():
                    break
                force = True
            self.exit_code = self._owned.process.returncode
        if not self._closure_confirmed():
            failure = failure or ExecutionPolicyError('child_failed')
            self._record('closure_pending', failure)
            raise failure
        # Files and attachment registration are released only after actual close.
        self._closed = True
        if self._release is not None:
            self._release()
        try:
            if self._owned is not None and error is None and failure is None:
                _require(self.exit_code == 0, 'child_failed')
                _verify_sources(self._inputs.source_snapshot, self._sources)
                for name, sha in self._support.items():
                    _require(_hash(self._folder / 'tools' / name) == sha, 'mismatch')
            self._record('failed' if error or failure else 'complete', error or failure)
        except BaseException as caught:
            self._record('failed', caught)
            raise
        if failure is not None:
            raise failure

    def __exit__(self, kind, error, traceback):
        if error is None:
            self.close()
        else:
            # Cleanup errors cannot replace an exception from the caller's body.
            with suppress(BaseException):
                self.close(error)
        return False


class _SourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        # Execute the verified source itself. Never consult a bytecode cache.
        return self.source_to_code(self.get_data(self.path), self.path)


class _SourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, modules):
        self.modules = modules

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.modules:
            expected=self.modules[fullname]
            spec=importlib.machinery.PathFinder.find_spec(fullname,path)
            _require(spec is not None and Path(spec.origin).resolve()==expected,'mismatch')
            spec.loader=_SourceLoader(fullname,str(expected))
            return spec
        _require(fullname.split('.')[0] in sys.stdlib_module_names,'unsupported')
        return None


def _child(request_path):
    """Fixed source-only protocol. GO attaches; a stop file ends ownership."""
    _require(sys.stdin.readline().strip() == 'GO', 'protocol')
    folder = request_path.parent
    request = json.loads(request_path.read_bytes())
    _require(set(request) == {'version', 'capture_id', 'financial_generation', 'source', 'sources', 'tools'})
    _require(request['version'] == 1, 'unsupported')
    for name, sha in request['tools'].items():
        _require(name in _SUPPORT and _hash(folder / 'tools' / name) == sha, 'mismatch')
    _require(set(request['tools']) == set(_SUPPORT), 'incomplete')
    root = Path(request['source']).resolve()
    modules = _verify_sources(root, request['sources'])
    _require(not (modules.keys() & sys.modules.keys()), 'unsupported')
    _require(not any(name in sys.modules for name in ('numpy', 'bench_candidates', 'bench_baseline')), 'unsupported')
    sys.path[:0] = [str(root),str(root / 'scripts'), str(root / 'website')]
    support_modules = {Path(name).stem: folder / 'tools' / name for name in _SUPPORT}
    _require(not (modules.keys() & support_modules.keys()), 'unsupported')
    finder = _SourceFinder(dict(modules, **support_modules))
    sys.meta_path.insert(0, finder)
    allowed_files = set(modules.values()) | {folder / 'tools' / name for name in _SUPPORT}
    stdlib = Path(sys.base_prefix).resolve()
    memory_path = Path('/proc/self/statm').resolve()
    def audit(event, args):
        if event in ('sqlite3.connect', 'socket.__new__', 'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system',
                     'os.posix_spawn', 'os.exec', 'os.fork'):
            raise ExecutionPolicyError('unsupported')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            _require(path in allowed_files or path == memory_path or
                     path.is_relative_to(stdlib) and not path.is_relative_to(root), 'unsupported')
    sys.addaudithook(audit)
    import schedules
    from bench_policy_program import PolicyProgram
    program = PolicyProgram(schedules)
    policy_sources = {}
    for path in program.source_paths:
        relative = path.relative_to(root).as_posix()
        _require(program.source_hashes[relative] == request['sources'].get(relative) == _hash(path), 'mismatch')
        policy_sources[relative] = program.source_hashes[relative]
    loaded = {}
    for name, path in modules.items():
        module = sys.modules.get(name)
        if module is not None:
            _require(Path(module.__file__).resolve() == path, 'mismatch')
            relative = path.relative_to(root).as_posix()
            _require(_hash(path) == request['sources'][relative], 'mismatch')
            loaded[relative] = _hash(path)
    _verify_sources(root, request['sources'])
    _require(not any(name in sys.modules for name in ('numpy', 'bench_candidates', 'bench_baseline')), 'unsupported')
    binding = dict(version=1, capture_id=request['capture_id'], financial_generation=request['financial_generation'],
                   policy_signature=program.signature, policy_sources=policy_sources)
    binding['identity'] = artifacts.digest(binding)
    _validate_binding(binding, request)
    memory = _memory_bytes()
    _require(memory <= MAX_CHILD_MEMORY, 'limit')
    evidence = dict(signature=program.signature, expressions=artifacts.digest(program.expressions),
        python=artifacts.digest(program.python_source()), decisions=artifacts.digest(program.decisions.source),
        statuses=program.decisions.statuses, sources=program.source_hashes,
        constants=[schedules.r.run.MIN_MARKET_CAP, schedules.r.run.MIN_EV, schedules.r.run.BUFFER,
                   schedules.r.run.MAX_AGE.days], bankruptcy=sorted(schedules.r.revalue.BANKRUPT))
    print(json.dumps(dict(event='attached', binding=binding, modules=loaded, memory_bytes=memory,
                         program_evidence=evidence)), flush=True)
    while not (folder / 'stop').exists():
        _require(_memory_bytes() <= MAX_CHILD_MEMORY, 'limit')
        time.sleep(.02)
    _verify_sources(root, request['sources'])


def _main():
    try:
        _child(Path(sys.argv[2]))
    except BaseException as error:
        print(json.dumps(dict(event='failed', reason=error.reason if isinstance(error, ExecutionPolicyError)
                             else 'child_failed', error_type=type(error).__name__)), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    _main()

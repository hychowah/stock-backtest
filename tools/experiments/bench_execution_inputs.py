"""Benchmark-only ownership of captured artifacts. No financial execution API.

Own a captured financial generation and its verified source snapshot. All
writable databases belong to this workspace. Captured inventories describe
capture-time evidence. This context does not establish current raw freshness,
attach financial engines, admit a benchmark, or qualify resource isolation.

The small cooperative limits below qualify disposable fixtures only. Checkpoints
cannot preempt caller Python or measure transient memory peaks. No workers or
compiler resources are created. Completed and failed workspace evidence remains.
"""
import ast
from contextlib import contextmanager, ExitStack
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys
from threading import Lock
import time
import uuid

import tools.experiments.bench_input_artifacts as artifacts
from tools.experiments.bench_input_store import _memory_bytes, InputStoreError

MAX_DATABASE_BYTES = 32 * 1024 ** 2
MAX_OUTPUT_BYTES = 64 * 1024 ** 2
MAX_MEMORY_BYTES = 128 * 1024 ** 2
MAX_SECONDS = 10.
_FILES = ('research.sqlite', 'schedules.sqlite', 'report.txt')
_SHA = re.compile(r'[0-9a-f]{64}')
_ID = re.compile(r'[0-9a-f]{32}')
_REVISION = re.compile(r'[0-9a-f]{40}')
# PolicyProgram.source_paths: books, metrics, schedules, run, research, revalue.
# Trace their local imports below, without importing or attaching these modules.
_POLICY_ROOTS = frozenset(('backtest/engines/original/schedules.py','backtest/inputs/research.py','backtest/financial/books.py','backtest/financial/metrics.py','backtest/financial/rules.py','backtest/screening.py','backtest/engines/reference/legacy.py','backtest/engines/reference/revalue.py','backtest/engines/original/book_batch.py'))
_locks_guard = Lock()
_locks = {}
# Retain ownership until a failed attachment close is explicitly retried.
_pending_closures = {}


class ExecutionInputError(ValueError):
    """Expected artifact failure with a stable, sanitized reason."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Execution inputs: ' + reason)


def _require(condition, reason='incomplete'):
    if not condition:
        raise ExecutionInputError(reason)


def _sha(value):
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _relative(value):
    _require(isinstance(value, str) and value and '\\' not in value and ':' not in value, 'unsupported')
    path = PurePosixPath(value)
    _require(not path.is_absolute() and path.as_posix() == value and
             all(part not in ('', '.', '..') for part in value.split('/')), 'unsupported')
    return path


def _path(value):
    try:
        path = Path(value).absolute()
    except (TypeError, ValueError) as error:
        raise ExecutionInputError('unsupported') from error
    # Reject symlinks and Windows junctions before resolve can hide an escape.
    for part in (path, *path.parents):
        _require(not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'unsupported')
    try:
        return path.resolve()
    except ValueError as error:
        raise ExecutionInputError('unsupported') from error


def _inside(root, relative):
    _relative(relative)
    path = _path(root / relative)
    _require(path.is_relative_to(root) and path != root, 'unsupported')
    return path


class _Budget:
    def __init__(self, cancel):
        self.cancel = cancel or (lambda: False)
        self.started = time.monotonic()
        self.failure = None

    def check(self, folder=None):
        if self.cancel():
            raise ExecutionInputError('cancelled')
        try:
            memory = _memory_bytes()
        except InputStoreError as error:
            raise ExecutionInputError('limit') from error
        if time.monotonic() - self.started > MAX_SECONDS or memory > MAX_MEMORY_BYTES:
            raise ExecutionInputError('limit')
        if folder is not None:
            total = 0
            for path in folder.rglob('*'):
                _require(not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'unsupported')
                if path.is_file():
                    total += path.stat().st_size
            _require(total <= MAX_OUTPUT_BYTES, 'limit')

    def progress(self):
        try:
            self.check()
            return 0
        except ExecutionInputError as error:
            self.failure = error
            return 1

    def backup_progress(self, status, remaining, total):
        self.check()
        _require(status in (sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE), 'busy')


@contextmanager
def _artifact_failures(budget):
    """Use only around owner operations. Caller exceptions bypass this boundary."""
    try:
        yield
    except sqlite3.ProgrammingError:
        raise
    except sqlite3.DatabaseError as error:
        code = getattr(error, 'sqlite_errorcode', 0) & 255
        reason = ('busy' if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) else
                  'limit' if code == sqlite3.SQLITE_FULL else 'corrupt')
        raise (budget.failure or ExecutionInputError(reason)) from error
    except (FileNotFoundError, NotADirectoryError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExecutionInputError('incomplete') from error
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or getattr(error, 'winerror', None) in (32, 33):
            raise ExecutionInputError('busy') from error
        raise


def _file_hash(path, budget):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(65536):
            budget.check()
            result.update(chunk)
    return result.hexdigest()


def _receipt(value):
    _require(isinstance(value, dict) and set(value) == {'bytes', 'mtime_ns', 'sha256'})
    _require(type(value['bytes']) is int and value['bytes'] >= 0 and
             type(value['mtime_ns']) is int and value['mtime_ns'] >= 0 and _sha(value['sha256']))


def _inventory(value, *, inputs=False):
    _require(isinstance(value, dict) and bool(value))
    for name, entry in value.items():
        if inputs and name == 'historical_through':
            from datetime import date
            try:
                _require(isinstance(entry, str) and date.fromisoformat(entry).isoformat() == entry)
            except ValueError as error:
                raise ExecutionInputError('incomplete') from error
            continue
        _relative(name)
        _require(isinstance(entry, list) and len(entry) == 2)
        _require((type(entry[0]) is int and entry[0] >= 0 or entry[0] == 'directory') and
                 type(entry[1]) is int and entry[1] >= 0)


def _manifest(folder):
    raw = (folder / 'capture.json').read_bytes()
    try:
        value = json.loads(raw)
        artifacts.encoded(value)  # Reject NaN/Infinity at any nested depth.
    except (ValueError, TypeError) as error:
        raise ExecutionInputError('incomplete') from error
    keys = {'version', 'capture_id', 'financial_generation', 'installed_revision',
            'originals', 'metadata', 'artifacts', 'limits', 'benchmark_admitted', 'originals_unchanged'}
    _require(isinstance(value, dict) and set(value) == keys)
    _require(type(value['version']) is int and value['version'] == 1, 'unsupported')
    _require(isinstance(value['capture_id'], str) and _ID.fullmatch(value['capture_id']))
    _require(_sha(value['financial_generation']))
    _require(value['benchmark_admitted'] is False and value['originals_unchanged'] is True, 'unsupported')
    revision = value['installed_revision']
    _require(revision is None or isinstance(revision, str) and _REVISION.fullmatch(revision))
    receipts = value['artifacts']
    _require(isinstance(receipts, dict) and set(receipts) == set(_FILES))
    for receipt in receipts.values():
        _receipt(receipt)
    _require(isinstance(value['metadata'], dict) and set(value['metadata']) == {'research', 'daily'} and
             all(isinstance(v, dict) for v in value['metadata'].values()))
    limits = value['limits']
    _require(isinstance(limits, dict) and set(limits) ==
             {'database_bytes', 'output_bytes', 'sampled_current_memory_bytes', 'wall_seconds'})
    _require(all(type(v) in (int, float) and v > 0 for v in limits.values()))
    before = value['originals']
    _require(isinstance(before, dict) and set(before) ==
             {'assets', 'sources', 'raw_inventory', 'freshness', 'installed_revision', 'deployment'})
    _require(before['installed_revision'] == revision, 'mismatch')
    _require(isinstance(before['assets'], dict) and set(before['assets']) ==
             {'data/research.sqlite', 'data/schedules.sqlite', 'results/summary-exits.txt'})
    for receipt in before['assets'].values():
        _receipt(receipt)
    original_report = before['assets']['results/summary-exits.txt']
    _require(all(original_report[key] == receipts['report.txt'][key] for key in ('bytes', 'sha256')), 'mismatch')
    if before['deployment'] is not None:
        _receipt(before['deployment'])
    sources = before['sources']
    _require(isinstance(sources, dict) and bool(sources))
    for name, sha in sources.items():
        path = _relative(name)
        _require((((len(path.parts)==2 and path.parts[0]=='scripts') or (len(path.parts)>=2 and path.parts[0]=='backtest') or (len(path.parts)==2 and path.parts[0]=='website') or (len(path.parts)>=3 and path.parts[:2] in (('website','rendering'),('website','server')))) and path.suffix == '.py') or name in artifacts.SOURCE_ASSETS, 'unsupported')
        _require(_sha(sha))
    _require(_POLICY_ROOTS <= sources.keys())
    if 'backtest/engines/numerical/random.py' in sources:
        _require(artifacts.SOURCE_ASSETS <= sources.keys(), 'incomplete')
    _inventory(before['raw_inventory'])
    freshness = before['freshness']
    _require(isinstance(freshness, dict) and set(freshness) == {'inputs', 'prices', 'daily_inputs'})
    _inventory(freshness['inputs'], inputs=True)
    _inventory(freshness['prices'])
    daily = freshness['daily_inputs']
    _require(isinstance(daily, dict) and set(daily) == {'version', 'inputs', 'engine'})
    _require(type(daily['version']) is int and daily['version'] == artifacts.DAILY_VERSION, 'unsupported')
    _require(daily['inputs'] == freshness['inputs'], 'mismatch')
    _inventory(daily['engine'])
    _require(set(daily['engine']) == {'backtest/inputs/daily.py', 'backtest/engines/original/schedules.py', 'backtest/engines/original/book_batch.py', 'backtest/calendar.py', 'backtest/portfolio_results.py'})
    return value, raw


def _connect(path, budget, *, readonly):
    uri = path.as_uri() + ('?mode=ro&immutable=1' if readonly else '?mode=rw')
    db = sqlite3.connect(uri, uri=True, timeout=0)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=0')
        db.execute('PRAGMA cache_size=-1024')
        if readonly:
            db.execute('PRAGMA query_only=ON')
        else:
            page_size = db.execute('PRAGMA page_size').fetchone()[0]
            db.execute(f'PRAGMA max_page_count={getattr(budget, "database_bytes", MAX_DATABASE_BYTES) // page_size}')
        db.set_progress_handler(budget.progress, 1000)
        return db
    except BaseException:
        db.close()
        raise


def _generation(research, daily, manifest, budget):
    for db, schema in ((research, artifacts.RESEARCH_TABLES), (daily, artifacts.DAILY_TABLES)):
        artifacts.schema(db, schema, budget, ExecutionInputError, reason='unsupported', integrity_reason='corrupt')
    r, d = (artifacts.metadata(db, ExecutionInputError, reason='incomplete') for db in (research, daily))
    _require(dict(research=r, daily=d) == manifest['metadata'], 'mismatch')
    _require(type(r.get('version')) is int and r['version'] == artifacts.RESEARCH_VERSION, 'unsupported')
    _require(isinstance(d.get('daily_inputs'), dict) and type(d['daily_inputs'].get('version')) is int and
             d['daily_inputs']['version'] == artifacts.DAILY_VERSION, 'unsupported')
    historical = manifest['originals']['freshness']
    _require(r.get('inputs') == historical['inputs'] and r.get('prices') == historical['prices'] and
             d['daily_inputs'] == historical['daily_inputs'], 'mismatch')
    _require(isinstance(d.get('cached_symbols'), list) and all(isinstance(v, str) for v in d['cached_symbols']))
    report_sha = manifest['artifacts']['report.txt']['sha256']
    _require(r.get('baseline_report_sha') == report_sha, 'mismatch')
    row_hash = lambda db, table: artifacts.table_hash(db, table, budget, ExecutionInputError,
                                                    reason='corrupt', every=1024, pool_order=False)
    artifacts.shared_rows(research, daily, row_hash, ExecutionInputError)
    identity = artifacts.digest(dict(
        research={table: row_hash(research, table) for table in artifacts.RESEARCH_TABLES if table != 'metadata'},
        daily_base={table: row_hash(daily, table) for table in artifacts.DAILY_BASE},
        metadata=(r, d), report=report_sha, sources=manifest['originals']['sources']))
    _require(identity == manifest['financial_generation'], 'mismatch')
    return identity


def _source_snapshot(root, target, sources, budget):
    target.mkdir()
    for name, expected in sources.items():
        path = _inside(root, name)
        _require(path.is_file())
        _require(_file_hash(path, budget) == expected, 'mismatch')
        destination = _inside(target, name)
        destination.parent.mkdir(parents=True,exist_ok=True)
        # Bounded copies also check cancellation; verify both ends after copying.
        with path.open('rb') as source, destination.open('xb') as output:
            while chunk := source.read(65536):
                budget.check(target.parent)
                output.write(chunk)
        _require(_file_hash(destination, budget) == expected and _file_hash(path, budget) == expected, 'mismatch')
    pending, visited = list(_POLICY_ROOTS), set()
    by_module = {}
    for name in sources:
        if name in artifacts.SOURCE_ASSETS:continue
        parts=list(PurePosixPath(name).parts)
        if parts[0] in ('backtest','website','tools'):
            module='.'.join(parts[:-1] if parts[-1]=='__init__.py' else [*parts[:-1],PurePosixPath(name).stem])
        else:module=PurePosixPath(name).stem
        _require(module not in by_module,'unsupported')
        by_module[module]=name

    def dependency(parts):
        module='.'.join(parts)
        if module in by_module:
            pending.append(by_module[module])
            for length in range(1,len(parts)):
                parent='.'.join(parts[:length])
                if parent in by_module:pending.append(by_module[parent])
            return True
        return False

    while pending:
        name=pending.pop()
        if name in visited:continue
        visited.add(name)
        try:tree=ast.parse((target/name).read_text(encoding='utf-8'))
        except (SyntaxError,ValueError) as error:raise ExecutionInputError('unsupported') from error
        package=list(PurePosixPath(name).parts[:-1])
        for number,node in enumerate(ast.walk(tree)):
            if number%1024==0:budget.check()
            if isinstance(node,ast.Call):
                dynamic=isinstance(node.func,ast.Name) and node.func.id in ('__import__','exec','eval')
                dynamic|=isinstance(node.func,ast.Attribute) and node.func.attr=='import_module'
                _require(not dynamic,'unsupported')
            imports=[]
            if isinstance(node,ast.Import):imports=[alias.name.split('.') for alias in node.names]
            elif isinstance(node,ast.ImportFrom):
                base=(package[:len(package)-node.level+1] if node.level else [])
                if node.module:base+=node.module.split('.')
                imports=[base]
                for alias in node.names:
                    if alias.name!='*':
                        alias_parts=[*base,alias.name]
                        candidate=root.joinpath(*alias_parts)
                        exists=candidate.with_suffix('.py').exists() or (candidate/'__init__.py').exists()
                        base_name='.'.join(base)
                        is_package=base_name in by_module and PurePosixPath(by_module[base_name]).name=='__init__.py'
                        if exists or is_package:_require(dependency(alias_parts),'incomplete')
                        else:dependency(alias_parts)
            for parts in imports:
                module='.'.join(parts)
                # Reject an unrecorded local module even if its name is stdlib.
                for directory in ('scripts','website'):
                    candidate=root/directory/(parts[0]+'.py')
                    if candidate.exists() or candidate.is_symlink():_require(directory+'/'+parts[0]+'.py' in sources)
                candidate=root.joinpath(*parts)
                if candidate.with_suffix('.py').exists() or (candidate/'__init__.py').exists():
                    _require(module in by_module,'incomplete')
                if not dependency(parts):_require(parts[0] in sys.stdlib_module_names,'incomplete')
    return target


class CapturedWorkspace:
    """Own captured inputs, source bytes and all private derivatives until close.

    Own a captured financial generation and its verified source snapshot. All
    writable databases belong to this workspace. Captured inventories describe
    capture-time evidence. This context does not establish current raw freshness,
    attach financial engines, admit a benchmark, or qualify resource isolation.

    No runtime discovery, financial imports, stable coordinator, workers or
    compiler resources. One context per instance. Output remains as evidence.
    """
    def __init__(self, capture_directory, policy_source, experiment_directory, *, cancel=None):
        self.capture = _path(capture_directory)
        self.policy_source = _path(policy_source)
        self.root = _path(experiment_directory)
        for original in (self.capture, self.policy_source):
            _require(not self.root.is_relative_to(original) and not original.is_relative_to(self.root), 'unsupported')
        self.cancel = cancel
        self._used = self._active = False
        self._resources = None
        self._attachments = {}
        with _locks_guard:
            self._thread_lock = _locks.setdefault(str(self.root), Lock())

    @contextmanager
    def _ownership(self):
        _require(self._thread_lock.acquire(blocking=False), 'busy')
        handle = None
        locked = False
        try:
            marker = self.root / 'workspace-owner.json'
            declaration = dict(version=1, kind='captured-input-workspaces')
            try:
                self.root.mkdir(parents=True)
            except FileExistsError:
                _require(self.root.is_dir(), 'unsupported')
                marker = _inside(self.root, marker.name)
                _require(marker.is_file() and marker.stat().st_size <= 1024, 'unsupported')
                _require(json.loads(marker.read_bytes()) == declaration, 'unsupported')
                for path in self.root.iterdir():
                    _inside(self.root, path.name)
                    if path.name in ('workspace-owner.json', 'owner.lock'):
                        _require(path.is_file(), 'unsupported')
                    else:
                        _require(path.name.startswith('workspace-') and
                                 _ID.fullmatch(path.name[len('workspace-'):]) and path.is_dir(), 'unsupported')
            else:
                with marker.open('xb') as stream:
                    stream.write(artifacts.encoded(declaration))
            lock_path = _inside(self.root, 'owner.lock')
            handle = lock_path.open('a+b')
            if not handle.seek(0, os.SEEK_END):
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise ExecutionInputError('busy') from None
                raise
            yield
        finally:
            if locked:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            if handle is not None:
                handle.close()
            self._thread_lock.release()

    def _record(self, status, error=None):
        value = dict(status=status, current_raw_freshness='unavailable', execution_admission='unavailable')
        if error is not None:
            value.update(reason=error.reason if isinstance(error, ExecutionInputError) else 'unexpected',
                         error_type=type(error).__name__)
        else:
            value.update(artifact_integrity='verified', captured_coherence='verified',
                         source_content='verified', financial_generation=self.identity)
        try:
            (self._folder / 'workspace.json').write_bytes(artifacts.encoded(value))
        except OSError:
            # A recording failure must not replace a caller's original exception.
            if error is None:
                raise

    def _budget(self):
        """The public captured-input fixture retains its original envelope.

        A measurement owner can reuse artifact operations with a separately
        declared envelope. That owner must obtain execution admission first.
        Changing that owner does not enlarge this fixture's qualified scope.
        """
        return _Budget(self.cancel)

    @contextmanager
    def _open_owned(self):
        budget = self._budget()
        with ExitStack() as lifetime:
            with _artifact_failures(budget):
                lifetime.enter_context(self._ownership())
                self._folder = _inside(self.root, 'workspace-' + uuid.uuid4().hex)
                self._folder.mkdir()
            try:
                with _artifact_failures(budget):
                    budget.check()
                    _require(self.capture.is_dir() and self.policy_source.is_dir())
                    _require({p.name for p in self.capture.iterdir()} == set(_FILES) | {'capture.json'})
                    for path in self.capture.iterdir():
                        _require(_inside(self.capture, path.name).is_file())
                    _require(sum((self.capture / name).stat().st_size for name in _FILES[:2]) <= getattr(budget, 'database_bytes', MAX_DATABASE_BYTES), 'limit')
                    _require(sum(p.stat().st_size for p in self.capture.iterdir()) <= getattr(budget, 'output_bytes', MAX_OUTPUT_BYTES), 'limit')
                    manifest, raw = _manifest(self.capture)
                    for name in _FILES:
                        path = self.capture / name
                        expected = manifest['artifacts'][name]
                        _require(path.stat().st_size == expected['bytes'] and _file_hash(path, budget) == expected['sha256'], 'corrupt')
                    self.source_snapshot = _source_snapshot(self.policy_source, self._folder / 'source',
                                                            manifest['originals']['sources'], budget)
                    resources = lifetime.enter_context(ExitStack())
                    self._resources = resources
                    self.research = _connect(self.capture / 'research.sqlite', budget, readonly=True)
                    resources.callback(self.research.close)
                    self.daily = _connect(self.capture / 'schedules.sqlite', budget, readonly=True)
                    resources.callback(self.daily.close)
                    self.identity = _generation(self.research, self.daily, manifest, budget)
                    self.capture_id = manifest['capture_id']
                    self.report = (self.capture / 'report.txt').read_bytes()
                    _require(hashlib.sha256(self.report).hexdigest() == manifest['artifacts']['report.txt']['sha256'], 'corrupt')
                    self.manifest_bytes = raw
                    self.captured_metadata = json.loads(artifacts.encoded(manifest['metadata']))
                    self.captured_freshness = json.loads(artifacts.encoded(manifest['originals']['freshness']))
                    (self._folder / 'capture.json').write_bytes(raw)
                    budget.check(self._folder)
                    self._record('attached')
                    self._active = True
                # Caller code is deliberately outside artifact-error translation.
                yield self
                with _artifact_failures(budget):
                    budget.check(self._folder)
                    self._record('complete')
            except BaseException as error:
                self._record('failed', error)
                raise
            finally:
                self._active = False
                # ExitStack closes derivatives and read-only handles before lock.

    def __enter__(self):
        _require(not self._used)
        self._used = True
        self._session = self._open_owned()
        return self._session.__enter__()

    def __exit__(self, *args):
        # Close attached processes before unwinding the source/database stack.
        # Keep the suspended owner alive if cleanup needs an explicit retry.
        self._active = False
        with _locks_guard:
            _pending_closures[id(self)] = self
        failure = None
        for close in tuple(self._attachments.values()):
            try:
                close()
            except BaseException as error:
                failure = failure or error
        if self._attachments:
            if args[1] is not None:
                # Preserve the caller's exception and retain ownership for retry.
                return False
            raise failure or ExecutionInputError('busy')
        try:
            if failure is not None and args[1] is None:
                self._session.__exit__(type(failure), failure, failure.__traceback__)
                raise failure
            return self._session.__exit__(*args)
        finally:
            with _locks_guard:
                _pending_closures.pop(id(self), None)

    def _register_resource(self, name, close):
        """Own at most one attachment of each kind through final closure.

        Return an idempotent release callback for an attachment closed early.
        The registered callback still runs before workspace ownership ends.
        """
        _require(self._active)
        with _locks_guard:
            _require(name not in self._attachments, 'busy')
        released = False
        def release():
            nonlocal released
            with _locks_guard:
                if not released:
                    self._attachments.pop(name, None)
                    released = True
        def finish():
            close()
            release()
        with _locks_guard:
            # Keep check and registration atomic for same-workspace callers.
            _require(name not in self._attachments, 'busy')
            self._attachments[name] = finish
        self._resources.callback(finish)
        return release

    @contextmanager
    def writable_daily(self):
        """Borrow a fresh private derivative; outer exit also closes escapes."""
        _require(self._active)
        budget = self._budget()
        target = folder = None
        try:
            with _artifact_failures(budget):
                budget.check(self._folder)
                folder = _inside(self._folder, 'daily-' + uuid.uuid4().hex)
                folder.mkdir()
                path = folder / 'schedules.sqlite'
                path.touch(exist_ok=False)
                target = _connect(path, budget, readonly=False)
                self._resources.callback(target.close)
                self.daily.backup(target, pages=16, progress=budget.backup_progress, sleep=0)
                # Backup copies page settings; enforce the target cap afterwards.
                page_size = target.execute('PRAGMA page_size').fetchone()[0]
                target.execute(f'PRAGMA max_page_count={getattr(budget, "database_bytes", MAX_DATABASE_BYTES) // page_size}')
                budget.check(self._folder)
                (folder / 'attempt.json').write_bytes(artifacts.encoded(dict(status='attached')))
            yield target
            with _artifact_failures(budget):
                if self._active:
                    budget.check(self._folder)
                    (folder / 'attempt.json').write_bytes(artifacts.encoded(dict(status='complete')))
        except BaseException as error:
            if folder is not None and self._active:
                try:
                    (folder / 'attempt.json').write_bytes(artifacts.encoded(dict(status='failed',
                        reason=error.reason if isinstance(error, ExecutionInputError) else 'unexpected',
                        error_type=type(error).__name__)))
                except OSError:
                    pass
            raise
        finally:
            if target is not None:
                target.close()

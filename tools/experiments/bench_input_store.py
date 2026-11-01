"""Own small synthetic prepared-input handoffs; no live capture or execution.

A producer builds research/daily/report inputs in fresh private storage. The
store closes its connections, checks coherence and publishes one immutable
folder. Readers borrow read-only handles; writable daily clones live elsewhere.
All handles close before store ownership ends. No caller supplies source DB paths.

Receipts bind artifacts and declared source/policy evidence. They do not prove
raw freshness, live capture, resource admission or readiness of either engine.
Limits are cooperative checkpoints, including SQLite progress callbacks. They
cannot preempt arbitrary producer Python or measure transient resource peaks.
There is no production adapter, subprocess execution, or admission override.
"""
from contextlib import contextmanager, ExitStack
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import Lock
import time
import uuid


from tools.experiments.bench_input_artifacts import (RESEARCH_VERSION, DAILY_VERSION, BASE_TABLES,
    RESEARCH_TABLES, DAILY_BASE, DAILY_TABLES, DERIVED)
import tools.experiments.bench_input_artifacts as artifacts
ARTIFACTS = ('research.sqlite', 'daily.sqlite', 'report.txt')
_MAX_DATABASE_BYTES = 32 * 1024 * 1024
_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
_MAX_MEMORY_BYTES = 128 * 1024 * 1024
_MAX_SECONDS = 10.
_ID = re.compile(r'[0-9a-f]{32}')
_SHA = re.compile(r'[0-9a-f]{64}')
_locks_guard = Lock()
_locks = {}


class InputStoreError(ValueError):
    """Expected failure with a stable, sanitized reason code."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Input store: ' + reason)


_json = artifacts.encoded
_digest = artifacts.digest


def _memory_bytes():
    """Sample current Linux RSS or current Windows process working set."""
    if os.name != 'nt':
        try:
            return int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
        except (OSError, ValueError, IndexError):
            raise InputStoreError('limit') from None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak', 'working', 'pool_peak',
            'pool', 'nonpaged_peak', 'nonpaged', 'pagefile', 'pagefile_peak')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
    value = Counters(); value.cb = ctypes.sizeof(value)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
        raise InputStoreError('limit')
    return value.working


class _Budget:
    def __init__(self, cancel):
        self.cancel = cancel or (lambda: False)
        self.started = time.monotonic()
        self.failure = None

    def check(self, folder=None):
        if self.cancel():
            raise InputStoreError('cancelled')
        if time.monotonic() - self.started > _MAX_SECONDS or _memory_bytes() > _MAX_MEMORY_BYTES:
            raise InputStoreError('limit')
        if folder is not None:
            paths = list(folder.iterdir())
            if any(p.is_symlink() or not p.is_file() for p in paths):
                raise InputStoreError('incomplete')
            if sum(p.stat().st_size for p in paths) > _MAX_OUTPUT_BYTES:
                raise InputStoreError('limit')
            if sum(p.stat().st_size for p in paths if p.name.endswith('.sqlite')) > _MAX_DATABASE_BYTES:
                raise InputStoreError('limit')

    def progress(self):
        try:
            self.check()
            return 0
        except InputStoreError as error:
            self.failure = error
            return 1

    def backup_progress(self, status, remaining, total):
        self.check()
        if status not in (sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE):
            raise InputStoreError('busy')


def _connect(path, budget, *, readonly=False):
    db = sqlite3.connect(path.resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw'),
                         uri=True, timeout=0)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=0')
        db.execute('PRAGMA cache_size=-1024')
        db.set_progress_handler(budget.progress, 1000)
        if readonly:
            db.execute('PRAGMA query_only=ON')
        return db
    except BaseException:
        db.close()
        raise


def _hash_file(path, budget):
    result = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(65536):
            budget.check()
            result.update(chunk)
    return result.hexdigest()


def _table_hash(db, table, budget):
    return artifacts.table_hash(db, table, budget, InputStoreError, reason='corrupt')


def _metadata(db):
    return artifacts.metadata(db, InputStoreError, reason='incomplete')


def _schema(db, expected, budget):
    artifacts.schema(db, expected, budget, InputStoreError,
                     reason='incomplete', integrity_reason='corrupt')


def _evidence(value):
    if not isinstance(value, dict) or set(value) != {'sources', 'policy_sha256', 'catalog_sha256'}:
        raise InputStoreError('incomplete')
    sources = value['sources']
    if not isinstance(sources, dict) or not sources:
        raise InputStoreError('incomplete')
    for name, sha in sources.items():
        if not isinstance(name, str) or name.startswith('/') or '\\' in name or '..' in name.split('/'):
            raise InputStoreError('incomplete')
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise InputStoreError('incomplete')
    if any(not isinstance(value[name], str) or not _SHA.fullmatch(value[name])
           for name in ('policy_sha256', 'catalog_sha256')):
        raise InputStoreError('incomplete')
    return json.loads(_json(value))


@contextmanager
def _database_failures(budget):
    """Translate failures only while the store owns the database operation."""
    try:
        yield
    except sqlite3.DatabaseError as error:
        reason = 'limit' if getattr(error, 'sqlite_errorcode', None) == sqlite3.SQLITE_FULL else 'corrupt'
        raise (budget.failure or InputStoreError(reason)) from error


def _manifest(folder, generation_id):
    """Contain malformed receipts before callers can access nested fields."""
    try:
        value = json.loads((folder / 'manifest.json').read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InputStoreError('incomplete') from error
    if not isinstance(value, dict):
        raise InputStoreError('incomplete')
    if type(value.get('version')) is not int or value['version'] != 1 or value.get('generation_id') != generation_id:
        raise InputStoreError('mismatch')
    if not isinstance(value.get('identity'), str) or not _SHA.fullmatch(value['identity']):
        raise InputStoreError('incomplete')
    _evidence(value.get('evidence'))
    artifacts = value.get('artifacts')
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACTS):
        raise InputStoreError('incomplete')
    for receipt in artifacts.values():
        if not isinstance(receipt, dict) or set(receipt) != {'bytes', 'sha256'}:
            raise InputStoreError('incomplete')
        if type(receipt['bytes']) is not int or receipt['bytes'] < 0:
            raise InputStoreError('incomplete')
        if not isinstance(receipt['sha256'], str) or not _SHA.fullmatch(receipt['sha256']):
            raise InputStoreError('incomplete')
    return value


def _coherence(research, daily, report_sha, evidence, budget, *, fresh):
    _schema(research, RESEARCH_TABLES, budget)
    _schema(daily, DAILY_TABLES, budget)
    r, d = _metadata(research), _metadata(daily)
    if not isinstance(d.get('daily_inputs'), dict):
        raise InputStoreError('incomplete')
    if r.get('version') != RESEARCH_VERSION or d['daily_inputs'].get('version') != DAILY_VERSION:
        raise InputStoreError('mismatch')
    inventory = r.get('inputs')
    if not isinstance(inventory, dict) or not inventory or d['daily_inputs'].get('inputs') != inventory:
        raise InputStoreError('mismatch')
    if not isinstance(d['daily_inputs'].get('engine'), dict) or not d['daily_inputs']['engine']:
        raise InputStoreError('incomplete')
    if r.get('baseline_report_sha') != report_sha:
        raise InputStoreError('mismatch')
    if not isinstance(r.get('prices'), dict) or not isinstance(d.get('cached_symbols'), list):
        raise InputStoreError('incomplete')
    artifacts.shared_rows(research, daily, lambda db, table: _table_hash(db, table, budget), InputStoreError)
    if fresh and any(daily.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone() for table in DERIVED):
        raise InputStoreError('incomplete')
    base = {table: _table_hash(daily, table, budget) for table in DAILY_BASE}
    # Research contains immutable January/latest evidence. Daily book tables are
    # excluded. Full file hashes still bind every byte of published artifacts.
    research_rows = {table: _table_hash(research, table, budget) for table in RESEARCH_TABLES if table != 'metadata'}
    return _digest(dict(research=research_rows, research_metadata=r,
                        daily=base, daily_metadata=d, report=report_sha, evidence=evidence))


@dataclass
class BoundInputs:
    """Borrowed handles valid only inside InputStore.open(). No execution grant."""
    research: sqlite3.Connection
    daily: sqlite3.Connection
    report: bytes
    identity: str
    generation_id: str
    _store: object
    _budget: object
    _folder: Path
    _resources: object
    _active: bool = True

    @contextmanager
    def writable_daily(self):
        """Own a fresh clone through final close; preserve it as attempt evidence."""
        if not self._active:
            raise InputStoreError('incomplete')
        budget = _Budget(self._budget.cancel)
        run = self._store.root / 'runs' / uuid.uuid4().hex
        run.mkdir()
        path = run / 'daily.sqlite'
        target = None
        try:
            budget.check()
            target = sqlite3.connect(path, timeout=0)
            self._resources.callback(target.close)
            self.daily.backup(target, pages=16, progress=budget.backup_progress, sleep=0)
            target.row_factory = sqlite3.Row
            target.set_progress_handler(budget.progress, 1000)
            budget.check(run)
            yield target
            budget.check(run)
        except BaseException as error:
            self._store._failure(run.name, error)
            raise
        finally:
            if target is not None:
                target.close()


class _Producer:
    def __init__(self, folder, budget):
        self.folder, self.budget = folder, budget
        self.research = self.daily = None
        self.generation_id = None
        try:
            for name in ('research', 'daily'):
                path = folder / (name + '.sqlite')
                path.touch(exist_ok=False)
                db = _connect(path, budget)
                setattr(self, name, db)
                db.execute(f'PRAGMA max_page_count={_MAX_DATABASE_BYTES // 2 // 4096}')
        except BaseException:
            self.close()
            raise

    def write_report(self, content):
        self.budget.check(self.folder)
        if not isinstance(content, bytes):
            raise TypeError('Report content must be bytes.')
        if len(content) > _MAX_OUTPUT_BYTES - _MAX_DATABASE_BYTES:
            raise InputStoreError('limit')
        (self.folder / 'report.txt').write_bytes(content)
        self.budget.check(self.folder)

    def seal(self):
        # Only these privately constructed DBs are normalized. SQLite itself
        # checkpoints committed WAL pages and retires its own sidecars. Busy
        # readers defer publication; no sidecar is deleted by the store.
        for db in (self.research, self.daily):
            if db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal':
                if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                    raise InputStoreError('busy')
                if db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
                    raise InputStoreError('busy')
        self.close()

    def close(self):
        for db in (self.research, self.daily):
            if db is not None:
                db.close()


class InputStore:
    """One no-wait owner of synthetic generation construction and attachment.

    Store paths must be separately owned fixture paths. No runtime path is
    accepted as a capture source. Store-local serialization holds through all
    connection closure. Previous generations are never overwritten or retired.
    """
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ('staging', 'generations', 'runs', 'failures'):
            (self.root / name).mkdir(exist_ok=True)
        with _locks_guard:
            self._thread_lock = _locks.setdefault(str(self.root), Lock())

    @contextmanager
    def _ownership(self):
        if not self._thread_lock.acquire(blocking=False):
            raise InputStoreError('busy')
        handle = None
        locked = False
        try:
            handle = (self.root / 'owner.lock').open('a+b')
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
                    raise InputStoreError('busy') from None
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

    def _failure(self, attempt, error):
        reason = error.reason if isinstance(error, InputStoreError) else 'unexpected'
        value = dict(attempt=attempt, reason=reason, error_type=type(error).__name__)
        path = self.root / 'failures' / (attempt + '.json')
        path.write_bytes(_json(value))

    @staticmethod
    def _sealed(folder, budget, *, manifest=False):
        budget.check(folder)
        expected = set(ARTIFACTS) | ({'manifest.json'} if manifest else set())
        if {p.name for p in folder.iterdir()} != expected:
            raise InputStoreError('incomplete')
        # Closed writers normally checkpoint WAL automatically. Remaining
        # journals/sidecars are rejected, never deleted or ignored by capture.

    @contextmanager
    def produce(self, evidence, *, cancel=None):
        """Build only owned inputs, then close, validate and atomically publish."""
        evidence = _evidence(evidence)
        budget = _Budget(cancel)
        attempt = uuid.uuid4().hex
        with self._ownership():
            folder = self.root / 'staging' / attempt
            folder.mkdir()
            producer = None
            try:
                budget.check()
                with _database_failures(budget):
                    producer = _Producer(folder, budget)
                # Caller code is outside artifact-error translation. A builder
                # programming failure keeps its original exception and type.
                yield producer
                with _database_failures(budget):
                    budget.check(folder)
                    if producer.research.in_transaction or producer.daily.in_transaction:
                        raise InputStoreError('incomplete')
                    producer.seal()
                    self._sealed(folder, budget)
                    with ExitStack() as resources:
                        research = _connect(folder / 'research.sqlite', budget, readonly=True)
                        resources.callback(research.close)
                        daily = _connect(folder / 'daily.sqlite', budget, readonly=True)
                        resources.callback(daily.close)
                        identity = _coherence(research, daily, _hash_file(folder / 'report.txt', budget),
                                              evidence, budget, fresh=True)
                    receipts = {name: dict(bytes=(folder / name).stat().st_size,
                                sha256=_hash_file(folder / name, budget)) for name in ARTIFACTS}
                    receipt = dict(version=1, generation_id=attempt, identity=identity,
                                   evidence=evidence, artifacts=receipts)
                    (folder / 'manifest.json').write_bytes(_json(receipt))
                    self._sealed(folder, budget, manifest=True)
                    # Unique destination, all owned connections closed. No pointer
                    # replacement or cleanup can damage an earlier generation.
                    folder.rename(self.root / 'generations' / attempt)
                    producer.generation_id = attempt
            except BaseException as error:
                self._failure(attempt, error)
                raise
            finally:
                if producer is not None:
                    producer.close()

    @contextmanager
    def open(self, generation_id, *, cancel=None):
        """Validate an immutable handoff before exposing read-only handles."""
        if not isinstance(generation_id, str) or not _ID.fullmatch(generation_id):
            raise InputStoreError('incomplete')
        budget = _Budget(cancel)
        with self._ownership(), ExitStack() as resources:
            folder = self.root / 'generations' / generation_id
            try:
                self._sealed(folder, budget, manifest=True)
                manifest = _manifest(folder, generation_id)
                evidence = manifest['evidence']
                for name in ARTIFACTS:
                    actual = dict(bytes=(folder / name).stat().st_size,
                                  sha256=_hash_file(folder / name, budget))
                    if manifest['artifacts'][name] != actual:
                        raise InputStoreError('corrupt')
                research = _connect(folder / 'research.sqlite', budget, readonly=True)
                resources.callback(research.close)
                daily = _connect(folder / 'daily.sqlite', budget, readonly=True)
                resources.callback(daily.close)
                identity = _coherence(research, daily, manifest['artifacts']['report.txt']['sha256'],
                                      evidence, budget, fresh=True)
                if identity != manifest.get('identity'):
                    raise InputStoreError('mismatch')
                bound = BoundInputs(research, daily, (folder / 'report.txt').read_bytes(),
                                    identity, generation_id, self, budget, folder, resources)
            except sqlite3.DatabaseError as error:
                raise (budget.failure or InputStoreError('corrupt')) from error
            except (FileNotFoundError, json.JSONDecodeError) as error:
                raise InputStoreError('incomplete') from error
            try:
                yield bound
            finally:
                bound._active = False

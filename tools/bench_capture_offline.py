"""Capture a stopped runtime without changing its financial inputs or books.

Exclusive source ownership precedes no-wait financial ownership and lasts until
all databases close and verification finishes. A concurrent server start can
wait behind this offline capture. This does not stop/start servers, prepare or
repair caches, attach engines, forge freshness metadata, or admit benchmarks.
Limits are cooperative checkpoints; real use also needs an external watchdog.
"""
import argparse
import ast
from contextlib import ExitStack, contextmanager
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import uuid

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE / 'website'), str(SOURCE / 'scripts')]
import runtime_access
import cache_access
from bench_input_store import _memory_bytes, InputStoreError
from bench_input_artifacts import BASE_TABLES, DAILY_BASE, RESEARCH_TABLES, DAILY_TABLES
import bench_input_artifacts as artifacts

MAX_DATABASE_BYTES = 4 * 1024 ** 3
MAX_OUTPUT_BYTES = 8 * 1024 ** 3
MAX_MEMORY_BYTES = 512 * 1024 ** 2
MAX_SECONDS = 900.
DATABASES = {'research.sqlite': 'data/research.sqlite', 'schedules.sqlite': 'data/schedules.sqlite'}
REPORT = 'results/summary-exits.txt'
SIGNATURE_SOURCES = ('baseline', 'research', 'metrics', 'books', 'cache_assets', 'run', 'revalue', 'financial_inputs')


class OfflineCaptureError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Offline capture: ' + reason)


encoded = artifacts.encoded
digest = artifacts.digest


class Budget:
    def __init__(self, cancel, progress):
        self.cancel = cancel or (lambda: False)
        self.progress = progress or (lambda event: None)
        self.started = time.monotonic()
        self.failure = None
        self.last_event = 0.

    def check(self):
        if self.cancel():
            raise OfflineCaptureError('cancelled')
        try:
            memory = _memory_bytes()
        except InputStoreError as error:
            raise OfflineCaptureError('limit') from error
        if time.monotonic() - self.started > MAX_SECONDS or memory > MAX_MEMORY_BYTES:
            raise OfflineCaptureError('limit')

    def event(self, stage, **values):
        self.check()
        self.progress(dict(event=stage, **values))

    def sqlite_progress(self):
        try:
            self.check()
            return 0
        except OfflineCaptureError as error:
            self.failure = error
            return 1

    def backup_progress(self, status, remaining, total):
        self.check()
        if status not in (sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE):
            raise OfflineCaptureError('busy')
        now = time.monotonic()
        if not remaining or now - self.last_event >= 1:
            self.last_event = now
            self.event('backup_progress', remaining_pages=remaining, total_pages=total)


def file_hash(path, budget):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            budget.check(); result.update(chunk)
    return result.hexdigest()


def receipt(path, budget):
    before = path.stat()
    value = dict(bytes=before.st_size, mtime_ns=before.st_mtime_ns, sha256=file_hash(path, budget))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OfflineCaptureError('changed-original')
    return value


def constant(root, module, name):
    tree = ast.parse((root / 'scripts' / (module + '.py')).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            try:
                if name == 'ASOF' and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'date' and not node.value.keywords:
                    return date(*(ast.literal_eval(value) for value in node.value.args))
                return ast.literal_eval(node.value)
            except (ValueError, TypeError):
                break
    raise OfflineCaptureError('unsupported')


def freshness(root, budget):
    """Explicit-root equivalent of signature(), price_sources(), fingerprint()."""
    raw = root / 'raw'
    paths = [raw / name for name in ('universe.json', 'metrics.jsonl', 'spy-div.json', 'treasury.json')]
    paths += [raw / 'px'] + [root / 'scripts' / (name + '.py') for name in SIGNATURE_SOURCES]
    paths += sorted((raw / 'financial-inputs').glob('*/*.json'))
    inventory = {}
    for number, path in enumerate(paths):
        if number % 1024 == 0: budget.check()
        info = path.stat()
        inventory[path.relative_to(root).as_posix()] = ['directory' if path.is_dir() else info.st_size, info.st_mtime_ns]
    report = (root / REPORT).read_text(encoding='utf-8')
    match = re.search(r'^Through (\d{4}-\d{2}-\d{2})\s*$', report, re.MULTILINE)
    if match is None: raise OfflineCaptureError('unsupported')
    inventory['historical_through'] = str(min(constant(root, 'run', 'ASOF'), date.fromisoformat(match[1])))
    prices = {}
    for number, path in enumerate(sorted((raw / 'px').glob('*.json'))):
        if number % 1024 == 0: budget.check()
        info = path.stat(); prices[path.name] = [info.st_size, info.st_mtime_ns]
    engine = {}
    for name in ('schedules.py', 'book_batch.py', 'schedule_calendar.py'):
        info = (root / 'scripts' / name).stat(); engine[name] = [info.st_size, info.st_mtime_ns]
    return dict(inputs=inventory, prices=prices, daily_inputs=dict(version=3, inputs=inventory, engine=engine))


def preflight(root):
    for name in ('deployment.pending.json', 'research.sqlite.publication.json'):
        if (root / 'data' / name).exists(): raise OfflineCaptureError('pending')
    for relative in DATABASES.values():
        path = root / relative
        if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise OfflineCaptureError('unsupported')
        with path.open('rb') as stream: header = stream.read(100)
        if len(header) != 100 or header[:16] != b'SQLite format 3\x00' or header[18:20] != b'\x01\x01':
            raise OfflineCaptureError('unsupported')
    if constant(root, 'research', 'SCHEMA_VERSION') != 7 or constant(root, 'schedules', 'VERSION') != 3:
        raise OfflineCaptureError('unsupported')


def originals(root, budget):
    preflight(root)
    assets = {relative: receipt(root / relative, budget) for relative in (*DATABASES.values(), REPORT)}
    source = {}
    for directory in ('scripts', 'website'):
        for path in sorted((root / directory).glob('*.py')):
            budget.check(); source[path.relative_to(root).as_posix()] = file_hash(path, budget)
    installed = None
    deployment_path = root / 'data/deployment.json'
    deployment_receipt = None
    if deployment_path.exists():
        deployment_receipt = receipt(deployment_path, budget)
        try:
            deployment = json.loads(deployment_path.read_bytes())
            installed = deployment['commit']; files = deployment['files']
            if not isinstance(installed, str) or not re.fullmatch(r'[0-9a-f]{40}', installed) or not isinstance(files, dict):
                raise OfflineCaptureError('unsupported')
            if any(files.get(name) != sha for name, sha in source.items()): raise OfflineCaptureError('stale')
        except (ValueError, KeyError, TypeError) as error:
            if isinstance(error, OfflineCaptureError): raise
            raise OfflineCaptureError('unsupported') from error
    raw_inventory = {}
    for number, path in enumerate(sorted((root / 'raw').rglob('*'))):
        if number % 1024 == 0: budget.check()
        if path.is_file():
            info = path.stat(); raw_inventory[path.relative_to(root).as_posix()] = [info.st_size, info.st_mtime_ns]
    return dict(assets=assets, sources=source, raw_inventory=raw_inventory,
                freshness=freshness(root, budget), installed_revision=installed, deployment=deployment_receipt)


@contextmanager
def ownership(root):
    with ExitStack() as stack:
        if (root / 'data/deployment.pending.json').exists(): raise OfflineCaptureError('pending')
        try:
            stack.enter_context(runtime_access.ownership(root, exclusive=True, timeout=0))
        except RuntimeError as error:
            reason = 'pending' if (root / 'data/deployment.pending.json').exists() else 'busy'
            raise OfflineCaptureError(reason) from error
        try:
            stack.enter_context(cache_access.WorkspaceAccess(root / 'data/website-data-0.lock').hold(timeout=0))
        except ValueError as error:
            raise OfflineCaptureError('busy') from error
        yield


@contextmanager
def sqlite_failures(budget):
    try:
        yield
    except sqlite3.DatabaseError as error:
        if budget.failure is not None: raise budget.failure from error
        code = getattr(error, 'sqlite_errorcode', -1) & 255
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise OfflineCaptureError('busy') from error
        if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
            raise OfflineCaptureError('unsupported') from error
        if code == sqlite3.SQLITE_FULL: raise OfflineCaptureError('limit') from error
        raise


@contextmanager
def database(path, budget, *, readonly):
    uri = path.resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw')
    db = sqlite3.connect(uri, uri=True, timeout=0)
    try:
        db.execute('PRAGMA busy_timeout=0'); db.execute('PRAGMA cache_size=-8192')
        if readonly: db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(budget.sqlite_progress, 100000)
        yield db
    finally:
        db.close()


def metadata(db):
    return artifacts.metadata(db, OfflineCaptureError, reason='unsupported')


def table_hash(db, table, budget):
    return artifacts.table_hash(db, table, budget, OfflineCaptureError,
                                reason='unsupported', every=1024, pool_order=False)


def validate(research, daily, before, report_sha, budget, *, integrity):
    for db, expected in ((research, RESEARCH_TABLES), (daily, DAILY_TABLES)):
        artifacts.schema(db, expected, budget, OfflineCaptureError,
                         reason='unsupported', integrity=integrity, integrity_first=False)
    r, d = metadata(research), metadata(daily)
    if r.get('version') != 7 or not isinstance(d.get('daily_inputs'), dict) or d['daily_inputs'].get('version') != 3:
        raise OfflineCaptureError('unsupported')
    if r.get('inputs') != d['daily_inputs'].get('inputs'): raise OfflineCaptureError('mismatch')
    current = before['freshness']
    if r.get('inputs') != current['inputs'] or r.get('prices') != current['prices'] or d['daily_inputs'] != current['daily_inputs']:
        raise OfflineCaptureError('stale')
    if r.get('baseline_report_sha') != report_sha: raise OfflineCaptureError('mismatch')
    artifacts.shared_rows(research, daily, lambda db, table: table_hash(db, table, budget), OfflineCaptureError)
    return r, d


def capture_offline(runtime, destination, *, cancel=None, progress=None):
    """Own one offline copy. Concurrent starts can wait; no originals are fixed."""
    root, destination = Path(runtime).resolve(), Path(destination).resolve()
    if destination == root / 'tmp' or not destination.is_relative_to(root / 'tmp') or destination.exists():
        raise OfflineCaptureError('unsupported')
    if not (root / 'data').is_dir(): raise OfflineCaptureError('unsupported')
    budget = Budget(cancel, progress)
    attempt = uuid.uuid4().hex
    stage = destination / ('staging-' + attempt)
    began = False
    try:
        with ownership(root), sqlite_failures(budget):
            budget.event('capture_start')
            preflight(root)
            source_size = sum((root / relative).stat().st_size for relative in DATABASES.values())
            if source_size > MAX_DATABASE_BYTES: raise OfflineCaptureError('limit')
            destination.parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(destination.parent).free < source_size + 64 * 1024 ** 2: raise OfflineCaptureError('limit')
            destination.mkdir(); began = True; stage.mkdir()
            (destination / 'attempt.json').write_bytes(encoded(dict(attempt=attempt, status='started')))
            before = originals(root, budget)
            # Persist before copying so an external watchdog leaves independently
            # checkable original evidence beside the unfinished attempt.
            (destination / 'originals-before.json').write_bytes(encoded(before))
            budget.event('originals_verified', database_bytes=source_size)
            report_bytes = (root / REPORT).read_bytes()
            if hashlib.sha256(report_bytes).hexdigest() != before['assets'][REPORT]['sha256']:
                raise OfflineCaptureError('changed-original')
            (stage / 'report.txt').write_bytes(report_bytes)
            with ExitStack() as connections:
                sources = [connections.enter_context(database(root / relative, budget, readonly=True)) for relative in DATABASES.values()]
                original_metadata = validate(*sources, before, before['assets'][REPORT]['sha256'], budget, integrity=False)
                for (name, _), source in zip(DATABASES.items(), sources):
                    budget.event('backup_start', database=name)
                    path = stage / name; path.touch(exist_ok=False)
                    with database(path, budget, readonly=False) as target:
                        page_size = source.execute('PRAGMA page_size').fetchone()[0]
                        source.backup(target, pages=max(1, 256 * 1024 // page_size), progress=budget.backup_progress, sleep=0)
                    if sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()) > MAX_OUTPUT_BYTES: raise OfflineCaptureError('limit')
            with ExitStack() as connections:
                copies = [connections.enter_context(database(stage / name, budget, readonly=True)) for name in DATABASES]
                copied_metadata = validate(*copies, before, hashlib.sha256(report_bytes).hexdigest(), budget, integrity=True)
                if copied_metadata != original_metadata: raise OfflineCaptureError('mismatch')
                budget.event('semantic_validation')
                base_hashes = {table: table_hash(copies[1], table, budget) for table in DAILY_BASE}
                research_hashes = {table: table_hash(copies[0], table, budget) for table in RESEARCH_TABLES if table != 'metadata'}
                semantic = digest(dict(research=research_hashes, daily_base=base_hashes,
                    metadata=copied_metadata, report=hashlib.sha256(report_bytes).hexdigest(), sources=before['sources']))
            budget.event('destination_verified')
            artifacts = {path.name: receipt(path, budget) for path in stage.iterdir()}
            try:
                after = originals(root, budget)
            except OfflineCaptureError as error:
                if error.reason in ('cancelled', 'limit'): raise
                raise OfflineCaptureError('changed-original') from error
            except FileNotFoundError as error:
                raise OfflineCaptureError('changed-original') from error
            if after != before: raise OfflineCaptureError('changed-original')
            manifest = dict(version=1, capture_id=attempt, financial_generation=semantic,
                installed_revision=before['installed_revision'], originals=before,
                metadata=dict(zip(('research', 'daily'), copied_metadata)), artifacts=artifacts,
                limits=dict(database_bytes=MAX_DATABASE_BYTES, output_bytes=MAX_OUTPUT_BYTES,
                    sampled_current_memory_bytes=MAX_MEMORY_BYTES, wall_seconds=MAX_SECONDS),
                benchmark_admitted=False, originals_unchanged=True)
            (stage / 'capture.json').write_bytes(encoded(manifest))
            if sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()) > MAX_OUTPUT_BYTES: raise OfflineCaptureError('limit')
            budget.check()
            published = destination / ('capture-' + attempt)
            stage.rename(published)
            (destination / 'attempt.json').write_bytes(encoded(dict(attempt=attempt, status='complete', capture=published.name)))
            budget.event('capture_complete', capture=str(published))
            return published
    except BaseException as error:
        if began:
            reason = error.reason if isinstance(error, OfflineCaptureError) else 'unexpected'
            (destination / 'failure.json').write_bytes(encoded(dict(attempt=attempt, reason=reason, error_type=type(error).__name__)))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    try:
        capture_offline(args.runtime, args.destination, progress=lambda event: print(json.dumps(event), flush=True))
    except BaseException as error:
        reason = error.reason if isinstance(error, OfflineCaptureError) else 'unexpected'
        print(json.dumps(dict(event='capture_failed', reason=reason, error_type=type(error).__name__)), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Benchmark-only prepared input validation with unchanged edit visibility.

Every validation enumerates the annual assets again. Directory enumeration is
an implementation of the current size/mtime contract, not a replacement token,
watcher or permission to defer manual-edit detection until restart.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path, checkpoint=lambda: None):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for part in iter(lambda: source.read(64 * 1024), b''):
            checkpoint()
            result.update(part)
    return result.hexdigest()


def _entries(path, checkpoint=lambda: None):
    try:
        with os.scandir(path) as entries:
            result = []
            for entry in entries:
                checkpoint(); result.append(entry)
            return result
    except (FileNotFoundError, NotADirectoryError):
        return []


def signature(research, checkpoint=lambda: None):
    """Return the authoritative signature using one fresh stat per asset.

    Matching directories and followed symlinks use the same treatment as
    Path.glob/Path.stat. No DirEntry or file metadata survives this invocation.
    Attach compares this result with research.signature before it can be used.
    """
    r = research
    paths = [r.RAW / name for name in
             ('universe.json', 'metrics.jsonl', 'spy-div.json', 'treasury.json')]
    paths += [r.RAW / 'px', Path(r.baseline.__file__), Path(r.__file__),
              Path(r.metrics.__file__), Path(r.books.__file__),
              Path(r.cache_assets.__file__), Path(r.run.__file__),
              Path(r.revalue.__file__), Path(r.financial_inputs.__file__)]
    result = {}
    for path in paths:
        checkpoint()
        info = path.stat()
        result[path.relative_to(r.ROOT).as_posix()] = [
            'directory' if stat.S_ISDIR(info.st_mode) else info.st_size,
            info.st_mtime_ns]
    for endpoint in _entries(r.RAW / 'financial-inputs', checkpoint):
        if not endpoint.is_dir():
            continue
        for asset in _entries(endpoint.path, checkpoint):
            checkpoint()
            # Path.glob is case-sensitive on POSIX and insensitive on Windows.
            name = asset.name.lower() if os.name == 'nt' else asset.name
            if not name.endswith('.json'):
                continue
            info = asset.stat()
            path = Path(asset.path)
            result[path.relative_to(r.ROOT).as_posix()] = [
                'directory' if stat.S_ISDIR(info.st_mode) else info.st_size,
                info.st_mtime_ns]
    result['historical_through'] = str(r.baseline.cutoff(
        (r.RESULTS / 'summary-exits.txt').read_text(encoding='utf-8')))
    return result


def metadata(path, checkpoint=lambda: None):
    """Read current-path metadata, including after an atomic database replacement."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro',
                                uri=True, timeout=0)) as db:
        # Callback exceptions must retain their reason, not become a generic
        # SQLite interrupted error. Reading a row is one cooperative work unit.
        failure = []
        def progress():
            try: checkpoint(); return 0
            except BaseException as error: failure.append(error); return 1
        db.set_progress_handler(progress, 100)
        try:
            result = {}
            for key, value in db.execute('SELECT key,value FROM metadata'):
                checkpoint(); result[key] = json.loads(value)
            checkpoint()
            return result
        except sqlite3.Error:
            if failure: raise failure[0]
            raise


class PreparedGeneration:
    """Reject invalid attachment reuse before calculation; never repair inputs.

    Validate current journals, prepared metadata, full report binding, policy
    dependencies and the complete request-visible source inventory. The compact
    identity supplements a fresh inventory scan on every request. Caller holds
    project/cache ownership through validation, native work and final closure.
    """
    def __init__(self, inputs, schedules, *, sources=()):
        self.inputs, self.s = inputs, schedules
        self.root = Path(schedules.r.ROOT)
        self.sources = tuple(Path(path) for path in sources)
        self.source_hashes = {str(path): file_hash(path) for path in self.sources}
        self.numeric_signature = inputs.signature
        self.policy_signature = inputs.policy.signature
        self.stats = {}
        self._journals()
        began = time.perf_counter()
        authoritative = schedules.r.signature()
        self.stats['authoritative_scan_seconds'] = time.perf_counter() - began
        began = time.perf_counter()
        observed = signature(schedules.r)
        self.stats['inventory_scan_seconds'] = time.perf_counter() - began
        if authoritative != observed:
            raise ValueError('Prepared-generation inventory differs from the authoritative scan.')
        self.inventory = observed
        self.daily = metadata(schedules.DATABASE)
        self.research = metadata(schedules.r.DATABASE)
        self.report_hash = file_hash(schedules.r.RESULTS / 'summary-exits.txt')
        self._attachment(self.daily)
        self._prepared(observed, self.daily, self.research, self.report_hash)
        self.identity = digest(dict(version=1, numeric=self.numeric_signature,
            policy=self.policy_signature, daily=self.daily.get('daily_inputs'),
            research=self.research, report=self.report_hash,
            sources=self.source_hashes))
        self.stats.update(identity=self.identity, inventory_entries=len(observed),
                          inventory_sha256=digest(observed),
                          inventory_agreement='exact', manual_edits='every_request')

    def _journals(self):
        for name in ('deployment.pending.json', 'research.sqlite.publication.json'):
            if (self.root / 'data' / name).exists():
                raise ValueError('Unfinished publication blocks prepared-generation reuse.')

    def _prepared(self, inventory, daily, research, report_hash):
        engine = {}
        for path in (Path(self.s.__file__), Path(self.s.__file__).with_name('book_batch.py'),
                     Path(self.s.__file__).with_name('schedule_calendar.py'),
                     Path(self.s.__file__).with_name('portfolio_results.py')):
            info = path.stat()
            engine[path.name] = [info.st_size, info.st_mtime_ns]
        accepted_prices = research.get('prices')
        if not isinstance(accepted_prices, dict):
            raise ValueError('Research price inventory is missing; retry preparation.')
        expected = dict(version=self.s.VERSION, inputs=inventory,
                        prices=digest(accepted_prices), engine=engine)
        if daily.get('daily_inputs') != expected:
            raise ValueError('Daily prepared generation changed; retry preparation.')
        if research.get('version') != self.s.r.SCHEMA_VERSION or research.get('inputs') != inventory:
            raise ValueError('Research prepared generation changed; retry preparation.')
        if research.get('baseline_report_sha') != report_hash:
            raise ValueError('Report content differs from its prepared generation.')

    def _attachment(self, daily):
        if self.inputs.generation is None or json.loads(self.inputs.generation) != daily.get('daily_inputs'):
            raise ValueError('Numerical inputs belong to a different prepared generation.')
        policy = self.inputs.policy
        actual = {Path(path).name: file_hash(path) for path in policy.source_paths}
        if actual != policy.source_hashes:
            raise ValueError('Attached policy source dependencies changed.')

    def validate(self):
        self._journals()
        observed = signature(self.s.r)
        daily, research = metadata(self.s.DATABASE), metadata(self.s.r.DATABASE)
        report_hash = file_hash(self.s.r.RESULTS / 'summary-exits.txt')
        self._attachment(daily)
        self._prepared(observed, daily, research, report_hash)
        if observed != self.inventory or daily.get('daily_inputs') != self.daily.get('daily_inputs') or research != self.research:
            raise ValueError('Attached prepared generation is stale.')
        if report_hash != self.report_hash:
            raise ValueError('Attached report generation changed.')
        if self.inputs.signature != self.numeric_signature or self.inputs.policy.signature != self.policy_signature:
            raise ValueError('Attached numerical or policy identity changed.')
        if self.source_hashes != {str(path): file_hash(path) for path in self.sources}:
            raise ValueError('Prepared-generation source dependencies changed.')
        self._journals()
        return self.identity

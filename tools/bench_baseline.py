"""Frozen production-engine baseline on disposable databases; never download data.

Execution is closed until bound input ownership and resource/availability
admission are qualified. The retained freeze/run/verify protocol describes
historical measurements. Source-only bootstrap remains available for synthetic
imports under source ownership; it does not admit benchmark execution.
"""
import argparse
import atexit
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time
from unittest.mock import patch

import bench_admission as admission

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = 1
SEEDS = (42, 20261022, 20261023)
POOLS = ('legacy', 'cached')
START, END = '1997-01-01', '2025-12-31'
DERIVED = ('period_pools', 'filter_values', 'screening_metrics', 'snapshots',
           'latest_snapshots', 'baseline_prices', 'baseline_periods', 'periods')
OPTIONS = dict(rank_from=1, rank_to=50, metric='ev_ebitda', min_cap=100e6,
               max_cap=None, min_ev=50e6, min_yield=0., max_multiple=None,
               sector=None, exchange=None, filters=[])
PROFILES = dict(F0=[], F1=[dict(field='pb', op='lt', value=3.),
                         dict(field='roe', op='gt', value=10.)],
                F2=[dict(field='return_1y', op='gt', value=0.),
                    dict(field='return_3y', op='gt', value=0.)])
_runtime_stack = ExitStack()
atexit.register(_runtime_stack.close)
s = batch = robust = coordinator = None
_original_initialize = None


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


_loaded_tool_sha256 = file_hash(__file__)


def assert_tool(expected=None):
    """Reject edits to the benchmark script while an execution can import it."""
    if file_hash(__file__) != (expected or _loaded_tool_sha256):
        raise ValueError('Benchmark tool changed during execution; retry with fresh evidence.')


def publish(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.building')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def bootstrap(runtime):
    """Own committed runtime source before importing any financial application code."""
    global s, batch, robust, coordinator, _original_initialize
    runtime = Path(runtime).resolve()
    if s is not None:
        if Path(s.r.ROOT).resolve() != runtime:
            raise ValueError('A process cannot attach two source runtimes.')
        return
    sys.path[:0] = [str(runtime / 'website'), str(runtime / 'scripts')]
    import runtime_access
    _runtime_stack.enter_context(runtime_access.ownership(runtime))
    import schedules
    import book_batch
    import robustness
    import cache_access
    s, batch, robust, coordinator = schedules, book_batch, robustness, cache_access
    _original_initialize = batch.initialize_worker
    for module in (s, batch, robust, s.r, s.metrics):
        if not Path(module.__file__).resolve().is_relative_to(runtime):
            raise ValueError('Financial imports must come from the selected runtime.')


# Native spawned children import this entry point before unpickling application
# work. Hold source ownership through interpreter exit, including failed workers.
if os.environ.get('BACKTEST_BASELINE_RUNTIME'):
    assert_tool(os.environ.get('BACKTEST_BASELINE_TOOL_SHA256'))
    bootstrap(os.environ['BACKTEST_BASELINE_RUNTIME'])


def observed_initialize(path, expected):
    """Measure real spawned-worker startup without changing worker calculations."""
    assert_tool(os.environ.get('BACKTEST_BASELINE_TOOL_SHA256'))
    source_seconds = 0.
    signature = s.r.signature
    def observed_signature():
        nonlocal source_seconds
        began = time.perf_counter()
        try:
            return signature()
        finally:
            source_seconds += time.perf_counter() - began
    began = time.perf_counter()
    with patch.object(s.r, 'signature', observed_signature):
        _original_initialize(path, expected)
    destination = Path(os.environ['BACKTEST_BASELINE_TELEMETRY']) / (str(os.getpid()) + '.json')
    publish(destination, dict(pid=os.getpid(), initialization_seconds=time.perf_counter()-began,
                              signature_seconds=source_seconds))


def compare(left, right):
    """Compare ordered evidence; categorical values/missingness are exact.

    Numeric fields use the baseline engine's fixed 1e-12 relative/absolute
    tolerances. Integer identities remain exact. Return maximum absolute and
    relative differences, rather than rounding values before comparison.
    """
    maximum_absolute = maximum_relative = 0.
    def walk(a, b, path):
        nonlocal maximum_absolute, maximum_relative
        if type(a) is not type(b):
            raise ValueError('Evidence type differs at ' + path)
        if type(a) is float:
            if not math.isfinite(a) or not math.isfinite(b):
                raise ValueError('Nonfinite evidence at ' + path)
            absolute = abs(a-b)
            relative = absolute / max(abs(a), abs(b)) if a or b else 0.
            maximum_absolute = max(maximum_absolute, absolute)
            maximum_relative = max(maximum_relative, relative)
            if not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError('Numeric evidence differs at ' + path)
        elif isinstance(a, dict):
            if a.keys() != b.keys():
                raise ValueError('Evidence fields differ at ' + path)
            for key in a:
                walk(a[key], b[key], path + '.' + key)
        elif isinstance(a, list):
            if len(a) != len(b):
                raise ValueError('Evidence lengths differ at ' + path)
            for index, (x, y) in enumerate(zip(a, b)):
                walk(x, y, path + '[' + str(index) + ']')
        elif a != b:
            raise ValueError('Evidence differs at ' + path)
    walk(left, right, '$')
    return dict(maximum_absolute=maximum_absolute, maximum_relative=maximum_relative,
                exact=digest(left) == digest(right))


def options(pool, profile):
    return dict(OPTIONS, pool=pool, filters=PROFILES[profile])


def freeze(db):
    """Freeze dates independently of pool/profile, then make all defaults explicit."""
    sessions = [tuple(row) for row in db.execute('SELECT day,price FROM sessions ORDER BY day')]
    if not sessions or sessions[0][0] > START or sessions[-1][0] < END:
        raise ValueError('Saved SPY cache does not cover the required 1997–2025 endpoints.')
    samples = {}
    for seed in SEEDS:
        config = robust.plan(db, start=START, end=END, months=12, trials=24,
                             seed=seed, **options('legacy', 'F0'))
        samples[str(seed)] = {key: value for key, value in config.items() if key != 'options'}
    qualification = [dict(id='mixed', overrides=dict(filters=PROFILES['F1']+PROFILES['F2'])),
                     dict(id='three_year', overrides=dict(metric='ev_ebitda_3y')),
                     dict(id='top100', overrides=dict(rank_to=100)),
                     dict(id='empty', overrides=dict(sector='__NO_SUCH_SECTOR__'))]
    manifest = dict(protocol=PROTOCOL, start=START, end=END, months=12, trials=24,
                    seeds=list(SEEDS), pools=list(POOLS), defaults=OPTIONS, profiles=PROFILES,
                    worker_policy=dict(requested=None, automatic_max=batch.DEFAULT_WORKERS,
                                       minimum_missing_books=batch.MIN_PARALLEL_BOOKS),
                    sessions_sha256=digest(sessions), samples=samples,
                    primary_cases=[dict(id=f'{pool}-{profile}-{seed}', pool=pool, profile=profile, seed=seed)
                                   for seed in SEEDS for pool in POOLS for profile in PROFILES],
                    correctness_inventory=qualification,
                    correctness_contract=['Exact holding order, symbols, ranks, dates and statuses',
                                          'Full valuations, returns, missingness and coverage',
                                          'Repeated frozen dates on another fresh database',
                                          'Separate exact saved-book replay',
                                          'Strict thresholds, both pools, both metric IDs',
                                          '1e-12 relative and absolute numerical tolerance'])
    manifest['sha256'] = digest(manifest)
    return manifest


def validate_manifest(manifest, db):
    expected = dict(manifest)
    claimed = expected.pop('sha256', None)
    if claimed != digest(expected) or manifest.get('protocol') != PROTOCOL:
        raise ValueError('Invalid workload manifest identity.')
    if manifest != freeze(db):
        raise ValueError('Frozen workloads differ from current sessions, planner or defaults.')


def configuration(manifest, case, db):
    result = robust.plan(db, start=manifest['start'], end=manifest['end'], months=manifest['months'],
                         trials=manifest['trials'], seed=case['seed'], **options(case['pool'], case['profile']))
    expected = dict(manifest['samples'][str(case['seed'])], options=options(case['pool'], case['profile']))
    if result != expected:
        raise ValueError('Planner changed the frozen samples or request options.')
    return result


def clear_books(db):
    """Clear disposable derived rows, never immutable price/report/company inputs."""
    with db:
        for table in DERIVED:
            db.execute('DELETE FROM ' + table)
    counts = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in DERIVED}
    if any(counts.values()):
        raise ValueError('Fresh run contains derived results.')
    return counts


def raw_inventory(root):
    """Metadata inventory is mutation evidence, explicitly not a content hash."""
    return {path.relative_to(root).as_posix(): [stat.st_size, stat.st_mtime_ns]
            for path in sorted((root/'raw').rglob('*')) if path.is_file()
            for stat in [path.stat()]}


def identity(root):
    """Capture content identities for executable source, report and prepared DBs."""
    if (root/'data/deployment.pending.json').exists() or (root/'data/research.sqlite.publication.json').exists():
        raise ValueError('An unfinished source or baseline publication blocks measurement.')
    deployment = load(root/'data/deployment.json') if (root/'data/deployment.json').exists() else None
    sources = {}
    for directory in ('scripts', 'website'):
        for path in sorted((root/directory).glob('*.py')):
            relative = path.relative_to(root).as_posix()
            sources[relative] = file_hash(path)
            if deployment and deployment['files'].get(relative) != sources[relative]:
                raise ValueError('Installed application source differs from its deployment manifest.')
    databases = {}
    for name in ('research.sqlite', 'schedules.sqlite'):
        path = root/'data'/name
        stat = path.stat()
        databases[name] = dict(sha256=file_hash(path), bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(path)+suffix)
            if sidecar.exists() and sidecar.stat().st_size:
                databases[name][suffix] = dict(sha256=file_hash(sidecar), bytes=sidecar.stat().st_size)
    with closing(sqlite3.connect((root/'data/schedules.sqlite').resolve().as_uri()+'?mode=ro', uri=True)) as db:
        daily = json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
        books = {table: db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in DERIVED}
    return dict(deployment_commit=deployment['commit'] if deployment else None,
                source_sha256=sources, daily_generation=daily,
                report_sha256=file_hash(root/'results/summary-exits.txt'), databases=databases,
                real_derived_counts=books, raw_inventory_sha256=digest(raw_inventory(root)))


class Delivery:
    """Encode website NDJSON event shapes and wait for local socket receipt."""
    def __init__(self):
        self.writer, reader = socket.socketpair()
        self.bytes = self.events = 0
        self.encoding_seconds = self.sending_seconds = 0.
        self.received = 0
        self.error = None
        def consume():
            try:
                with reader:
                    while True:
                        block = reader.recv(65536)
                        if not block:
                            break
                        self.received += len(block)
            except BaseException as error:
                self.error = error
        self.thread = Thread(target=consume, daemon=True)
        self.thread.start()
    def send(self, value):
        began = time.perf_counter()
        block = (json.dumps(value, allow_nan=False)+'\n').encode()
        self.encoding_seconds += time.perf_counter()-began
        began = time.perf_counter()
        self.writer.sendall(block)
        self.sending_seconds += time.perf_counter()-began
        self.events += 1
        self.bytes += len(block)
    def close(self):
        self.writer.close()
        self.thread.join(timeout=30)
        if self.thread.is_alive() or self.error or self.received != self.bytes:
            raise ValueError('Local response transport did not receive the complete response.')


def windows_processes(*, include_pids=None):
    """One sampled process tree snapshot using native stdlib APIs."""
    import ctypes as c
    from ctypes import wintypes as w
    class Entry(c.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD),
                    ('heap', c.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
                    ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD),
                    ('exe', w.WCHAR*260)]
    class Memory(c.Structure):
        _fields_ = [('cb', w.DWORD), ('faults', w.DWORD)] + [(name, c.c_size_t) for name in
                    ('peak_working', 'working', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged',
                     'pagefile', 'peak_pagefile', 'private')]
    class IO(c.Structure):
        _fields_ = [(name, c.c_ulonglong) for name in ('reads', 'writes', 'other', 'read_bytes', 'written_bytes', 'other_bytes')]
    kernel = c.WinDLL('kernel32', use_last_error=True)
    psapi = c.WinDLL('psapi', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [w.HANDLE, c.POINTER(Entry)]
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.GetProcessIoCounters.argtypes = [w.HANDLE, c.POINTER(IO)]
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.POINTER(Memory), w.DWORD]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == w.HANDLE(-1).value:
        raise OSError('Cannot sample native processes.')
    entries = []
    try:
        entry = Entry();entry.size = c.sizeof(entry)
        present = kernel.Process32FirstW(snapshot, c.byref(entry))
        while present:
            entries.append((entry.pid, entry.parent, entry.threads))
            present = kernel.Process32NextW(snapshot, c.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    descendants = {os.getpid()}
    while True:
        expanded = descendants | {pid for pid, parent, unused in entries if parent in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    if include_pids is not None:
        descendants = set(include_pids)
    result = {}
    for pid, parent, threads in entries:
        if pid not in descendants:
            continue
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            continue
        try:
            memory = Memory();memory.cb = c.sizeof(memory)
            io = IO()
            if not psapi.GetProcessMemoryInfo(handle, c.byref(memory), c.sizeof(memory)):
                continue
            if not kernel.GetProcessIoCounters(handle, c.byref(io)):
                continue
            result[str(pid)] = dict(private_bytes=memory.private, working_set=memory.working,
                                    threads=threads, written_bytes=io.written_bytes, read_bytes=io.read_bytes)
        finally:
            kernel.CloseHandle(handle)
    return result


class Resources:
    """Sample process-tree peaks; exited-between-samples processes can be missed."""
    def __init__(self):
        self.stop = Event()
        self.interval = .2
        self.error = None
        self.peaks = dict(private_bytes=0, working_set=0, threads=0, processes=0)
        self.io = {}
        self.initial_io = {}
        self.samples = 0
        self.supported = os.name == 'nt'
        self.thread = None
    def sample(self):
        processes = windows_processes()
        self.samples += 1
        for key in ('private_bytes', 'working_set', 'threads'):
            self.peaks[key] = max(self.peaks[key], sum(row[key] for row in processes.values()))
        self.peaks['processes'] = max(self.peaks['processes'], len(processes))
        for pid, row in processes.items():
            self.initial_io.setdefault(pid, {key: row[key] if pid == str(os.getpid()) else 0 for key in ('written_bytes', 'read_bytes')})
            self.io[pid] = {key: max(self.io.get(pid, {}).get(key, 0), row[key]) for key in ('written_bytes', 'read_bytes')}
    def start(self):
        if self.supported:
            self.sample()
            def monitor():
                try:
                    while not self.stop.wait(self.interval):
                        self.sample()
                except BaseException as error:
                    self.error = type(error).__name__
            self.thread = Thread(target=monitor, daemon=True)
            self.thread.start()
    def finish(self):
        if self.thread:
            self.stop.set();self.thread.join();self.sample()
        return dict(supported=self.supported, sampling_seconds=self.interval, samples=self.samples,
                    sampled_tree_peaks=self.peaks if self.supported else None,
                    sampled_io_bytes={key: sum(row[key]-self.initial_io[pid][key] for pid, row in self.io.items())
                                      for key in ('written_bytes', 'read_bytes')} if self.supported else None,
                    error=self.error,
                    limitations='Sampled aggregate process-tree peaks, not exact instantaneous maxima. Child I/O after its final sample can be missed; counters include benchmark observation.')


def request(database, manifest, case, telemetry, *, require_fresh=True):
    """Timed adapter: ordinary freshness scan, planner, batch, NDJSON delivery.

    Base clone/reset and bulk holding serialization are excluded. Observing
    holding references, stage clocks and sampled resources are included.
    Socket transport is equivalent local delivery, not the production HTTP server.
    """
    admission.require_execution()
    assert_tool()
    telemetry.mkdir(parents=True, exist_ok=True)
    # Interrupted attempts retain their own evidence. Only this new directory
    # belongs to the current request, even when the case/phase is retried.
    attempt = Path(tempfile.mkdtemp(prefix='attempt-', dir=telemetry))
    os.environ['BACKTEST_BASELINE_TELEMETRY'] = str(attempt)
    holdings = []
    stages = dict(signature_seconds=0., selection_seconds=0.)
    signature, select, summarize = s.r.signature, s.r._select, robust.summarize
    def observed_signature():
        began = time.perf_counter()
        try:
            return signature()
        finally:
            stages['signature_seconds'] += time.perf_counter()-began
    def observed_select(*args, **kwargs):
        began = time.perf_counter()
        try:
            return select(*args, **kwargs)
        finally:
            stages['selection_seconds'] += time.perf_counter()-began
    def observed_summary(result, number, dates):
        holdings.append({key: value for key, value in result.items() if key != 'seconds'})
        return summarize(result, number, dates)
    def progress(payload):
        delivery.send(payload)
        if payload.get('type') == 'progress' and payload.get('completed') == payload.get('trial') and payload.get('completed') in (1, 8, 16, 24):
            print(json.dumps(dict(event='trial_complete', case=case['id'],
                                  phase='fresh' if require_fresh else 'replay',
                                  completed=payload['completed'])), flush=True)
    resources = Resources();resources.start()
    delivery = Delivery()
    began = time.perf_counter()
    db = None
    try:
        with patch.object(s.r, 'signature', observed_signature), patch.object(s.r, '_select', observed_select), \
                patch.object(robust, 'summarize', observed_summary), \
                patch.object(batch, 'initialize_worker', observed_initialize):
            validation = time.perf_counter()
            db = s.connect(database)
            db.execute('PRAGMA cache_size=-131072')
            initial = {table: db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in DERIVED}
            if require_fresh and any(initial.values()):
                raise ValueError('Fresh request found saved derived rows.')
            config = configuration(manifest, case, db)
            stages['validation_seconds'] = time.perf_counter()-validation
            delivery.send(dict(type='configuration', configuration=config))
            result = robust.run(db, config, progress=progress)
            delivery.send(dict(type='complete', result=result))
            db.close();db = None
            delivery.close()
            elapsed = time.perf_counter()-began
    finally:
        if db:
            db.close()
        if delivery.writer.fileno() != -1:
            delivery.close()
        resource_report = resources.finish()
    if len(holdings) != manifest['trials'] or result['completed'] != manifest['trials']:
        raise ValueError('Incomplete evidence capture.')
    if require_fresh and result['execution']['reused_books']:
        raise ValueError('Fresh request reused a saved book.')
    stages.update(encoding_seconds=delivery.encoding_seconds, socket_send_seconds=delivery.sending_seconds,
                  calculation_wait_seconds=result['execution']['calculation_wait_seconds'],
                  publication_seconds=result['execution']['write_seconds'])
    summary = {key: value for key, value in result.items() if key not in ('seconds', 'execution', 'trials')}
    summary['trials'] = [{key: value for key, value in trial.items() if key != 'seconds'} for trial in result['trials']]
    initialization = [load(path) for path in sorted(attempt.glob('*.json'))]
    expected_workers = result['execution']['workers'] if result['execution']['workers'] > 1 else 0
    if len(initialization) != expected_workers:
        raise ValueError('Worker initialization evidence does not match this request.')
    assert_tool()
    return dict(wall_seconds=elapsed, stages=stages, resources=resource_report, summary=summary,
                execution=result['execution'], initial_derived_counts=initial,
                response=dict(bytes=delivery.bytes, received_bytes=delivery.received, events=delivery.events),
                telemetry_attempt=attempt.name, worker_initialization=initialization,
                valid=result['valid'], incomplete=result['incomplete'],
                database_bytes=database.stat().st_size), holdings


def evidence_path(workdir, case_id):
    return workdir/'evidence'/(case_id+'.json')


def verify_checkpoint(path, binding, workdir):
    """Only a complete checkpoint whose full evidence still hashes is reusable."""
    value = load(path)
    if value.get('binding') != binding or value.get('status') != 'complete':
        raise ValueError('Completed checkpoint belongs to different inputs or protocol.')
    evidence = workdir/value['evidence_file']
    if file_hash(evidence) != value['evidence_sha256']:
        raise ValueError('Checkpoint evidence content is missing or changed.')
    document = load(evidence)
    if len(document['fresh']) != 24 or compare(document['fresh'], document['replay'])['exact'] is not True:
        raise ValueError('Checkpoint replay or holding evidence is invalid.')
    if not compare(value['measurement']['summary'], value['replay']['summary'])['exact']:
        raise ValueError('Checkpoint aggregate evidence differs.')
    return value


def environment():
    power = None
    if os.name == 'nt':
        result = subprocess.run(['powercfg', '/getactivescheme'], capture_output=True,
                                text=True, check=False)
        power = result.stdout.strip() if result.returncode == 0 else 'unavailable'
    return dict(python=sys.version, platform=platform.platform(), sqlite=sqlite3.sqlite_version,
                logical_cpus=os.cpu_count(), machine=platform.machine(), processor=platform.processor(),
                native_windows=os.name == 'nt', tool_sha256=file_hash(__file__), active_power_scheme=power,
                thread_environment={key: os.environ.get(key) for key in
                                    ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                                     'NUMBA_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})


def assert_workdir(root, workdir):
    if not workdir.resolve().is_relative_to((root/'tmp').resolve()) or workdir.resolve() == (root/'tmp').resolve():
        raise ValueError('Benchmark workdir must be a dedicated folder below runtime tmp/.')


def runner(args):
    admission.require_execution()
    assert_tool()
    os.environ['BACKTEST_BASELINE_TOOL_SHA256'] = _loaded_tool_sha256
    root = Path(args.runtime).resolve()
    os.environ['BACKTEST_BASELINE_RUNTIME'] = str(root)
    bootstrap(root)
    workdir = Path(args.workdir).resolve()
    assert_workdir(root, workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    with coordinator.access():
        # Full preparation readiness, including report binding and raw prices,
        # runs before capturing the immutable baseline identity. Never prepare
        # silently here: preparation can publish a new canonical report.
        reference = s.r.connect(full_prices=True);reference.close()
        production = s.connect()
        try:
            manifest = freeze(production) if args.command == 'freeze' else load(args.manifest)
            validate_manifest(manifest, production)
            if args.command == 'freeze':
                publish(args.manifest, manifest)
                print(json.dumps(dict(event='frozen', manifest=str(args.manifest), sha256=manifest['sha256'])), flush=True)
                return
            before = identity(root)
            binding = dict(protocol=PROTOCOL, workload_sha256=manifest['sha256'], input_identity_sha256=digest(before),
                           environment=environment())
            checkpoints = workdir/'checkpoints';checkpoints.mkdir(exist_ok=True)
            completed = {}
            for case in manifest['primary_cases']:
                path = checkpoints/(case['id']+'.json')
                if path.exists():
                    completed[case['id']] = verify_checkpoint(path, binding, workdir)
            if args.command == 'run':
                template = workdir/'template.sqlite'
                began = time.perf_counter()
                with closing(sqlite3.connect(template)) as target:
                    production.backup(target)
                    clear_books(target)
                setup = time.perf_counter()-began
                pending = [case for case in manifest['primary_cases'] if case['id'] not in completed]
                if args.limit is not None:
                    pending = pending[:args.limit]
                for case in pending:
                    assert_tool()
                    case_id = case['id']
                    print(json.dumps(dict(event='case_start', case=case_id)), flush=True)
                    database = workdir/'active.sqlite'
                    shutil.copyfile(template, database)
                    telemetry = workdir/'telemetry'/case_id
                    with closing(sqlite3.connect(database)) as db:
                        if any(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in DERIVED):
                            raise ValueError('Template is not fresh.')
                    measurement, fresh = request(database, manifest, case, telemetry/'fresh')
                    replay_measurement, replay = request(database, manifest, case, telemetry/'replay', require_fresh=False)
                    parity = compare(fresh, replay)
                    if not parity['exact']:
                        raise ValueError('Current engine changed complete holdings on exact replay.')
                    if not compare(measurement['summary'], replay_measurement['summary'])['exact']:
                        raise ValueError('Current engine changed aggregate results on exact replay.')
                    document = dict(fresh=fresh, replay=replay)
                    repeated_measurement = None
                    if case == manifest['primary_cases'][0]:
                        shutil.copyfile(template, database)
                        repeated_measurement, repeated = request(database, manifest, case, telemetry/'fresh_repeat')
                        if not compare(fresh, repeated)['exact']:
                            raise ValueError('Repeated fresh explicit samples changed holdings.')
                        if not compare(measurement['summary'], repeated_measurement['summary'])['exact']:
                            raise ValueError('Repeated fresh explicit samples changed aggregate results.')
                        document['fresh_repeat'] = repeated
                    evidence = evidence_path(workdir, case_id)
                    publish(evidence, document)
                    if identity(root) != before:
                        raise ValueError('Production inputs changed during the baseline.')
                    assert_tool()
                    value = dict(status='complete', case=case, binding=binding, measurement=measurement,
                                 replay=replay_measurement, fresh_repeat=repeated_measurement,
                                 parity=parity, evidence_file=evidence.relative_to(workdir).as_posix(),
                                 evidence_sha256=file_hash(evidence), evidence_bytes=evidence.stat().st_size,
                                 created_utc=datetime.now(timezone.utc).isoformat(),
                                 production_unchanged=True, template_setup_seconds=setup)
                    publish(checkpoints/(case_id+'.json'), value)
                    completed[case_id] = value
                    database.unlink()
                    print(json.dumps(dict(event='case_complete', case=case_id,
                                          wall_seconds=measurement['wall_seconds'], valid=measurement['valid'],
                                          incomplete=measurement['incomplete'])), flush=True)
            if identity(root) != before:
                raise ValueError('Production inputs changed before verification completed.')
            assert_tool()
            report = dict(protocol=PROTOCOL, workload_sha256=manifest['sha256'], binding=binding, input_identity=before,
                          methodology=dict(boundary='schedules.connect through NDJSON socket receipt and database closure',
                                           production_http=False, base_dataset_loaded=False, fresh_books=True,
                                           automatic_workers=True, raw_invariance='All raw file paths, sizes and mtimes; not raw content hashes',
                                           prepared_invariance='Content hashes of research/daily DBs and sidecars, report, source; derived row counts',
                                           exclusions=['Preparation/readiness, source import, clone/reset, evidence JSON writing and invariance scans',
                                                       'Installation and compiler startup are not measured in this Python-only baseline'],
                                           overlaps='Selection and signature timers overlap validation. Worker init/signatures are concurrent; do not sum them with wall time. Calculation wait overlaps worker init and prefetch.',
                                           os_cache='Not flushed or controlled',
                                           power='Not changed by harness; record host power configuration separately',
                                           observer='Holding-reference capture, clocks, 200ms process sampling and worker telemetry included'),
                          completed=len(completed), pending=[case['id'] for case in manifest['primary_cases'] if case['id'] not in completed],
                          correctness_inventory=manifest['correctness_inventory'], qualification_status='Inventory frozen; no additional real-data qualification claimed',
                          runs=[completed[case['id']] for case in manifest['primary_cases'] if case['id'] in completed],
                          production_unchanged=True)
            publish(args.report, report)
            print(json.dumps(dict(event='report', completed=report['completed'], pending=len(report['pending']), report=str(args.report))), flush=True)
        finally:
            production.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'run', 'verify'))
    parser.add_argument('--runtime', type=Path, default=ROOT)
    parser.add_argument('--workdir', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--limit', type=int, help='Run this many pending cases; six first runs are the seed-42 pilots.')
    args = parser.parse_args()
    args.workdir = args.workdir or args.runtime/'tmp/cb01-baseline'
    args.report = args.report or args.workdir/'baseline.json'
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    runner(args)


if __name__ == '__main__':
    main()

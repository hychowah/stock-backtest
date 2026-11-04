"""Run this repository's test files by tier, each file in its own process.

    python3 tests/run.py [--tier fast|heavy|all] [--jobs N]

Entries are tests/test_*.py and tests/check-*.cjs. An entry is fast unless the
tables below name it, so a new test file joins the everyday gate. The fast
tier (default) gates every commit; the heavy tier holds slow qualification
workloads. No tier runs the files that FROZEN names (AGENTS.md, Tests). The
interpreter that runs this file runs every Python entry; .cjs entries need
node.

Each file runs in a new process group, with TMPDIR, TEMP and TMP set to a
private run folder under ~/.cache/ebitda-ev-spread-tests/. That place is on
disk and outside every checkout. The private input copy needs more free space
than a shared memory-backed /tmp can give. The run folder is removed when the
run ends. A file that exceeds its tier's time cap is killed with its group and
fails. The exit status is non-zero when any file fails or the run folder cannot
be removed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'tests'
RUNS = Path.home() / '.cache' / 'ebitda-ev-spread-tests'

# Tier tables. Every discovered entry not named here is fast. A listed name
# that does not exist, or a name in two tables, stops the run. Adding a name to
# HEAVY accepts a slow workload and needs the user's agreement.
HEAVY = frozenset()
# Tests of the frozen experimental engine (AGENTS.md, Tests). No tier runs
# them, and they need tmp/numerical-venv. No live test file imports one of
# them or a frozen source module directly; tests/test_package_structure.py
# scans the test files' imports. Run one directly when unfreezing; it may have
# drifted from live interfaces.
FROZEN = frozenset({
    'check-checkpoint-snapshots.cjs',
    'test_bounded_runtime.py',
    'test_bounded_trials.py',
    'test_candidate_calculations.py',
    'test_candidate_calendar_recovery.py',
    'test_evidence_browser.py',
    'test_guarded_numerical_entries.py',
    'test_input_engine_ownership.py',
    'test_legacy_selection_replay.py',
    'test_numerical_books.py',
    'test_numerical_calendar.py',
    'test_numerical_delegated.py',
    'test_numerical_dependencies.py',
    'test_numerical_execution.py',
    'test_numerical_expanded_admission.py',
    'test_numerical_factors.py',
    'test_numerical_formulas.py',
    'test_numerical_generation.py',
    'test_numerical_generation_hosts.py',
    'test_numerical_history.py',
    'test_numerical_matrix.py',
    'test_numerical_numba_books.py',
    'test_numerical_portfolios.py',
    'test_numerical_preparation.py',
    'test_numerical_profiles.py',
    'test_numerical_publication.py',
    'test_numerical_random.py',
    'test_numerical_readiness.py',
    'test_numerical_runtime.py',
    'test_numerical_scalar.py',
    'test_numerical_scalar_capabilities.py',
    'test_numerical_scalar_measurements.py',
    'test_numerical_scalar_native.py',
    'test_numerical_scalar_process.py',
    'test_numerical_scalar_qualification.py',
    'test_numerical_temporal.py',
    'test_numerical_trial.py',
    'test_numerical_trial_pool.py',
    'test_numerical_trials.py',
    'test_numerical_worker_control.py',
    'test_operating_spread_engine.py',
    'test_opt_in_readiness.py',
    'test_parallel_comparison.py',
    'test_phase11_candidate.py',
    'test_phase11_compiled_operations.py',
    'test_phase11_measurements.py',
    'test_scalar_admission.py',
    'test_trial_checkpoints.py',
    'test_website_engine_alignment.py',
})
# Files that match the entry patterns but are not standalone entries.
NOT_ENTRIES = frozenset({
    'check-screener.cjs',  # run by check_screener.py with SQL expectations
    'check-range.cjs',     # needs a built website/local; run after website/build.py
})
CAP_SECONDS = {'fast': 300, 'heavy': 3600}  # per file, set by the file's own tier
SLOW_FAST_SECONDS = 60
TAIL_LINES = 40
TAIL_BYTES = 64 * 1024


@dataclass(frozen=True)
class Entry:
    path: Path
    tier: str


@dataclass(frozen=True)
class Result:
    entry: Entry
    status: str  # PASS, FAIL or TIMEOUT
    seconds: float
    tail: str    # last lines of the file's output; empty for PASS


def select(tier):
    """Return the entries of a tier in start order and how many entries the
    tier leaves out. Frozen files and non-entries are never entries. First,
    stop if a table names a missing file or a file is in two tables."""
    names = {path.name for pattern in ('test_*.py', 'check-*.cjs') for path in TESTS.glob(pattern)}
    tables = (('HEAVY', HEAVY), ('FROZEN', FROZEN), ('NOT_ENTRIES', NOT_ENTRIES))
    listed = HEAVY | FROZEN | NOT_ENTRIES
    missing = sorted(listed - names)
    owners = {name: [table for table, members in tables if name in members] for name in sorted(listed)}
    twice = {name: found for name, found in owners.items() if len(found) > 1}
    if missing or twice:
        lines = ['The tier table in tests/run.py does not match tests/.']
        lines += [f'  not found: {name}' for name in missing]
        lines += [f"  in {' and '.join(found)}: {name}" for name, found in twice.items()]
        raise SystemExit('\n'.join(lines))
    entries = [Entry(TESTS / name, 'heavy' if name in HEAVY else 'fast') for name in names - FROZEN - NOT_ENTRIES]
    chosen = [entry for entry in entries if tier in ('all', entry.tier)]
    # Heavy files start first, so with --jobs above 1 their long caps overlap the rest.
    chosen.sort(key=lambda entry: (entry.tier != 'heavy', entry.path.name))
    return chosen, len(entries) - len(chosen)


def require_interpreters(entries):
    """Stop when a selected .cjs file has no node on PATH."""
    if any(entry.path.suffix == '.cjs' for entry in entries) and not shutil.which('node'):
        raise SystemExit('The selected checks include .cjs files, and node is not on PATH.')


class Run:
    """Own one run folder and every file process started in it.

    The folder is a new private directory under RUNS with temp/ (TMPDIR, TEMP
    and TMP for every file and its descendants) and logs/ (one log per file).
    Each file process leads a new process group (a process tree on Windows).
    close() refuses new starts, kills the groups still running, then removes
    the folder. It returns a removal problem instead of hiding it.

    Some test children start their own sessions, so a group kill misses them.
    On Linux, close() also kills every process that still carries this run's
    TMPDIR. Only close() can do that: all files of a run share the marker.
    """

    def __init__(self):
        RUNS.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix='run-', dir=RUNS))
        self.temp = self.folder / 'temp'
        self.logs = self.folder / 'logs'
        self.temp.mkdir()
        self.logs.mkdir()
        self._lock = threading.Lock()
        self._processes = set()
        self._closed = False

    def execute(self, entry, seconds):
        """Run one entry with a time cap in seconds and return its Result."""
        command = ([sys.executable, '-B', str(entry.path)] if entry.path.suffix == '.py'
                   else ['node', str(entry.path)])
        temp = str(self.temp)
        environment = dict(os.environ, TMPDIR=temp, TEMP=temp, TMP=temp, PYTHONUNBUFFERED='1')
        group = (dict(start_new_session=True) if os.name == 'posix'
                 else dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP))
        log = self.logs / (entry.path.name + '.log')
        started = time.monotonic()
        with open(log, 'wb') as output:
            with self._lock:
                if self._closed:
                    raise RuntimeError('The run is closed; no new file can start.')
                process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=output, stderr=subprocess.STDOUT, **group)
                self._processes.add(process)
            try:
                status = 'PASS' if process.wait(seconds) == 0 else 'FAIL'
            except subprocess.TimeoutExpired:
                _kill_group(process)
                process.wait()
                status = 'TIMEOUT'
            finally:
                with self._lock:
                    self._processes.discard(process)
        elapsed = time.monotonic() - started
        return Result(entry, status, elapsed, '' if status == 'PASS' else _tail(log))

    def close(self):
        """Refuse new starts, kill running groups and remove the folder.
        Return a description of a removal problem, or None."""
        with self._lock:
            self._closed = True
            running = list(self._processes)
        for process in running:
            _kill_group(process)
        for process in running:
            process.wait()
        deadline = time.monotonic() + 5
        while (escaped := self._escaped()) and time.monotonic() < deadline:
            for pid in escaped:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            time.sleep(0.1)
        try:
            shutil.rmtree(self.folder)
        except OSError as error:
            return f'Could not remove the run folder {self.folder}: {error}'
        return None

    def _escaped(self):
        """Return the pids whose TMPDIR is in this run's temp folder (Linux /proc only)."""
        marker = b'TMPDIR=' + os.fsencode(self.temp)
        found = []
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                variables = (proc / 'environ').read_bytes().split(b'\0')
            except OSError:
                continue
            if any(item == marker or item.startswith(marker + b'/') for item in variables):
                found.append(int(proc.name))
        return found


def _kill_group(process):
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _tail(log):
    with open(log, 'rb') as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - TAIL_BYTES))
        lines = stream.read().decode('utf-8', 'replace').splitlines()
    return '\n'.join(lines[-TAIL_LINES:])


def _positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return value


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the test files of one tier, each in its own process.')
    parser.add_argument('--tier', choices=('fast', 'heavy', 'all'), default='fast')
    parser.add_argument('--jobs', type=_positive,
                        help='files that run at the same time (default 8, or 1 when heavy files are selected)')
    args = parser.parse_args(argv)
    entries, left_out = select(args.tier)
    # Heavy fixtures hold the checkout's shared cache lock for minutes, and a
    # waiter gives up after 30 s, so heavy files only pass one at a time.
    jobs = args.jobs or (1 if any(entry.tier == 'heavy' for entry in entries) else 8)
    require_interpreters(entries)
    # Termination takes the interrupt path, so the run kills its groups first.
    for name in ('SIGTERM', 'SIGHUP'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _interrupt)

    run = Run()
    print(f'{args.tier} tier: {len(entries)} files, {jobs} at a time, run folder {run.folder}', flush=True)
    started = time.monotonic()
    results = []
    interrupted = False
    pool = ThreadPoolExecutor(max_workers=max(1, min(jobs, len(entries))))
    try:
        futures = [pool.submit(run.execute, entry, CAP_SECONDS[entry.tier]) for entry in entries]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f'{result.status:<7} {result.seconds:6.1f}s  {result.entry.path.name}', flush=True)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        # File processes lead their own sessions and miss the terminal's
        # interrupt, so kill them before the pool waits for its threads.
        problem = run.close()
        pool.shutdown(wait=True, cancel_futures=True)
    elapsed = time.monotonic() - started

    failed = sorted((result for result in results if result.status != 'PASS'), key=lambda r: r.entry.path.name)
    for result in failed:
        print(f'--- {result.entry.path.name} ({result.status}, last {TAIL_LINES} lines) ---')
        print(result.tail)
    slow = sorted((result for result in results
                   if result.entry.tier == 'fast' and result.seconds >= SLOW_FAST_SECONDS),
                  key=lambda r: -r.seconds)
    if slow:
        print(f"Fast files at {SLOW_FAST_SECONDS} s or more (move to HEAVY only with the user's agreement):")
        for result in slow:
            print(f'  {result.entry.path.name}  {result.seconds:.1f} s')
    summary = f'{args.tier} tier: {len(results) - len(failed)} passed, {len(failed)} failed in {elapsed:.1f} s.'
    if left_out:
        summary += f" Not run: {left_out} {'heavy' if args.tier == 'fast' else 'fast'} files."
    summary += f' Frozen, never run: {len(FROZEN)} files.'
    if interrupted:
        summary += f' Interrupted; {len(entries) - len(results)} files did not finish.'
    print(summary)
    if problem:
        print(problem, file=sys.stderr)
    if interrupted:
        return 130
    return 1 if failed or problem else 0


if __name__ == '__main__':
    sys.exit(main())

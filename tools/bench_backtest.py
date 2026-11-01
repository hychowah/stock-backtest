"""Offline, isolated end-to-end random-date engine comparisons.

Execution is closed until bound input ownership and resource/availability
admission are qualified. The retained protocol is historical. Each worker
gets a fresh SQLite copy on the same filesystem as the real daily database.
The template has no prepared dated books. File-copy/reset time is benchmark
setup, excluded for every engine; opening, loading, calculation, selection and
per-trial commits are timed. No network or third-party packages are needed.
"""
from array import array
from bisect import bisect_left, bisect_right
from contextlib import ExitStack
from datetime import date
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

try:
    import resource
except ImportError:  # Native Windows does not expose resource.getrusage.
    resource = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import bench_admission as admission
sys.path.insert(0, str(ROOT / 'scripts'))
import schedules as s
import robustness

MODES = ('sqlite_128mb', 'sqlite_512mb', 'sqlite_mmap', 'arrays',
         'arrays_shared_reports', 'selected_pool', 'arrays_selected_pool', 'production')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


class ArrayPrices:
    """Real sorted price histories, not recorded answers from another run."""
    def __init__(self, db):
        self.series = {}
        self.rows = 0
        self.bytes = 0
        self.calls = 0
        current = None
        for symbol, day, price, adjusted in db.execute(
                'SELECT symbol,day,price,adjusted FROM prices ORDER BY symbol,day'):
            if symbol != current:
                current = symbol
                parts = (array('i'), array('d'), array('i'), array('d'))
                self.series[symbol] = parts
            ordinal = date.fromisoformat(day).toordinal()
            if price is not None:
                parts[0].append(ordinal); parts[1].append(price)
            if adjusted is not None:
                parts[2].append(ordinal); parts[3].append(adjusted)
            self.rows += 1
        self.bytes = sum(len(a)*a.itemsize for parts in self.series.values() for a in parts)

    def price(self, db, symbol, day, column, forward=False, slack=None):
        self.calls += 1
        parts = self.series.get(symbol)
        if parts is None:
            return None
        days, values = parts[:2] if column == 'price' else parts[2:]
        ordinal = day.toordinal()
        index = bisect_left(days, ordinal) if forward else bisect_right(days, ordinal)-1
        if index < 0 or index >= len(days):
            return None
        actual = days[index]
        if slack is not None and abs(actual-ordinal) > slack:
            return None
        return date.fromordinal(actual), values[index]


def portable_result(result):
    """Keep every holding/value/status; remove only the measured runtime."""
    result = dict(result)
    result.pop('seconds', None)
    return result


def prepare_reference_period(db, entry, exit_day, books, cached, pool='legacy'):
    """Retain the pre-optimization eager preparation as a benchmark reference.

    Financial policy and metric calculators are still shared. Completion markers
    adapt the old two-pool implementation to the current daily cache schema.
    """
    existing = db.execute('SELECT year FROM periods WHERE entry=? AND exit=?',
                          (str(entry), str(exit_day))).fetchone()
    if existing:
        return existing[0]
    broad, legacy = books
    statements, ranks = s.financial_books.candidates(books, entry)
    spy = dict(db.execute('SELECT day,price FROM sessions WHERE day IN (?,?)',
                          (str(entry), str(exit_day))).fetchall())
    treasury = db.execute('SELECT yield_value FROM treasuries WHERE day<=? ORDER BY day DESC LIMIT 1',
                          (str(entry),)).fetchone()
    treasury = treasury[0] if treasury else 0.
    cursor = db.execute('INSERT INTO periods(entry,exit,spy,treasury,legacy_candidates,cached_candidates) VALUES(?,?,?,?,?,?)',
                        (str(entry), str(exit_day), spy[str(exit_day)]/spy[str(entry)]-1,
                         treasury, len(ranks), len(statements['cached'])))
    period_id = cursor.lastrowid
    for pool in ('cached', 'legacy'):
        for symbol, statement in statements[pool].items():
            if symbol not in cached or (pool == 'legacy' and symbol not in ranks):
                continue
            def lookup(day, column, forward, slack):
                return s.price(db, symbol, day, column, forward=forward, slack=slack)
            row = s.financial_books.snapshot(statement, entry, exit_day, lookup,
                                            (entry.year, symbol) in s.r.revalue.BANKRUPT)
            if row is None:
                continue
            fiscal, entry_date, end_date, cap, ev, ebitda, yield_value, multiple, ret, status = row
            if not s.financial_books.eligible(pool, cap, ev):
                continue
            observation = dict(symbol=symbol, fiscal=fiscal, enterprise_value=ev,
                               ev_ebitda=multiple, ebitda_yield=yield_value)
            db.execute('INSERT INTO snapshots VALUES('+','.join('?'*15)+')',
                       (pool, period_id, symbol, ranks.get(symbol), fiscal, entry_date,
                        end_date, cap, ev, ebitda, yield_value, multiple, yield_value-treasury, ret, status))
            history = [dict(row, fiscal=str(row['fiscal']), known=str(row['known'])) for row in broad[symbol]]
            for metric, (multiple, yield_value) in s.metrics.evaluate(observation, history).items():
                db.execute('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',
                           ('historical', pool, period_id, symbol, metric, multiple, yield_value))
        db.execute('INSERT INTO period_pools VALUES(?,?)', (period_id, pool))
    return period_id


def worker(args):
    admission.require_execution()
    started = time.perf_counter()
    cpu_started = time.process_time()
    db = sqlite3.connect(args.database, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA cache_size=-'+str(524288 if args.mode == 'sqlite_512mb' else 131072))
    if args.mode == 'sqlite_mmap':
        db.execute('PRAGMA mmap_size=1073741824')
    before = db.execute('SELECT COUNT(*) FROM periods').fetchone()[0]
    if before:
        raise ValueError('Benchmark worker requires zero existing dated books.')
    original = s.backtest_dates
    phase = 'fresh'
    signatures = {'fresh': [], 'cached': []}
    checkpoints = {}
    original_histories = s.histories
    arrays = None
    init_start = time.perf_counter()
    with ExitStack() as stack:
        if args.mode not in ('production', 'selected_pool', 'arrays_selected_pool'):
            stack.enter_context(patch.object(s, 'prepare_period', prepare_reference_period))
        if args.mode.startswith('arrays'):
            arrays = ArrayPrices(db)
            stack.enter_context(patch.object(s, 'price', arrays.price))
        if args.mode in ('arrays_shared_reports', 'arrays_selected_pool'):
            books = original_histories(db)
            stack.enter_context(patch.object(s, 'histories', lambda unused: books))
        init_seconds = time.perf_counter()-init_start
        print(json.dumps(dict(event='initialized', mode=args.mode,
                              seconds=round(init_seconds, 3))), flush=True)

        def observed(*positional, **keywords):
            result = original(*positional, **keywords)
            signatures[phase].append(digest(portable_result(result)))
            return result

        stack.enter_context(patch.object(s, 'backtest_dates', observed))
        config = robustness.plan(db, start=args.start, end=args.end,
                                 months=args.months, trials=args.trials,
                                 seed=args.seed, pool=args.pool, metric=args.metric)

        def progress(event):
            completed = event['completed']
            if completed == event['trial'] and completed in (1, 8, 24, 50, 100, args.trials):
                elapsed = time.perf_counter()-started
                checkpoints[str(completed)] = elapsed
                print(json.dumps(dict(event='checkpoint', mode=args.mode,
                                      completed=completed, seconds=round(elapsed, 3))), flush=True)

        def run(callback=None):
            if args.mode=='production':
                return robustness.run(db,config,callback,workers=args.workers)
            # Reference/prototype modes preserve their original serial loop so
            # their patched price/prepare functions run in this process.
            began=time.perf_counter();rows=[]
            for number,dates in enumerate(config['samples'],1):
                trial=s.backtest_dates(db,dates=dates,start=config['start'],end=config['end'],months=config['months'],**config['options'])
                rows.append(robustness.summarize(trial,number,dates))
                if callback:callback(dict(type='progress',completed=number,total=config['requested'],trial=number))
            return robustness.summarize_trials(config,rows,began)
        calculation_start = time.perf_counter()
        result = run(progress)
        calculation_seconds = time.perf_counter()-calculation_start
        fresh_seconds = time.perf_counter()-started
        fresh_cpu_seconds = time.process_time()-cpu_started
        phase = 'cached'
        cached_start = time.perf_counter()
        repeated = run()
        cached_seconds = time.perf_counter()-cached_start
        if signatures['fresh'] != signatures['cached']:
            raise AssertionError('Fully cached replay changed complete holding results.')
        columns = ('cagr', 'spy_cagr', 'growth', 'spy_growth', 'dates', 'empty_periods', 'short_periods')
        outcomes = [{k: row[k] for k in columns} for row in result['trials']]
        replay_outcomes = [{k: row[k] for k in columns} for row in repeated['trials']]
        if outcomes != replay_outcomes:
            raise AssertionError('Fully cached replay changed trial summaries.')
        report = dict(mode=args.mode, workers=args.workers, execution=result.get('execution'), configuration=config,
                      initialization_seconds=init_seconds,
                      calculation_seconds=calculation_seconds,
                      fresh_total_seconds=fresh_seconds,
                      fresh_cpu_seconds=fresh_cpu_seconds,
                      cached_replay_seconds=cached_seconds,
                      checkpoints_including_initialization=checkpoints,
                      initial_books=before,
                      persisted_books=db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],
                      prepared_pools=db.execute('SELECT COUNT(*) FROM period_pools').fetchone()[0],
                      snapshots=db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0],
                      complete=result['valid'], incomplete=result['incomplete'],
                      holding_result_digests=signatures['fresh'],
                      outcomes=outcomes, distributions=result['distributions'],
                      array_rows=arrays.rows if arrays else None,
                      array_bytes=arrays.bytes if arrays else None,
                      array_price_calls=arrays.calls if arrays else None,
                      effective_sqlite_cache_kib=-db.execute('PRAGMA cache_size').fetchone()[0],
                      effective_mmap_bytes=db.execute('PRAGMA mmap_size').fetchone()[0],
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None,
                      database_bytes=Path(args.database).stat().st_size)
    db.close()
    Path(args.worker_output).write_text(json.dumps(report, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--mode', choices=MODES, default='sqlite_128mb')
    parser.add_argument('--modes', nargs='+', choices=MODES,
                        default=['sqlite_128mb', 'production'])
    parser.add_argument('--database', type=Path, default=s.DATABASE)
    parser.add_argument('--worker-output')
    parser.add_argument('--workers',type=int,choices=range(1,9),default=1)
    parser.add_argument('--worker-counts',type=int,nargs='+',choices=range(1,9),help='Sequential production comparisons; never time competing runs.')
    parser.add_argument('--workdir', type=Path,
                        help='Override temporary database location for a filesystem control run.')
    parser.add_argument('--output', type=Path, default=ROOT/'results/experiments/backtest-benchmark.json')
    parser.add_argument('--reference-report', type=Path,
                        help='Also require exact parity with the first run in a saved benchmark report.')
    parser.add_argument('--start', default='1996-01-01')
    parser.add_argument('--end', default='2026-10-20')
    parser.add_argument('--months', type=int, default=12)
    parser.add_argument('--trials', type=int, default=100)
    parser.add_argument('--seed', type=int, default=20261022)
    parser.add_argument('--pool', default='legacy')
    parser.add_argument('--metric', default='ev_ebitda')
    args = parser.parse_args()
    admission.require_execution()
    if args.worker:
        worker(args)
        return
    source_stat = args.database.stat()
    report = dict(environment=dict(python=sys.version, platform=platform.platform(),
                                  logical_cpus=os.cpu_count(), source_bytes=source_stat.st_size),
                  methodology=dict(fresh_books=True, shared_sampled_dates=True,
                                   per_trial_commit=True, full_holdings_parity=True,
                                   price_history_loading_included=True,
                                   filesystem=str(args.workdir or args.database.parent),
                                   excluded='Common benchmark-only database cloning/reset; OS page cache is not flushed',
                                   production_changes=False, parent_cpu_only=True),
                  source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (ROOT/name for name in ('scripts/schedules.py','scripts/book_batch.py','scripts/robustness.py','backtest/calendar.py','backtest/portfolio_results.py'))},runs=[])
    if args.reference_report:
        report['reference_report']=str(args.reference_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='backtest-benchmark-') as scratch:
        template = Path(scratch)/'template.sqlite'
        source = sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True)
        destination = sqlite3.connect(template)
        clone_start = time.perf_counter()
        source.backup(destination)
        source.close()
        destination.execute(s.POOL_SCHEMA)
        for table in ('period_pools', 'screening_metrics', 'snapshots', 'latest_snapshots', 'periods'):
            destination.execute('DELETE FROM '+table)
        destination.commit(); destination.close()
        s.upgrade_daily_cache(template,s.fingerprint())
        report['benchmark_setup_seconds'] = time.perf_counter()-clone_start
        print(json.dumps(dict(event='template_ready', seconds=round(report['benchmark_setup_seconds'], 3))), flush=True)
        def comparable(result):
            return (result['configuration'], result['holding_result_digests'],
                    result['outcomes'], result['distributions'], result['persisted_books'])
        reference = comparable(json.loads(args.reference_report.read_text())['runs'][0]) if args.reference_report else None
        for mode,count in ((mode,count) for mode in args.modes for count in ((args.worker_counts or [args.workers]) if mode=='production' else [1])):
            with tempfile.NamedTemporaryFile(prefix='benchmark-', suffix='.sqlite',
                                             dir=args.workdir or args.database.parent, delete=False) as handle:
                temporary = Path(handle.name)
            try:
                shutil.copyfile(template, temporary)
                worker_output = Path(scratch)/(mode+'-'+str(count)+'.json')
                command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                           '--mode', mode, '--database', str(temporary),
                           '--worker-output', str(worker_output), '--start', args.start,
                           '--end', args.end, '--months', str(args.months),
                           '--trials', str(args.trials), '--seed', str(args.seed),
                           '--pool', args.pool, '--metric', args.metric,'--workers',str(count)]
                process_start = time.perf_counter()
                subprocess.run(command, check=True)
                result = json.loads(worker_output.read_text())
                result['worker_process_seconds'] = time.perf_counter()-process_start
                compared = comparable(result)
                if reference is None:
                    reference = compared
                if compared != reference:
                    raise AssertionError('Engine parity failed for '+mode)
                result['matches_reference_exactly'] = True
                report['runs'].append(result)
                args.output.write_text(json.dumps(report, indent=2)+'\n')
                print(json.dumps(dict(event='mode_complete', mode=mode, workers=count,
                                      fresh_seconds=round(result['fresh_total_seconds'], 3),
                                      cached_seconds=round(result['cached_replay_seconds'], 3),
                                      parity=True)), flush=True)
            finally:
                temporary.unlink(missing_ok=True)
                for suffix in ('-journal', '-wal', '-shm'):
                    Path(str(temporary)+suffix).unlink(missing_ok=True)
    after = args.database.stat()
    if (source_stat.st_size, source_stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError('Production cache changed during the benchmark; investigate before interpreting results.')
    report['source_cache_unchanged'] = True
    args.output.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()

"""Native candidate-engine comparison with shared selection and trial evidence.

Each method runs in a fresh process with loaded immutable inputs. The parent
owns source/cache coordination, production controls and failure containment.
The original request adapter owns financial aggregation and durable NDJSON
delivery. No saved input or production book is changed.

Execution is closed until bound input ownership and resource/availability
admission are qualified. Source-only imports and numerical helpers remain
available for synthetic tests. The retained runner is not an isolation proof.
"""
import argparse
from collections import deque
from contextlib import closing
from datetime import date
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import bench_baseline as baseline
import bench_methods as previous
import bench_admission as admission

METHODS = ('numba', 'python', 'duckdb', 'persistent', 'polars', 'rust')
STAGING = ('all', 'requested')
CANDIDATE_ASSEMBLY = ('source', 'compiled')
PROTOCOL = 1


def require_exact(comparison, label):
    if comparison.get('exact') is not True:
        raise ValueError(label + ' did not agree exactly.')


def validate_measurement(measured, budget, label, *, require_samples=False):
    """Reject measured violations before any following experiment work."""
    elapsed = measured.get('wall_seconds')
    if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or not 0 <= elapsed <= budget:
        raise ValueError(label + ' exceeded its declared time budget or has invalid timing evidence.')
    resources = measured.get('resources', {})
    if resources.get('error'):
        raise ValueError(label + ' resource sampling failed.')
    if require_samples and (resources.get('supported') is not True or not resources.get('samples')):
        raise ValueError(label + ' has incomplete resource evidence.')
    if resources.get('supported'):
        if not isinstance(resources.get('samples'), int) or resources['samples'] <= 0:
            raise ValueError(label + ' has incomplete resource evidence.')
        peaks = resources.get('sampled_tree_peaks') or {}
        for field in ('private_bytes', 'working_set'):
            value = peaks.get(field)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 2 * 1024**3:
                raise ValueError(label + ' exceeded its sampled memory bound or has invalid resource evidence.')


def validate_method(report, requests, args):
    """Only a closed, complete, agreed method can reach another control."""
    if (report.get('status') != 'complete' or report.get('financial_agreement') is not True
            or report.get('process_exit_code') != 0 or report.get('owned_descendants_closed') is not True
            or report.get('resources_closed') is not True or report.get('source_unchanged') is not True
            or report.get('process_failure')):
        raise ValueError('Candidate method failed, is incomplete, or did not close.')
    proof = report.get('intermediate_proof', {})
    if proof.get('status') == 'failed':
        raise ValueError('Intermediate proof failed.')
    require_exact(proof.get('comparison', {}), 'Intermediate proof')
    validate_measurement(report.get('setup', {}), args.setup_budget, 'Setup', require_samples=True)
    cases = report.get('cases', [])
    if [case.get('id') for case in cases] != [case['id'] for case in requests]:
        raise ValueError('Candidate method did not complete every frozen request.')
    for case, requested in zip(cases, requests, strict=True):
        if case.get('status') != 'matched' or case.get('kind') != requested['kind']:
            raise ValueError('Candidate request failed or is incomplete.')
        for field in ('comparison', 'summary_comparison', 'replay_comparison'):
            require_exact(case.get(field, {}), 'Request ' + field)
        if case['kind'] == 'primary':
            validate_measurement(case.get('measurement', {}), args.request_budget,
                                 'Primary request', require_samples=True)


def validate_assembly(assembly, methods, staging):
    if assembly not in CANDIDATE_ASSEMBLY:
        raise ValueError('Choose source or compiled candidate assembly.')
    if assembly == 'compiled' and (set(methods) != {'numba'} or staging != 'all'):
        raise ValueError('Compiled candidate assembly requires Numba and complete SQL staging.')


def emit(event, **values):
    print(json.dumps(dict(event=event, **values), allow_nan=False), flush=True)


def memory_workspace(source, schedules):
    """Create only the common screener workspace; no daily prices are copied."""
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    try:
        db.executescript(schedules.SCHEMA)
        db.executemany('INSERT INTO companies VALUES(?,?,?,?)',
                       source.execute('SELECT * FROM companies'))
        db.executemany('INSERT INTO sessions VALUES(?,?)',
                       source.execute('SELECT day,price FROM sessions ORDER BY day'))
        db.commit()
        return db
    except BaseException:
        db.close()
        raise


def stage_book(db, book, pool, *, ranking_metric=None, staged_rows=None):
    """Stage one complete snapshot book and only the ranking pair consumed by
    this request; preserve missing pairs and requested threshold values.

    A None ranking_metric retains complete staging for the comparison control.
    Count actual inserted rows, including zero rows for a missing ranking pair.
    """
    for table in baseline.DERIVED:
        db.execute('DELETE FROM ' + table)
    db.execute('INSERT INTO periods VALUES(?,?,?,?,?,?,?)', (1, *book['period']))
    snapshots = db.executemany('INSERT INTO snapshots VALUES(' + ','.join('?' * 15) + ')',
                               ((pool, 1, *row) for row in book['snapshots']))
    metrics = db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',
        (('historical', pool, 1, symbol, metric, multiple, score)
         for symbol, metric, multiple, score in book['metrics']
         if ranking_metric is None or metric == ranking_metric))
    filters = db.executemany('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',
                             (('historical', pool, 1, *row) for row in book['filters']))
    if staged_rows is not None:
        for name, cursor in (('snapshots', snapshots), ('screening_metrics', metrics),
                             ('filter_values', filters)):
            staged_rows[name] += cursor.rowcount
    return 1


class BatchModel(previous.Model):
    """Adapt bounded multi-date candidates to unchanged SQL and portfolio code.

    Candidate batches follow requested trial order. Repeated books are computed
    again within this pilot; no entry factors or completed portfolios are reused.
    Only the pending bounded batch and one SQL candidate book stay resident.
    """
    def __init__(self, inputs, executor, expected, source, *, batch_books=16,
                 row_limit=65536, staging='all', candidate_assembly='source'):
        if staging not in STAGING:
            raise ValueError('Choose all or requested SQL staging.')
        validate_assembly(candidate_assembly, [executor.stats['backend']], staging)
        if executor.candidate_assembly != candidate_assembly:
            raise ValueError('Candidate assembly differs from attached executor.')
        self.candidate_assembly = candidate_assembly
        self.staging = staging
        self.staged_rows = dict.fromkeys(('snapshots', 'screening_metrics', 'filter_values'), 0)
        self.s = inputs.s
        self.books = inputs.books
        self.cached = {symbol for symbol, present in zip(inputs.symbols, inputs.cached_mask)
                       if present}
        self.db = memory_workspace(source, self.s)
        self.executor = executor
        self.expected = expected
        self.original_average = self.s.metrics.annual_average
        self.average_cache = {}
        self.stages = {}
        self.last_request = None
        self.pending = deque()
        self.jobs = None
        self.started = False
        self.batch_books = min(batch_books, max(1, row_limit // max(1, len(inputs.symbols))))

    def prepare(self, db, entry, exit_day, books, cached, pool='legacy'):
        self.check_deadline()
        if not self.started:
            began = time.perf_counter()
            self.executor.begin(self.expected)
            self.executor.deadline = self.deadline
            plan = getattr(self.executor, 'request_plan', None)
            if plan is not None:
                jobs = plan.books
            else:
                sessions = [date.fromisoformat(row[0]) for row in
                            db.execute('SELECT day FROM sessions ORDER BY day')]
                jobs = []
                for dates in self.expected['samples']:
                    _, _, periods = self.s.dated_periods(
                        dates, self.expected['start'], self.expected['end'],
                        self.expected['months'], sessions)
                    jobs.extend((str(a), str(b), pool) for a, b in periods)
            self.jobs = iter(jobs)
            self.started = True
            self.add_time('batch_planning_seconds', began)
        key = str(entry), str(exit_day), pool
        if not self.pending:
            batch = []
            for _ in range(self.batch_books):
                item = next(self.jobs, None)
                if item is None:
                    break
                batch.append(item)
            if not batch or batch[0] != key:
                raise ValueError('Candidate batches changed requested book order.')
            began = time.perf_counter()
            results = self.executor.evaluate(batch, self.options)
            self.add_time('candidate_batch_seconds', began)
            self.check_deadline()
            if len(results) != len(batch):
                raise ValueError('Candidate executor changed the number of requested books.')
            for requested, result in zip(batch, results, strict=True):
                identity = result['entry'], result['exit'], result['pool']
                if identity != requested:
                    raise ValueError('Candidate executor changed a requested book identity.')
                self.pending.append((requested, result))
        requested, book = self.pending.popleft()
        if requested != key:
            raise ValueError('Candidate executor changed first-use order.')
        began = time.perf_counter()
        ranking_metric = (self.options.get('metric', self.s.metrics.DEFAULT_METRIC)
                          if self.staging == 'requested' else None)
        result = stage_book(db, book, pool, ranking_metric=ranking_metric,
                            staged_rows=self.staged_rows)
        self.add_time('staging_seconds', began)
        return result


def run_candidate(inputs, executor, expected, source, store, *, freshness,
                  budget_seconds, binding=None, progress=None, staging='all', candidate_assembly='source'):
    """Measure a fresh request through the original financial request adapter."""
    admission.require_execution()
    model = BatchModel(inputs, executor, expected, source, staging=staging, candidate_assembly=candidate_assembly)
    try:
        measured, evidence = previous.run_request(
            model, None, expected, store, freshness=freshness,
            progress=progress, budget_seconds=budget_seconds,
            binding=dict(binding or {}, staging=staging, candidate_assembly=candidate_assembly))
        measured['executor'] = dict(executor.stats)
        measured.update(staging=staging, candidate_assembly=candidate_assembly, staged_rows=dict(model.staged_rows))
        return measured, evidence
    finally:
        if model.last_request is not None:
            model.last_request.update(staging=staging, candidate_assembly=candidate_assembly, staged_rows=dict(model.staged_rows))
        executor.last_request = model.last_request
        model.close()


def normalized_book(book, needed):
    """Ignore storage iteration order; keep every candidate identity and value."""
    return dict(entry=book['entry'], exit=book['exit'], pool=book['pool'],
                period=list(book['period']),
                snapshots=[list(row) for row in sorted(book['snapshots'], key=lambda row: row[0])],
                metrics=[list(row) for row in sorted(book['metrics'], key=lambda row: row[:2])],
                filters=[list(row) for row in sorted(book['filters'], key=lambda row: row[:2])
                         if row[1] in needed])


def reference_smokes(source, requests, directory):
    """Untimed independent real-data checks use the original read-only engine."""
    s = baseline.s
    books, cached = s.histories(source), s.cached_symbols(source)
    records = []
    for item in requests:
        expected = item['configuration']
        db = memory_workspace(source, s)
        evidence, rows = [], []
        began = time.perf_counter()
        try:
            for number, dates in enumerate(expected['samples'], 1):
                sessions = [date.fromisoformat(day) for day in
                            (row[0] for row in db.execute('SELECT day FROM sessions ORDER BY day'))]
                _, _, periods = s.dated_periods(
                    dates, expected['start'], expected['end'], expected['months'], sessions)
                with db:
                    for a, b in periods:
                        source.execute('BEGIN')
                        try:
                            book = s.compute_period(source, a, b, books, cached, expected['options']['pool'])
                        finally:
                            source.rollback()
                        s.store_period(db, book)
                result = s.backtest_dates(db, dates=dates, start=expected['start'],
                    end=expected['end'], months=expected['months'], **expected['options'])
                evidence.append(previous.clean(result))
                rows.append(baseline.robust.summarize(result, number, dates))
                with db:
                    for table in baseline.DERIVED:
                        db.execute('DELETE FROM '+table)
            summary = previous.clean(baseline.robust.summarize_trials(expected, rows, began))
        finally:
            db.close()
        path = directory / (item['id'] + '-reference.json')
        baseline.publish(path, evidence)
        records.append(dict(item, evidence_file=str(path), evidence_sha256=baseline.file_hash(path),
                            summary=summary, kind='untimed_correctness'))
        emit('reference_smoke_complete', case=item['id'])
    return records


def source_files():
    files = [Path(__file__), Path(previous.__file__), Path(baseline.__file__)]
    files += [ROOT / 'tools' / name for name in
              ('bench_methods_arrays.py', 'bench_generation.py', 'bench_policy_program.py')]
    files.extend(sorted((ROOT / 'tools').glob('bench_candidates*.py')))
    files.extend(sorted((ROOT / 'tools').glob('bench_candidates*.rs')))
    return list(dict.fromkeys(files))


def hashes(files):
    return {path.name: baseline.file_hash(path) for path in files}


def intermediate_proof(inputs, executor, source):
    """Compare full real candidate books and report identities before timing."""
    import numpy as np
    s = inputs.s
    sessions = sorted(inputs.sessions)
    anchors = (('1997-01-02','1997-12-31'),('2016-02-29','2016-03-07'),
               ('2025-06-02','2025-12-31'))
    dates = [(next(day for day in sessions if day>=a),
              next(day for day in reversed(sessions) if day<=b)) for a,b in anchors]
    jobs = [(a,b,pool) for pool in ('legacy','cached') for a,b in dates]
    fields = set(s.metrics.FILTERS)
    options = dict(baseline.options('legacy','F0'),
        filters=[dict(field=field,op='gt',value=0.) for field in s.metrics.FILTERS])
    executor.begin(dict(options=options))
    capture = executor.limits.get('capture',False)
    executor.limits['capture'] = True
    try:
        actual = executor.evaluate(jobs,options)
        trace = executor.trace
        report_ids = {id(row):index for index,row in enumerate(inputs.report_rows)}
        for number,(entry,exit_day,pool) in enumerate(jobs):
            statements,ranks = s.financial_books.candidates(inputs.books,date.fromisoformat(entry))
            for label,key in (('cached','broad_reports'),('legacy','legacy_reports')):
                expected_ids = np.full(len(inputs.symbols),-1,dtype=np.int32)
                for symbol,row in statements[label].items():
                    expected_ids[inputs.symbol_ids[symbol]] = report_ids[id(row)]
                np.testing.assert_array_equal(trace[key][number],expected_ids)
            expected_ranks = np.zeros(len(inputs.symbols),dtype=np.int32)
            for symbol,rank in ranks.items():
                expected_ranks[inputs.symbol_ids[symbol]] = rank
            np.testing.assert_array_equal(trace['ranks'][number],expected_ranks)
        reference = []
        for entry,exit_day,pool in jobs:
            source.execute('BEGIN')
            try:
                reference.append(s.compute_period(source,date.fromisoformat(entry),
                    date.fromisoformat(exit_day),inputs.books,inputs.cached,pool))
            finally:
                source.rollback()
        expected = [normalized_book(book,fields) for book in reference]
        observed = [normalized_book(book,fields) for book in actual]
        comparison = baseline.compare(expected,observed)
        return dict(comparison=comparison,books=len(jobs),
            source_candidates=sum(len(book['snapshots']) for book in reference),
            source_metrics=sum(len(book['metrics']) for book in reference),
            source_filters=sum(len(book['filters']) for book in reference),
            source_sha256=baseline.digest(expected),candidate_sha256=baseline.digest(observed),
            report_and_rank_identity='exact',scope='Complete candidate values for six real books; all filter fields requested.')
    finally:
        executor.limits['capture'] = capture
        executor.trace = {}


def worker(args):
    """No financial import or child is started before the parent assigns ownership."""
    admission.require_execution()
    emit('worker_ready', method=args.worker)
    if sys.stdin.readline().strip() != 'GO':
        raise ValueError('Candidate worker did not receive its ownership handshake.')
    os.environ['BACKTEST_BASELINE_RUNTIME'] = str(args.runtime)
    baseline.bootstrap(args.runtime)
    import bench_candidates as core
    request = baseline.load(args.specification)
    if request['staging'] != args.staging or args.staging not in STAGING:
        raise ValueError('SQL staging variant differs from the frozen specification.')
    if request['candidate_assembly'] != args.candidate_assembly:
        raise ValueError('Candidate assembly differs from the frozen specification.')
    validate_assembly(args.candidate_assembly, [args.worker], args.staging)
    files = source_files()
    if hashes(files) != request['source_hashes']:
        raise ValueError('Candidate source changed before attachment.')
    source = sqlite3.connect((args.runtime / 'data/schedules.sqlite').resolve().as_uri()+'?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    inputs = executor = generation = None
    report = dict(method=args.worker, staging=args.staging, candidate_assembly=args.candidate_assembly,
                  cases=[], status='setup', setup=None, financial_agreement=False)
    resources = baseline.Resources()
    began = time.perf_counter()
    try:
        resources.start()
        inputs = core.NumericInputs(source, baseline.s)
        limits = dict(threads=4, workers=4, workdir=str(args.workdir / args.worker),
                      capture=False, batch_books=16, max_candidate_rows=65536,
                      request_plan=request.get('prepared_validation', False),
                      candidate_assembly=args.candidate_assembly)
        Path(limits['workdir']).mkdir(parents=True, exist_ok=True)
        if args.worker == 'python':
            executor = core.PythonExecutor(inputs, policy=inputs.policy, limits=limits)
        else:
            backend = importlib.import_module('bench_candidates_'+args.worker)
            executor = backend.attach(inputs, policy=inputs.policy, limits=limits)
        if request.get('prepared_validation'):
            from bench_generation import PreparedGeneration
            generation = PreparedGeneration(inputs, baseline.s, sources=files)
            report['prepared_generation'] = dict(generation.stats)
        report['setup'] = dict(wall_seconds=time.perf_counter()-began,
                              resources=resources.finish(), inputs=dict(inputs.stats),
                              executor=dict(executor.stats), policy_signature=inputs.policy.signature)
        baseline.publish(args.result, report)
        emit('setup_complete', method=args.worker, seconds=report['setup']['wall_seconds'])
        validate_measurement(report['setup'], request['setup_budget'], 'Setup', require_samples=os.name=='nt')
        emit('proof_start', method=args.worker)
        try:
            report['intermediate_proof'] = intermediate_proof(inputs,executor,source)
            require_exact(report['intermediate_proof'].get('comparison', {}), 'Intermediate proof')
            report['intermediate_proof']['status'] = 'matched'
        except Exception as error:
            report.setdefault('intermediate_proof', {}).update(
                status='failed',error_type=type(error).__name__,error=str(error))
        baseline.publish(args.result,report)
        emit('proof_complete',method=args.worker,status=report['intermediate_proof'].get('status','matched'))
        require_exact(report['intermediate_proof'].get('comparison', {}), 'Intermediate proof')
        for case in request['requests']:
            emit('request_start', method=args.worker, case=case['id'], kind=case['kind'])
            store = args.workdir / (args.worker+'-'+case['id']+'.sqlite')
            result = dict(id=case['id'], kind=case['kind'], staging=args.staging, candidate_assembly=args.candidate_assembly, status='running')
            report['cases'].append(result)
            baseline.publish(args.result, report)
            try:
                def freshness():
                    if generation is not None:
                        generation.validate()
                        return
                    # Untimed smoke checks use the immutable inputs owned by the
                    # parent. They never supply a headline performance number.
                    if case['kind'] == 'primary':
                        checked = baseline.s.connect(); checked.close()
                def progress(event):
                    if event['completed'] in (1, 8, 16, 24):
                        emit('trial', method=args.worker, case=case['id'], completed=event['completed'])
                measured, picks = run_candidate(inputs, executor, case['configuration'],
                    source, store, freshness=freshness, staging=args.staging, candidate_assembly=args.candidate_assembly,
                    budget_seconds=request['request_budget'] if case['kind']=='primary' else request['smoke_budget'],
                    binding=dict(input_identity=request['input_identity_sha256'],
                                 policy=inputs.policy.signature, source_hashes=request['source_hashes'],
                                 method=args.worker), progress=progress)
                evidence = args.workdir / (args.worker+'-'+case['id']+'-evidence.json')
                baseline.publish(evidence, picks)
                result.update(evidence_file=evidence.name, evidence_sha256=baseline.file_hash(evidence),
                    result_store_file=store.name, result_store_sha256=baseline.file_hash(store))
                if case['kind']=='primary':
                    result['measurement'] = measured
                else:
                    result['correctness'] = dict(committed_trials=measured['committed_trials'],
                                                executor=measured['executor'], staging=measured['staging'],
                                                candidate_assembly=measured['candidate_assembly'],
                                                staged_rows=measured['staged_rows'])
                reference = baseline.load(Path(case['evidence_file']))
                result['comparison'] = baseline.compare(reference, picks)
                result['summary_comparison'] = baseline.compare(case['summary'], measured['summary'])
                result['replay_comparison'] = baseline.compare(picks, previous.replay(store))
                for field in ('comparison', 'summary_comparison', 'replay_comparison'):
                    require_exact(result[field], 'Request ' + field)
                validate_measurement(measured, request['request_budget'] if case['kind']=='primary'
                                     else request['smoke_budget'], 'Request',
                                     require_samples=case['kind']=='primary' and os.name=='nt')
                if hashes(files) != request['source_hashes']:
                    raise ValueError('Candidate source changed during request.')
                result['status'] = 'matched'
                emit('request_complete', method=args.worker, case=case['id'], status='matched',
                     **({'seconds':measured['wall_seconds']} if case['kind']=='primary' else {}))
            except Exception as error:
                result.update(status='failed', error_type=type(error).__name__, error=str(error),
                              diagnostics=getattr(executor, 'last_request', None))
                if store.exists():
                    try:
                        partial = previous.replay(store)
                        result.update(committed_trials=len(partial),
                            partial_comparison=baseline.compare(
                                baseline.load(Path(case['evidence_file']))[:len(partial)], partial),
                            result_store_file=store.name, result_store_sha256=baseline.file_hash(store))
                    except Exception as partial_error:
                        result['partial_error'] = type(partial_error).__name__
                emit('request_failed', method=args.worker, case=case['id'], error_type=type(error).__name__)
                baseline.publish(args.result, report)
                raise
            baseline.publish(args.result, report)
        if hashes(files) != request['source_hashes']:
            raise ValueError('Candidate source changed during comparison.')
        report['financial_agreement'] = True
        report['status'] = 'complete'
        baseline.publish(args.result, report)
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error))
        if report['setup'] is None:
            report['setup'] = dict(wall_seconds=time.perf_counter()-began, resources=resources.finish())
        baseline.publish(args.result, report)
        emit('method_failed', method=args.worker, error_type=type(error).__name__)
    finally:
        failures = []
        closers = [resources.finish] if not resources.stop.is_set() else []
        closers += [item.close for item in (executor, inputs, source)
                    if item is not None and hasattr(item, 'close')]
        for close in closers:
            try:
                close()
            except Exception as error:
                failures.append(dict(error_type=type(error).__name__, error=str(error)))
        report['resources_closed'] = not failures
        if failures:
            report.update(status='failed', financial_agreement=False, closure_errors=failures)
        try:
            report['source_unchanged'] = hashes(files) == request['source_hashes']
        except Exception as error:
            report['source_unchanged'] = False
            report['identity_error'] = dict(error_type=type(error).__name__, error=str(error))
        if not report['source_unchanged']:
            report.update(status='failed', financial_agreement=False,
                          error='Candidate source changed during comparison.')
        baseline.publish(args.result, report)
    emit('worker_complete', method=args.worker, status=report['status'])


def smoke_requests(source, *, start='2015-01-01', end='2025-12-31', extended=False):
    """Explicit correctness fixtures; these never replace frozen primary cases."""
    result = []
    for pool in ('legacy','cached'):
        for profile in ('F1','F2','mixed'):
            options = baseline.options(pool,profile if profile!='mixed' else 'F0')
            if profile=='mixed':
                options = dict(options,metric='ev_ebitda_3y',rank_from=2,rank_to=100,
                               filters=baseline.PROFILES['F1']+baseline.PROFILES['F2'])
            configuration = baseline.robust.plan(source,start=start,end=end,
                               months=12,trials=2,seed=42,**options)
            result.append(dict(id=f'smoke-{pool}-{profile}',configuration=configuration))
        if extended:
            for label, changes in (('rank-slice', dict(rank_from=51, rank_to=100)),
                                   ('empty', dict(min_cap=1e100))):
                options = dict(baseline.options(pool, 'F0'), **changes)
                configuration = baseline.robust.plan(source, start=start, end=end,
                    months=12, trials=2, seed=42, **options)
                result.append(dict(id=f'smoke-{pool}-{label}', configuration=configuration))
    return result


def run_isolated(args,method,specification,result):
    """Use phase deadlines and terminate the complete owned process group."""
    admission.require_execution()
    from bench_candidates_process import OwnedProcess
    command = [sys.executable,str(Path(__file__).resolve()),'--runtime',str(args.runtime),
        '--workdir',str(args.workdir),'--worker',method,'--specification',str(specification),
        '--result',str(result),'--staging',args.staging,
        '--candidate-assembly',args.candidate_assembly]
    environment = dict(os.environ)
    # The child announces readiness before acquiring source ownership. Its
    # financial imports start only after assignment to the parent-owned job.
    environment.pop('BACKTEST_BASELINE_RUNTIME',None)
    environment['NUMBA_NUM_THREADS'] = environment['POLARS_MAX_THREADS'] = '4'
    environment['OMP_NUM_THREADS'] = environment['OPENBLAS_NUM_THREADS'] = '4'
    environment['MKL_NUM_THREADS'] = environment['NUMEXPR_NUM_THREADS'] = '4'
    stage,case = 'startup',None
    deadline = time.monotonic()+60
    outcome = None
    with OwnedProcess(command,env=environment) as owned:
        while True:
            event = owned.event(timeout=.25)
            if event is None:
                break
            if event:
                print(json.dumps(event,allow_nan=False),flush=True)
                kind = event.get('event')
                if kind=='worker_ready':
                    owned.start(); stage='setup'; deadline=time.monotonic()+args.setup_budget+30
                elif kind=='setup_complete':
                    stage='proof'; deadline=time.monotonic()+180
                elif kind=='proof_complete':
                    stage='between_requests'; deadline=time.monotonic()+60
                elif kind=='request_start':
                    stage='request'; case=event['case']
                    budget=args.request_budget if event['kind']=='primary' else args.smoke_budget
                    deadline=time.monotonic()+budget+30
                elif kind in ('request_complete','request_failed'):
                    stage='between_requests'; deadline=time.monotonic()+60
                elif kind=='worker_complete':
                    stage='shutdown'; deadline=time.monotonic()+60
            if time.monotonic()>deadline:
                outcome=dict(status='hard_timeout',stage=stage,case=case,
                             error='Declared stage budget plus cleanup grace exceeded.')
                owned.terminate()
                emit('method_hard_timeout',method=method,stage=stage,case=case)
                break
        code=owned.process.wait(timeout=30)
    report=baseline.load(result) if result.exists() else dict(method=method,staging=args.staging,candidate_assembly=args.candidate_assembly,cases=[])
    report['process_exit_code']=code
    report['owned_descendants_closed']=True
    if outcome:
        report['process_failure']=outcome
        report['status']='incomplete'
        failed=next((entry for entry in report['cases'] if entry['id']==case),None)
        if failed is not None:
            failed['status']='hard_timeout'
            store=args.workdir/(method+'-'+case+'.sqlite')
            if store.exists():
                try:
                    # Recovery is confined to this owned disposable result DB.
                    # A forced stop may leave the current trial's hot journal.
                    with closing(sqlite3.connect(store)) as recovery:
                        recovery.execute('SELECT COUNT(*) FROM trials').fetchone()
                    partial=previous.replay(store)
                    spec=baseline.load(specification)
                    request=next(item for item in spec['requests'] if item['id']==case)
                    expected=baseline.load(Path(request['evidence_file']))
                    failed.update(committed_trials=len(partial),
                        partial_comparison=baseline.compare(expected[:len(partial)],partial),
                        result_store_file=store.name,result_store_sha256=baseline.file_hash(store))
                except Exception as error:
                    failed['partial_error']=dict(error_type=type(error).__name__,error=str(error))
    elif code and report.get('status')=='complete':
        report['status']='failed_shutdown'
    return report


def parent(args):
    """Serial native comparison; invalid evidence stops subsequent work."""
    admission.require_execution()
    validate_assembly(args.candidate_assembly, args.methods, args.staging)
    if os.name!='nt':
        raise ValueError('Headline comparisons require native Windows Python.')
    args.runtime,args.workdir=args.runtime.resolve(),args.workdir.resolve()
    baseline.assert_workdir(args.runtime,args.workdir)
    args.workdir.mkdir(parents=True,exist_ok=True)
    if (args.workdir/'comparison.json').exists() or (args.workdir/'template.sqlite').exists():
        raise ValueError('Use a new work directory; existing evidence is never overwritten.')
    os.environ['BACKTEST_BASELINE_RUNTIME']=str(args.runtime)
    os.environ['BACKTEST_BASELINE_TOOL_SHA256']=baseline._loaded_tool_sha256
    baseline.bootstrap(args.runtime)
    manifest=baseline.load(args.manifest)
    files=source_files(); source_hashes=hashes(files)
    report=dict(protocol=PROTOCOL,status='running',methods=args.methods,
        prepared_validation=args.prepared_validation,staging=args.staging,candidate_assembly=args.candidate_assembly,
        source_hashes=source_hashes,environment=baseline.environment(),runs=[],controls=[],
        request_budget_seconds=args.request_budget,setup_budget_seconds=args.setup_budget,
        smoke_budget_seconds=args.smoke_budget,
        limitations=['Candidate executors retain source-derived policy, complete candidate books, final SQL selection and portfolio assembly.',
                     ('An equivalent fresh metadata inventory and prepared-generation binding are included in request time.'
                      if args.prepared_validation else 'Full current freshness is included in primary request time.'),
                     'Smoke requests are untimed correctness checks under the owned immutable input generation.',
                     'Setup, compilation, cloning, proof and evidence comparison are separate from warm request time.',
                     'One primary pool/profile/seed is a pilot; no full-matrix qualification. OS cache is uncontrolled.'])
    with baseline.coordinator.access():
        ready=baseline.s.r.connect(full_prices=True);ready.close()
        source=baseline.s.connect()
        before=None
        try:
            baseline.validate_manifest(manifest,source)
            before=baseline.identity(args.runtime)
            report['input_identity_sha256']=baseline.digest(before)
            report['input_identity']={key:value for key,value in before.items() if key!='daily_generation'}
            report['workload_sha256']=manifest['sha256']
            template=args.workdir/'template.sqlite'
            with closing(sqlite3.connect(template)) as destination:
                source.backup(destination);baseline.clear_books(destination)
            smokes=reference_smokes(source,smoke_requests(source, extended=args.prepared_validation),args.workdir)
            case=next(case for case in manifest['primary_cases'] if case['id']==args.case)
            configuration=baseline.configuration(manifest,case,source)
            def control(number):
                emit('control_start',number=number)
                path=args.workdir/f'control-{number}.sqlite'
                shutil.copyfile(template,path)
                measured,evidence=baseline.request(path,manifest,case,args.workdir/'telemetry'/f'control-{number}')
                path.unlink()
                report['controls'].append(measured)
                baseline.publish(args.workdir/'comparison.json',report)
                emit('control_complete',number=number,seconds=measured['wall_seconds'])
                return measured,evidence
            first,evidence=control(0)
            reference=args.workdir/'primary-reference.json'
            baseline.publish(reference,evidence)
            requests=[dict(id=case['id'],kind='primary',configuration=configuration,
                           evidence_file=str(reference),evidence_sha256=baseline.file_hash(reference),
                           summary=first['summary'])]+smokes
            report['primary_reference']=dict(file=reference.name,sha256=baseline.file_hash(reference))
            specification=args.workdir/'specification.json'
            baseline.publish(specification,dict(source_hashes=source_hashes,requests=requests,
                prepared_validation=args.prepared_validation,staging=args.staging,candidate_assembly=args.candidate_assembly,
                input_identity_sha256=report['input_identity_sha256'],request_budget=args.request_budget,
                smoke_budget=args.smoke_budget,setup_budget=args.setup_budget))
            for number,method in enumerate(args.methods,1):
                if hashes(files)!=source_hashes:
                    raise ValueError('Experimental source changed before method execution.')
                result=args.workdir/(method+'-result.json')
                item=run_isolated(args,method,specification,result)
                baseline.publish(result,item)
                report['runs'].append(item)
                validate_method(item, requests, args)
                if hashes(files)!=source_hashes or baseline.identity(args.runtime)!=before:
                    raise ValueError('Source or production inputs changed during candidate comparison.')
                after,after_evidence=control(number)
                item['control_comparison']=baseline.compare(evidence,after_evidence)
                item['control_summary_comparison']=baseline.compare(first['summary'],after['summary'])
                require_exact(item['control_comparison'], 'Production control holdings')
                require_exact(item['control_summary_comparison'], 'Production control summary')
                primary=next((entry for entry in item['cases'] if entry['kind']=='primary'),None)
                item['bracketing_controls']=[number-1,number]
                if primary and primary['status']=='matched':
                    before_time=report['controls'][number-1]['wall_seconds']
                    after_time=after['wall_seconds']
                    item['conservative_speedup']=min(before_time,after_time)/primary['measurement']['wall_seconds']
                    item['control_drift_ratio']=max(before_time,after_time)/min(before_time,after_time)
                if baseline.identity(args.runtime)!=before:
                    raise ValueError('Production inputs changed during candidate comparison.')
                report['production_unchanged']=True
                baseline.publish(args.workdir/'comparison.json',report)
            if hashes(files)!=source_hashes:
                raise ValueError('Experimental source changed during comparison.')
            report['status']='pilot_complete'
            baseline.publish(args.workdir/'comparison.json',report)
        except Exception as error:
            report.update(status='stopped',error_type=type(error).__name__,error=str(error))
            raise
        finally:
            try:
                report['source_unchanged']=hashes(files)==source_hashes
                if before is not None:
                    report['production_unchanged']=baseline.identity(args.runtime)==before
                if not report['source_unchanged'] or report.get('production_unchanged') is False:
                    report.update(status='stopped',identity_failure=True)
            except Exception as error:
                report.update(status='stopped',identity_failure=True,
                              identity_error=dict(error_type=type(error).__name__,error=str(error)))
                raise
            finally:
                try:
                    source.close()
                    report['source_closed']=True
                except Exception as error:
                    report.update(status='stopped',source_closed=False,
                                  closure_error=dict(error_type=type(error).__name__,error=str(error)))
                    raise
                finally:
                    baseline.publish(args.workdir/'comparison.json',report)
    emit('comparison_complete',methods=len(report['runs']),report=str(args.workdir/'comparison.json'))


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--runtime', type=Path, required=True)
    result.add_argument('--workdir', type=Path, required=True)
    result.add_argument('--methods', nargs='+', choices=METHODS, default=list(METHODS))
    result.add_argument('--staging', choices=STAGING, default='all',
                        help='Stage all ranking pairs (control) or only the requested metric.')
    result.add_argument('--candidate-assembly', choices=CANDIDATE_ASSEMBLY, default='source',
                        help='Execute source guards (control) or compiled source-derived decisions (Numba; complete staging).')
    result.add_argument('--prepared-validation', action='store_true',
                        help='Benchmark exact inventory validation and planned request work; no production changes.')
    result.add_argument('--case', default='legacy-F0-42',
                        help='One frozen primary case ID; use separate serial runs for other cases.')
    result.add_argument('--manifest', type=Path, default=ROOT/'docs/plans/compiled-backtest/phases/CB-01/workloads.json')
    result.add_argument('--request-budget', type=float, default=180.)
    result.add_argument('--setup-budget', type=float, default=600.)
    result.add_argument('--smoke-budget', type=float, default=60.)
    result.add_argument('--worker', choices=METHODS)
    result.add_argument('--specification', type=Path)
    result.add_argument('--result', type=Path)
    return result


def main():
    args = parser().parse_args()
    for value in (args.request_budget, args.setup_budget, args.smoke_budget):
        if not math.isfinite(value) or value<=0:
            raise ValueError('Candidate budgets must be finite positive seconds.')
    if args.worker:
        return worker(args)
    return parent(args)


if __name__ == '__main__':
    main()

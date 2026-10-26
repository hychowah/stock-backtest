"""Internal financial worker for MeasurementExecution; no runtime discovery.

Application source, prepared databases and every writable path are explicitly
bound. Production financial functions remain authoritative. Source-only policy
attachment has no dependency on this financial protocol. Real entry is closed.
"""
from contextlib import closing
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys
import sysconfig
import time

import bench_admission as admission
from bench_execution_storage import failure_reason
from bench_comparison import ComparisonError, digest, encoded


def _verify(root, files):
    for relative, expected in files.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ComparisonError('mismatch')


def _guard(request, folder):
    """Reject accidental Python access to undeclared project assets.

    This is a dependency check, not an operating-system sandbox. Native-library
    access and full process-tree resource enforcement remain qualification work.
    """
    source, capture = Path(request['source']).resolve(), Path(request['capture']).resolve()
    tools = (folder.parent / 'tools').resolve()
    observation = Path(request['observation_root']).resolve()
    owner = folder.parent.resolve()
    libraries = {Path(sysconfig.get_path(name)).resolve() for name in ('stdlib', 'platstdlib', 'purelib', 'platlib')}
    readonly = (source, capture, tools, observation, *libraries)
    def within(path, roots):
        return any(path == root or path.is_relative_to(root) for root in roots)
    def audit(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(char in mode for char in 'wax+')) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing:
                coordination = request.get('observation_mode') == 'coordinated' and (
                    path in (observation / 'data/website-source.lock', observation / 'data/website-data-0.lock')
                    or path.parent == observation / 'data/website-data-0.lock.live')
                if not coordination and (not within(path, (owner,)) or within(path, (source, tools))):
                    raise ComparisonError('unsupported')
            elif not within(path, (*readonly, owner)):
                if os.name == 'nt' or not within(path, (Path('/proc'), Path('/sys'))):
                    raise ComparisonError('unsupported')
        elif event == 'sqlite3.connect':
            value = str(args[0])
            observations = {(observation / 'data' / name).as_uri() + '?mode=ro'
                            for name in ('research.sqlite', 'schedules.sqlite')}
            if value not in observations and value != ':memory:' and not value.startswith((capture.as_uri() + '/', owner.as_uri() + '/', str(owner) + os.sep)):
                raise ComparisonError('unsupported')
        elif event == 'socket.connect':
            address = args[1]
            if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1'):
                raise ComparisonError('unsupported')
    sys.addaudithook(audit)


def _observe(request, schedules):
    from bench_execution_observation import CurrentObservation
    return CurrentObservation(request, schedules).current()


def _bind(request):
    """Bind actual private modules and all reference spawn paths explicitly."""
    import sqlite3
    source = Path(request['source']).resolve()
    _verify(source, request['sources'])
    sys.path[:0] = [str(source / 'scripts'), str(source / 'website')]
    import schedules as s
    import robustness
    import book_batch
    import bench_baseline as baseline
    for module in (s, s.r, s.metrics, robustness, book_batch):
        if not Path(module.__file__).resolve().is_relative_to(source):
            raise ComparisonError('mismatch')
    captured = Path(request['capture'])
    database = Path(request['database'])

    def connect(path=None):
        selected = database if path is None else Path(path)
        if selected.resolve() != database.resolve():
            raise ComparisonError('unsupported')
        db = sqlite3.connect(selected.resolve().as_uri() + '?mode=rw', uri=True)
        db.row_factory = sqlite3.Row
        return db

    def research_connect(path=None, check=True, full_prices=False):
        selected = captured / 'research.sqlite' if path is None else Path(path)
        if selected.resolve() != (captured / 'research.sqlite').resolve():
            raise ComparisonError('unsupported')
        db = sqlite3.connect(selected.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
        db.row_factory = sqlite3.Row
        return db

    # Binding substitutes storage discovery, not eligibility/formulas/calendar.
    s.DATABASE, s.r.DATABASE = database, captured / 'research.sqlite'
    s.connect, s.r.connect = connect, research_connect
    s.fingerprint = lambda: json.loads(encoded(request['captured_freshness']['daily_inputs']))
    s.r.signature = lambda: _observe(request, s)
    book_batch.initialize_worker = initialize_bound_worker
    baseline.s, baseline.batch, baseline.robust = s, book_batch, robustness
    return s, robustness, baseline


def initialize_bound_worker(path, expected):
    """Spawn uses the same private source and generation as its parent request.

    Current inventory was checked inside the parent request. Descendants check
    that exact immutable generation, never discover or lock the live runtime.
    """
    import multiprocessing
    from threading import Thread
    request = json.loads((Path(path).parent / 'binding.json').read_bytes())
    s, _, _ = _bind(request)
    import book_batch
    parent = multiprocessing.parent_process()
    if parent is not None:
        def follow():
            parent.join()
            os._exit(0)
        Thread(target=follow, daemon=True).start()
    book_batch._reader = book_batch.open_reader(path, expected)
    book_batch._books = s.histories(book_batch._reader)
    book_batch._cached = s.cached_symbols(book_batch._reader)


def _proof(source, s, configuration, executor=None):
    from bench_candidates_run import normalized_book
    sessions = [date.fromisoformat(row[0]) for row in source.execute('SELECT day FROM sessions ORDER BY day')]
    _, _, periods = s.dated_periods(configuration['samples'][0], configuration['start'],
        configuration['end'], configuration['months'], sessions)
    jobs = [(str(a), str(b), pool) for pool in ('legacy', 'cached') for a, b in periods[:3]]
    if not jobs:
        raise ComparisonError('incomplete')
    fields = set(s.metrics.FILTERS)
    if executor is not None:
        options = dict(configuration['options'], filters=[dict(field=field, op='gt', value=0.) for field in fields])
        executor.begin(dict(options=options))
        books = executor.evaluate(jobs, options)
    else:
        histories, cached = s.histories(source), s.cached_symbols(source)
        books = []
        for a, b, pool in jobs:
            source.execute('BEGIN')
            try:
                books.append(s.compute_period(source, date.fromisoformat(a), date.fromisoformat(b), histories, cached, pool))
            finally:
                source.rollback()
    return [normalized_book(book, fields) for book in books]


def _reference(request, s, robust, baseline):
    """Ordinary production trial evaluator, including local delivery and saving."""
    from unittest.mock import patch
    from bench_methods import clean
    configuration = request['configuration']
    holdings = []
    summarize = robust.summarize
    def observe(result, number, dates):
        holdings.append(clean(result))
        return summarize(result, number, dates)
    delivery = baseline.Delivery()
    db = None
    began = time.perf_counter()
    try:
        _observe(request, s)
        db = s.connect()
        planned = robust.plan(db, start=configuration['start'], end=configuration['end'],
            months=configuration['months'], trials=configuration['requested'], seed=configuration['seed'],
            **configuration['options'])
        if planned != configuration:
            raise ComparisonError('mismatch')
        delivery.send(dict(type='configuration', configuration=planned))
        with patch.object(robust, 'summarize', observe):
            result = robust.run(db, planned, progress=delivery.send)
        delivery.send(dict(type='complete', result=result))
        if result['execution']['reused_books'] or len(holdings) != configuration['requested']:
            raise ComparisonError('mismatch')
        db.close(); db = None
        delivery.close()
        elapsed = time.perf_counter() - began
    finally:
        if db is not None:
            db.close()
        if delivery.writer.fileno() != -1:
            delivery.close()
    summary = {key: value for key, value in result.items() if key not in ('seconds', 'execution', 'trials')}
    summary['trials'] = [{key: value for key, value in row.items() if key != 'seconds'} for row in result['trials']]
    return elapsed, holdings, summary, dict(execution=result['execution'],
        response_bytes=delivery.bytes, received_bytes=delivery.received)


def run(request_path):
    admission.require_execution()
    if sys.stdin.readline().strip() != 'GO':
        raise ComparisonError('protocol')
    import sqlite3
    request_path = Path(request_path).resolve()
    request = json.loads(request_path.read_bytes())
    folder = request_path.parent
    _verify(folder.parent / 'tools', request['tools'])
    _guard(request, folder)
    s, robust, baseline = _bind(request)
    # Spawn children receive only this explicit binding beside the private DB.
    (Path(request['database']).parent / 'binding.json').write_bytes(encoded(request))
    from bench_policy_program import PolicyProgram
    from bench_methods import clean, replay
    from bench_candidates_run import run_candidate
    reference = None
    if request['reference'] is not None:
        reference = json.loads(Path(request['reference']['path']).read_bytes())
        if digest(reference) != request['reference']['sha256'] or reference['binding'] != request['binding']:
            raise ComparisonError('mismatch')
    source = inputs = executor = None
    def phase(name):
        print(json.dumps(dict(event='phase', name=name)), flush=True)
    try:
        source = sqlite3.connect((Path(request['capture']) / 'schedules.sqlite').as_uri() + '?mode=ro&immutable=1', uri=True)
        source.row_factory = sqlite3.Row
        policy = PolicyProgram(s)
        if request['step'].startswith('numba_'):
            from bench_candidates import NumericInputs
            from bench_candidates_numba import attach
            inputs = NumericInputs(source, s)
            executor = attach(inputs, policy=inputs.policy, limits=dict(
                threads=request['threads'], capture=False, request_plan=True,
                candidate_assembly=request['step'].removeprefix('numba_'), workdir=str(folder)))
        phase('setup')
        proof = _proof(source, s, request['configuration'], executor)
        if reference is not None and baseline.compare(reference['proof'], proof)['exact'] is not True:
            raise ComparisonError('mismatch')
        phase('proof')
        if executor is None:
            elapsed, evidence, summary, details = _reference(request, s, robust, baseline)
        else:
            measured, evidence = run_candidate(inputs, executor, request['configuration'], source,
                folder / 'trials.sqlite', freshness=lambda: _observe(request, s),
                binding=request['binding'], budget_seconds=request['request_budget'],
                candidate_assembly=request['step'].removeprefix('numba_'))
            if baseline.compare(evidence, replay(folder / 'trials.sqlite'))['exact'] is not True:
                raise ComparisonError('mismatch')
            elapsed, summary = measured['wall_seconds'], measured['summary']
            details = dict(committed_trials=measured['committed_trials'],
                response_bytes=measured['response_bytes'], received_bytes=measured['received_bytes'],
                executor=measured['executor'])
        phase('request')
        if reference is not None:
            for key, value in (('evidence', evidence), ('summary', summary)):
                if baseline.compare(reference[key], value)['exact'] is not True:
                    raise ComparisonError('mismatch')
        value = dict(binding=request['binding'], policy_signature=policy.signature, proof=proof,
            evidence=evidence, summary=summary, request_seconds=elapsed, details=details,
            financial_agreement=True, scope='disposable_fixture', speed_gate='unqualified')
        (folder / 'result.json').write_bytes(encoded(value))
        _verify(Path(request['source']), request['sources'])
        phase('collection')
    finally:
        for resource in (executor, inputs, source):
            if resource is not None:
                resource.close()
    print(json.dumps(dict(event='complete', sha256=digest(value))), flush=True)


def main():
    try:
        run(sys.argv[-1])
    except BaseException as error:
        print(json.dumps(dict(event='failed', reason=failure_reason(error),
                              error_type=type(error).__name__)), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()

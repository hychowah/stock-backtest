"""Compare benchmark-only evaluators with shared policy and durable trials.

Production inputs and source never change. Financial arithmetic, ranking and
portfolio aggregation call current production modules. Report-index experiments
must prove their complete candidate mappings against that source policy.
Execution is closed until bound input ownership and resource/availability
admission are qualified. The retained orchestration is historical. Source-only
attachment and numerical/evidence helpers remain available for synthetic tests.
"""
import argparse
from bisect import bisect_right
from calendar import monthrange
from contextlib import ExitStack, closing
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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import tools.experiments.bench_baseline as baseline
import tools.experiments.bench_admission as admission
METHODS = ('arrays', 'numba', 'duckdb', 'indexed')


def bind_financial():
    """Bind selected runtime financial owners after source acquisition."""
    global daily,research,screening,rules,financial_books,metrics
    from backtest.inputs import daily,research
    from backtest import screening
    from backtest.financial import rules,books as financial_books,metrics


def clean(value):
    """Exclude only runtime diagnostics from financial evidence."""
    if isinstance(value, dict):
        return {key:clean(item) for key,item in value.items() if key not in ('seconds','execution')}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


class Model:
    """Immutable scalar inputs plus one disposable SQL screening workspace."""
    def __init__(self, source, schedules):
        self.s = schedules
        began = time.perf_counter()
        self.books = daily.histories(source)
        self.cached = daily.cached_symbols(source)
        self.histories = {symbol:[dict(row,fiscal=str(row['fiscal']),known=str(row['known']))
                                  for row in rows] for symbol,rows in self.books[0].items()}
        self.financials = {}
        for row in source.execute('SELECT symbol,fiscal,values_json FROM financial_inputs'):
            self.financials.setdefault(row[0],{})[row[1]] = json.loads(row[2])
        self.sessions = dict(source.execute('SELECT day,price FROM sessions ORDER BY day'))
        treasuries = list(source.execute('SELECT day,yield_value FROM treasuries ORDER BY day'))
        self.treasury_days = [row[0] for row in treasuries]
        self.treasury_values = [row[1] for row in treasuries]
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript(daily.SCHEMA)
        self.db.executemany('INSERT INTO companies VALUES(?,?,?,?)',
                            source.execute('SELECT * FROM companies'))
        self.db.executemany('INSERT INTO sessions VALUES(?,?)',self.sessions.items())
        self.db.commit()
        self.base_seconds = time.perf_counter()-began
        self.original_average = metrics.annual_average
        self.average_cache = {}
        self.stages = {}

    def close(self):
        self.db.close()

    def annual_average(self, rows, fiscal, years):
        key = id(rows), fiscal, years
        if key not in self.average_cache:
            self.average_cache[key] = self.original_average(rows,fiscal,years)
        return self.average_cache[key]

    def add_time(self, key, began):
        self.stages[key] = self.stages.get(key,0.) + time.perf_counter()-began

    def candidate_reports(self, entry):
        return financial_books.candidates(self.books,entry)

    def needs_thresholds(self, needed):
        # The first-wave methods remain eager controls for later experiments.
        return True

    def prepare(self, db, entry, exit_day, books, cached, pool='legacy'):
        """Resolve two batches; call unchanged scalar policy; stage one book."""
        self.check_deadline()
        began = time.perf_counter()
        statements,ranks = self.candidate_reports(entry)
        candidates = {symbol:statement for symbol,statement in statements[pool].items()
                      if symbol in self.cached and (pool!='legacy' or symbol in ranks)}
        self.add_time('candidates_seconds',began)
        needed = {condition['field'] for condition in self.options.get('filters',[])}
        thresholds = self.needs_thresholds(needed)
        trailing = ([entry.replace(year=entry.year-years,
                     day=min(entry.day,monthrange(entry.year-years,entry.month)[1])) for years in (1,3)]
                    if thresholds else [])
        queries = []
        for symbol,statement in candidates.items():
            queries.extend([(symbol,statement['fiscal'].toordinal(),'price',False),
                            (symbol,entry.toordinal(),'price',True),
                            (symbol,exit_day.toordinal(),'adjusted',False)])
            if thresholds:
                queries.append((symbol,entry.toordinal(),'adjusted',False))
            queries.extend((symbol,day.toordinal(),'adjusted',False) for day in trailing)
        queries = list(dict.fromkeys(queries))
        began = time.perf_counter()
        answers = dict(zip(queries,self.resolver.resolve(queries),strict=True))
        self.check_deadline()
        second = []
        for symbol in candidates:
            raw = answers[symbol,entry.toordinal(),'price',True]
            if raw is not None:
                second.append((symbol,raw[0],'adjusted',True))
        second = list(dict.fromkeys(second))
        answers.update(zip(second,self.resolver.resolve(second),strict=True))
        self.check_deadline()
        self.add_time('lookup_seconds',began)
        treasury_index = bisect_right(self.treasury_days,str(entry))-1
        treasury = self.treasury_values[treasury_index] if treasury_index>=0 else 0.
        snapshots,pairs,filters = [],[],[]
        metric = self.options.get('metric',metrics.DEFAULT_METRIC)
        for symbol,statement in candidates.items():
            self.check_deadline()
            def lookup(day,column,forward=False,slack=None):
                key = symbol,day.toordinal(),column,forward
                if key not in answers:
                    raise ValueError('Financial policy requested an unplanned price lookup.')
                value = answers[key]
                if value is None or (slack is not None and abs(value[0]-day.toordinal())>slack):
                    return None
                return date.fromordinal(value[0]),value[1]
            began = time.perf_counter()
            row = financial_books.snapshot(statement,entry,exit_day,lookup,
                            (entry.year,symbol) in rules.BANKRUPT)
            self.add_time('snapshot_seconds',began)
            if row is None:
                continue
            fiscal,buy,sell,cap,ev,ebitda,yield_value,multiple,ret,status = row
            if not financial_books.eligible(pool,cap,ev):
                continue
            observation = dict(symbol=symbol,fiscal=fiscal,market_cap=cap,
                enterprise_value=ev,ev_ebitda=multiple,ebitda_yield=yield_value)
            began = time.perf_counter()
            evaluated = metrics.evaluate(observation,self.histories[symbol])
            self.add_time('metric_seconds',began)
            # Call the complete authoritative calculator. Store only fields
            # required by this request; unused missing fields never exclude.
            # The indexed method may omit the whole call when no condition
            # consumes a threshold. It never projects individual formulas.
            values = {}
            if thresholds:
                began = time.perf_counter()
                values = metrics.filter_values(observation,evaluated,entry,lookup,
                                                      self.financials.get(symbol,{}))
                self.add_time('threshold_seconds',began)
            snapshots.append((pool,1,symbol,ranks.get(symbol),fiscal,buy,sell,cap,ev,
                              ebitda,yield_value,multiple,yield_value-treasury,ret,status))
            if metric in evaluated:
                pairs.append(('historical',pool,1,symbol,metric,*evaluated[metric]))
            filters.extend(('historical',pool,1,symbol,key,value)
                           for key,value in values.items() if key in needed)
        began = time.perf_counter()
        for table in ('period_pools','filter_values','screening_metrics','snapshots','periods'):
            db.execute('DELETE FROM '+table)
        spy = self.sessions[str(exit_day)]/self.sessions[str(entry)]-1
        db.execute('INSERT INTO periods VALUES(?,?,?,?,?,?,?)',
                   (1,str(entry),str(exit_day),spy,treasury,len(ranks),len(statements['cached'])))
        db.executemany('INSERT INTO snapshots VALUES('+','.join('?'*15)+')',snapshots)
        db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',pairs)
        db.executemany('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',filters)
        self.add_time('staging_seconds',began)
        return 1

    def check_deadline(self):
        if self.deadline is not None and time.perf_counter()>self.deadline:
            raise TimeoutError('Experimental request exceeded its declared time budget.')


def run_request(model,resolver,expected,store_path,*,freshness=lambda:None,progress=None,budget_seconds=None,binding=None):
    """Warm loaded base, empty result store; include validation and durable writes.

    This benchmark adapter retains the current full freshness scan. Loading and
    JIT compilation are separately reported. SQL candidate tables contain one
    period. Callers can retain bounded candidate batches. Complete selected
    trial evidence is committed before progress.
    """
    admission.require_execution()
    if Path(store_path).exists():
        raise ValueError('A fresh request requires a new result store.')
    model.resolver = resolver
    model.options = expected['options']
    model.average_cache.clear()
    model.stages = {}
    model.last_request = None
    for table in baseline.DERIVED:
        model.db.execute('DELETE FROM '+table)
    model.db.commit()
    delivery = baseline.Delivery()
    resources = baseline.Resources()
    resources.start()
    began = time.perf_counter()
    model.deadline = began+budget_seconds if budget_seconds is not None else None
    rows,holdings = [],[]
    output = None
    original_select = screening.select
    def select(*args,**kwargs):
        started = time.perf_counter()
        try:
            return original_select(*args,**kwargs)
        finally:
            model.add_time('selection_seconds',started)
    try:
        started = time.perf_counter()
        freshness()
        model.add_time('freshness_seconds',started)
        configuration = baseline.robust.plan(model.db,start=expected['start'],end=expected['end'],
            months=expected['months'],trials=expected['requested'],seed=expected['seed'],
            **expected['options'])
        if configuration != expected:
            raise ValueError('Frozen planner configuration changed.')
        output = sqlite3.connect(store_path)
        output.execute('PRAGMA synchronous=FULL')
        output.execute('CREATE TABLE binding(value TEXT NOT NULL)')
        output.execute('INSERT INTO binding VALUES(?)',
                       (json.dumps(dict(configuration=expected,identity=binding),allow_nan=False),))
        output.execute('CREATE TABLE trials(number INTEGER PRIMARY KEY,evidence TEXT NOT NULL)')
        output.commit()
        delivery.send(dict(type='configuration',configuration=configuration))
        with ExitStack() as stack:
            stack.enter_context(patch.object(daily,'histories',lambda unused:model.books))
            stack.enter_context(patch.object(daily,'cached_symbols',lambda unused:model.cached))
            stack.enter_context(patch.object(daily,'prepared_period',lambda *unused:None))
            stack.enter_context(patch.object(model.s,'prepare_period',model.prepare))
            stack.enter_context(patch.object(metrics,'annual_average',model.annual_average))
            stack.enter_context(patch.object(screening,'select',select))
            for number,dates in enumerate(configuration['samples'],1):
                result = model.s.backtest_dates(model.db,dates=dates,start=configuration['start'],
                    end=configuration['end'],months=configuration['months'],**configuration['options'])
                evidence = clean(result)
                publication = time.perf_counter()
                with output:
                    output.execute('INSERT INTO trials VALUES(?,?)',
                                   (number,json.dumps(evidence,allow_nan=False)))
                model.add_time('publication_seconds',publication)
                holdings.append(evidence)
                rows.append(baseline.robust.summarize(result,number,dates))
                event = dict(type='progress',completed=number,total=configuration['requested'],trial=number)
                delivery.send(event)
                if progress:
                    progress(event)
        aggregate = baseline.robust.summarize_trials(configuration,rows,began)
        delivery.send(dict(type='complete',result=aggregate))
        output.close();output = None
        delivery.close()
        elapsed = time.perf_counter()-began
    finally:
        if output is not None:
            output.close()
        if delivery.writer.fileno()!=-1:
            delivery.close()
        memory = resources.finish()
        # Keep diagnostics on exceptions too. Committed evidence is independently
        # readable from the result store; an unfinished trial has no saved row.
        model.last_request = dict(wall_seconds=time.perf_counter()-began,
            stages=dict(model.stages),resources=memory,committed_trials=len(holdings),
            result_bytes=Path(store_path).stat().st_size if Path(store_path).exists() else 0,
            response_bytes=delivery.bytes,received_bytes=delivery.received)
    return dict(model.last_request,wall_seconds=elapsed,summary=clean(aggregate)),holdings


def replay(store):
    """Return committed evidence only; an unfinished trial has no row."""
    with closing(sqlite3.connect(Path(store).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT evidence FROM trials ORDER BY number')]


def hashes(files):
    """Keep raw source identities distinct across canonical package owners."""
    repository=Path(__file__).resolve().parents[2]
    return {path.relative_to(ROOT if path.is_relative_to(ROOT) else repository).as_posix():
            baseline.file_hash(path) for path in files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--workdir',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,default=ROOT/'docs/plans/compiled-backtest/phases/CB-01/workloads.json')
    parser.add_argument('--methods',nargs='+',choices=METHODS,default=list(METHODS))
    parser.add_argument('--cases',nargs='*')
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--no-control-after',action='store_true',help='Exploratory only; does not qualify 5x.')
    parser.add_argument('--max-seconds',type=float,default=180.,
                        help='Per-method request budget, checked between batches; expired cases stay incomplete.')
    args = parser.parse_args()
    if not math.isfinite(args.max_seconds) or args.max_seconds<=0:
        parser.error('--max-seconds must be finite and positive')
    admission.require_execution()
    os.environ.setdefault('NUMBA_NUM_THREADS','4')
    os.environ['BACKTEST_BASELINE_RUNTIME'] = str(args.runtime)
    baseline.bootstrap(args.runtime)
    bind_financial()
    root,workdir = args.runtime.resolve(),args.workdir.resolve()
    baseline.assert_workdir(root,workdir)
    workdir.mkdir(parents=True,exist_ok=True)
    s = baseline.s
    methods,unavailable = {},{}
    for name in args.methods:
        try:
            methods[name] = importlib.import_module('tools.experiments.bench_methods_'+name)
        except ImportError as error:
            unavailable[name] = dict(status='unavailable',error_type=type(error).__name__,error=str(error))
    sources = [Path(__file__),Path(baseline.__file__),ROOT/'tools/__init__.py',
               ROOT/'tools/experiments/__init__.py']+[ROOT/'tools/experiments'/('bench_methods_'+name+'.py') for name in args.methods]
    for method in methods.values():
        sources.extend(getattr(method,'SOURCE_FILES',()))
    sources = list(dict.fromkeys(sources))
    source_hashes = hashes(sources)
    def check_sources():
        if source_hashes != hashes(sources):
            raise ValueError('Experiment source changed during measurement.')
    manifest = baseline.load(args.manifest)
    report = dict(status='exploratory',source_hashes=source_hashes,environment=baseline.environment(),
                  methods=args.methods,seed=args.seed,runs=[],
                  unavailable=unavailable,
                  limitations=['Shared scalar finance remains Python; this does not rank full replacement engines.',
                               'Current full freshness scan is retained in all headline timings.',
                               'One seed is a pilot; qualification requires all three frozen seeds.',
                               'Loading and compilation are excluded from warm time and separately measured.'],
                  method_request_budget_seconds=args.max_seconds)
    check_sources()
    with baseline.coordinator.access():
        reference = research.connect(full_prices=True);reference.close()
        source = daily.connect()
        model = None
        try:
            baseline.validate_manifest(manifest,source)
            before = baseline.identity(root)
            report['input_identity_sha256'] = baseline.digest(before)
            report['input_identity'] = {key:value for key,value in before.items() if key!='daily_generation'}
            report['workload_sha256'] = manifest['sha256']
            template = workdir/'template.sqlite'
            if template.exists():
                raise ValueError('Use a new work directory for each comparative run.')
            with closing(sqlite3.connect(template)) as target:
                source.backup(target)
                baseline.clear_books(target)
            cases = [case for case in manifest['primary_cases'] if case['seed']==args.seed and
                     (not args.cases or case['id'] in args.cases)]
            for case in cases:
                print(json.dumps(dict(event='case_start',case=case['id'])),flush=True)
                configuration = baseline.configuration(manifest,case,source)
                control_path = workdir/(case['id']+'-control.sqlite')
                shutil.copyfile(template,control_path)
                control,evidence = baseline.request(control_path,manifest,case,workdir/'telemetry'/case['id']/'before')
                control_path.unlink()
                reference_file = workdir/(case['id']+'-reference-evidence.json')
                baseline.publish(reference_file,evidence)
                item = dict(case=case,control_before=control,candidates=dict(unavailable),
                    reference_evidence_file=reference_file.name,
                    reference_evidence_sha256=baseline.file_hash(reference_file))
                for name,method in methods.items():
                    print(json.dumps(dict(event='method_start',method=name,case=case['id'])),flush=True)
                    check_sources()
                    setup_resources = baseline.Resources();setup_resources.start()
                    started = time.perf_counter()
                    resolver = None
                    candidate_model = None
                    setup_seconds = setup_memory = None
                    store = workdir/(case['id']+'-'+name+'.sqlite')
                    try:
                        if hasattr(method,'open_model'):
                            candidate_model = method.open_model(source,s)
                        else:
                            if model is None:
                                model = Model(source,s)
                                report['scalar_base_load_seconds'] = model.base_seconds
                            candidate_model = model
                        candidate_model.last_request = None
                        resolver = method.open_prices(source)
                        setup_seconds = time.perf_counter()-started
                        setup_memory = setup_resources.finish()
                        def freshness():
                            checked = daily.connect()
                            checked.close()
                        def progress(event):
                            if event['completed'] in (1,8,16,24):
                                print(json.dumps(dict(event='trial',method=name,case=case['id'],
                                                      completed=event['completed'])),flush=True)
                        measurement,picks = run_request(candidate_model,resolver,configuration,store,
                            freshness=freshness,progress=progress,budget_seconds=args.max_seconds,
                            binding=dict(input_identity=report['input_identity_sha256'],
                                         source_hashes=source_hashes,method=name))
                        comparison = baseline.compare(evidence,picks)
                        summary_comparison = baseline.compare(control['summary'],measurement['summary'])
                        persisted = replay(store)
                        replay_comparison = baseline.compare(picks,persisted)
                        if not replay_comparison['exact']:
                            raise ValueError('Durable trial evidence changed on replay.')
                        check_sources()
                        evidence_file = workdir/(case['id']+'-'+name+'-evidence.json')
                        baseline.publish(evidence_file,picks)
                        item['candidates'][name] = dict(status='matched',measurement=measurement,
                            comparison=comparison,summary_comparison=summary_comparison,
                            setup_seconds=setup_seconds,setup_resources=setup_memory,backend_stats=resolver.stats,
                            model_setup=getattr(candidate_model,'setup_stats',{}),
                            evidence_file=evidence_file.name,evidence_sha256=baseline.file_hash(evidence_file),
                            result_store_file=store.name,result_store_sha256=baseline.file_hash(store),
                            speedup_before=control['wall_seconds']/measurement['wall_seconds'])
                        print(json.dumps(dict(event='method_complete',method=name,case=case['id'],
                            seconds=measurement['wall_seconds'],speedup=item['candidates'][name]['speedup_before'])),flush=True)
                    except Exception as error:
                        if setup_seconds is None:
                            setup_seconds = time.perf_counter()-started
                        if setup_memory is None:
                            setup_memory = setup_resources.finish()
                        failed = dict(status='failed',error_type=type(error).__name__,error=str(error),
                            setup_seconds=setup_seconds,setup_resources=setup_memory,
                            model_setup=getattr(candidate_model,'setup_stats',{}),
                            backend_stats=dict(resolver.stats) if resolver is not None else None,
                            measurement=getattr(candidate_model,'last_request',None))
                        if store.exists():
                            failed.update(result_store_file=store.name,
                                          result_store_sha256=baseline.file_hash(store))
                            try:
                                partial = replay(store)
                                failed['committed_trials'] = len(partial)
                                failed['partial_comparison'] = baseline.compare(evidence[:len(partial)],partial)
                            except Exception as partial_error:
                                failed['partial_evidence_error'] = dict(
                                    error_type=type(partial_error).__name__,error=str(partial_error))
                        item['candidates'][name] = failed
                        print(json.dumps(dict(event='method_failed',method=name,error=str(error))),flush=True)
                    finally:
                        if not setup_resources.stop.is_set():
                            setup_resources.finish()
                        if resolver is not None:
                            resolver.close()
                        if candidate_model is not None and candidate_model is not model:
                            candidate_model.close()
                    baseline.publish(workdir/'comparison.json',dict(report,current_case=item))
                if not args.no_control_after:
                    after_path = workdir/(case['id']+'-after.sqlite')
                    shutil.copyfile(template,after_path)
                    after,after_picks = baseline.request(after_path,manifest,case,workdir/'telemetry'/case['id']/'after')
                    after_path.unlink()
                    item['control_comparison'] = baseline.compare(evidence,after_picks)
                    if not item['control_comparison']['exact']:
                        raise ValueError('Current-engine controls changed complete evidence.')
                    item['control_after'] = after
                    for result in item['candidates'].values():
                        if result['status']=='matched':
                            result['conservative_speedup'] = min(control['wall_seconds'],after['wall_seconds'])/result['measurement']['wall_seconds']
                            result['control_drift_ratio'] = max(control['wall_seconds'],after['wall_seconds'])/min(control['wall_seconds'],after['wall_seconds'])
                if baseline.identity(root)!=before:
                    raise ValueError('Production inputs changed during comparison.')
                report['runs'].append(item)
                report['production_unchanged'] = True
                baseline.publish(workdir/'comparison.json',report)
            check_sources()
        finally:
            if model is not None:
                model.close()
            source.close()
    print(json.dumps(dict(event='complete',cases=len(report['runs']),report=str(workdir/'comparison.json'))),flush=True)


if __name__=='__main__':
    main()

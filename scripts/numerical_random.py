"""Offline random-trial recovery over an explicitly borrowed CB-09 portfolio.

No runtime discovery, planner replacement, application routing or user store.
Caller holds source-before-import and cache ownership through store, portfolio,
provider and attachment closure. Validate current inputs even on full recovery.
"""
import ast
from contextlib import contextmanager
import tempfile
from copy import deepcopy
import hashlib
import json
from importlib.metadata import version
from pathlib import Path
import platform
import sqlite3
import sys
import time

import numerical_calendar
import numerical_trial
import portfolio_results
import robustness
import trial_checkpoints

DIAGNOSTIC_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ('scripts/numerical_random.py','scripts/numerical_portfolio.py',
                'scripts/numerical_numba.py','scripts/numerical_runtime.py',
                'scripts/numerical_runtime_child.py','scripts/numerical_session.py',
                'scripts/numerical_execution.py','scripts/numerical_trial_pool.py',
                'scripts/numerical_trial_worker.py',
                'scripts/trial_checkpoints.py','scripts/robustness.py')
COMPATIBILITY_ROOTS = ('tools/numerical_trials.py','tools/numerical_portfolios.py',
                'tools/bench_candidates_numba.py','tools/portfolio_workspace.py')


def source_identity():
    """Hash the transitive local Python imports, without importing providers.

    Keys are repository-relative POSIX paths. Policy sources and extraction,
    numerical decisions, SQL selection, calendar, reducer and adapter code all
    participate. This conservative closure may reject safe reuse after an
    unrelated local dependency edit; it cannot reuse changed calculation code.
    """
    pending=[ROOT/name for name in SOURCE_ROOTS]
    pending += [ROOT/name for name in COMPATIBILITY_ROOTS if (ROOT/name).is_file()]
    seen={}
    while pending:
        path=pending.pop()
        key=path.relative_to(ROOT).as_posix()
        if key in seen:continue
        content=path.read_bytes();seen[key]=hashlib.sha256(content).hexdigest()
        for node in ast.walk(ast.parse(content,filename=key)):
            names=([alias.name for alias in node.names] if isinstance(node,ast.Import)
                   else [node.module] if isinstance(node,ast.ImportFrom) and node.module else [])
            for name in names:
                for folder in ('scripts','tools','website'):
                    candidate=ROOT/folder/(name.split('.')[0]+'.py')
                    if candidate.is_file():pending.append(candidate);break
    resource=ROOT/'scripts/numerical_rust_kernel.rs'
    seen[resource.relative_to(ROOT).as_posix()]=hashlib.sha256(resource.read_bytes()).hexdigest()
    return dict(sorted(seen.items()))


def validate_configuration(portfolio,configuration):
    """Validate every recorded schedule; never resample a recovery plan."""
    portfolio._validate_inputs()
    config=numerical_calendar.validate_plan(portfolio._calendar().sessions,configuration,
        checkpoint=portfolio.s.backtest_control.checkpoint)
    trial_checkpoints.binding_json(dict(generation='validation',policy='validation',schema='validation',
        result_contract=portfolio_results.CONTRACT_VERSION,implementation={'validation':True},
        execution={'validation':True},configuration=config))
    portfolio.validate_selection(config['options'])
    return config


def checkpoint_binding(portfolio,configuration,*,execution=None):
    """One source-owned complete calculation signature; diagnostics excluded."""
    config=validate_configuration(portfolio,configuration)
    inputs=portfolio.inputs
    if execution is None:
        provider=portfolio.provider
        execution=provider_execution(inputs,provider.limits,getattr(provider,'compiler',None))
        execution['provider']=type(provider).__module__+'.'+type(provider).__qualname__
        execution['threads']=provider.stats.get('threads',1)
    binding=dict(generation=inputs.signature,policy=inputs.policy.signature,
        schema=inputs.policy.field_schema,result_contract=portfolio_results.CONTRACT_VERSION,
        implementation=source_identity(),execution=execution,configuration=config)
    trial_checkpoints.binding_json(binding)
    return binding


def provider_execution(inputs,limits,compiler):
    """Describe the numerical contract without constructing its provider."""
    return dict(python=platform.python_version(),implementation=sys.implementation.name,
        architecture=platform.machine(),byteorder=sys.byteorder,sqlite=sqlite3.sqlite_version,
        versions={name:version(name) for name in ('numpy','numba','llvmlite')},
        provider=('numerical_rust.RustExecutor' if limits.get('backend')=='rust' else 'numerical_numba.NumbaExecutor'),
        catalog=json.loads(json.dumps(inputs.policy.fields)),bankruptcy=[list(v) for v in sorted(inputs.bankrupt)],
        limits=deepcopy(limits),fastmath=False,compiler_cache=False,
        threads=limits.get('threads',1),compiler=deepcopy(compiler))


class _Source:
    """A checkpoint reference or leased artifact; replay never retains a batch."""
    def __init__(self,number,experiment,completion=None):
        self.number,self.experiment,self.completion=number,experiment,completion

    def replay_into(self,emit):
        if self.completion is not None:return self.completion.artifact.copy_into(emit)
        summary=self.experiment.replay_into(self.number,emit)
        if summary is None:
            raise ValueError('Expected retained checkpoint disappeared during the active experiment.')
        return summary

    def release(self):
        if self.completion is not None:self.completion.release()


class _LocalCompletion:
    def __init__(self,number,stream,artifact):
        self.number,self.stream,self.artifact=number,stream,artifact

    def release(self):self.stream.close()


class _LocalExecution:
    """Borrow B's evaluator for existing offline calls; one artifact at a time."""
    def __init__(self,portfolio,binding):
        self.portfolio,self.binding=portfolio,binding

    @contextmanager
    def batch(self,specifications):
        evaluator=numerical_trial.TrialEvaluator(self.portfolio,
            calculation_identity=numerical_trial.calculation_identity(self.binding))
        limits=dict(max_bytes=256*1024**2,piece_bytes=1024*1024,record_bytes=8*1024*1024)
        active=[]
        class Batch:
            def completed(inner):
                for spec in specifications:
                    stream=tempfile.TemporaryFile('w+b')
                    completion=_LocalCompletion(spec['number'],stream,None);active.append(completion)
                    descriptor=evaluator.produce(spec,stream,limits=limits)
                    completion.artifact=numerical_trial.open_artifact(stream,descriptor,
                        expected_spec=spec,limits=limits,checkpoint=self.portfolio.s.backtest_control.checkpoint)
                    yield completion
                    completion.release();active.remove(completion)
        try:yield Batch()
        finally:
            for completion in active:completion.release()


@contextmanager
def ordered_sources(portfolio,binding,experiment,progress=None,*,execution=None):
    with experiment.store.coordinating(experiment):
        with _ordered_sources(portfolio,binding,experiment,progress,execution=execution) as sources:
            yield sources


@contextmanager
def _ordered_sources(portfolio,binding,experiment,progress=None,*,execution=None):
    """Recover before startup; parent commits completion order, emits plan order.

    One parent writer owns the active experiment. Its saves never evict its own
    previous rows. No checkpoint read transaction survives a replay call. Retained
    artifacts release immediately; unretained leases provide bounded backpressure.
    The earliest missing trial is submitted first and always owns a reservation.
    """
    if trial_checkpoints.canonical(binding)!=trial_checkpoints.canonical(experiment.binding):
        raise ValueError('Checkpoint experiment belongs to a different calculation binding.')
    config=binding['configuration'];checkpoint=portfolio.s.backtest_control.checkpoint
    stats=dict(recovered_trials=0,calculated_trials=0,retained_trials=0,unretained_trials=0,
               evicted_experiments=0,workers=0)
    ready={};missing=[];frontier=1
    def event(number):
        if progress:progress(dict(type='progress',completed=stats['recovered_trials']+stats['calculated_trials'],
            total=config['requested'],trial=number,**stats))
    for number in range(1,config['requested']+1):
        checkpoint()
        summary=experiment.replay_into(number,lambda period:None)
        if summary is None:missing.append(numerical_trial.specification(binding,number))
        else:
            ready[number]=_Source(number,experiment);stats['recovered_trials']+=1;event(number)
    event(missing[0]['number'] if missing else config['requested'])
    def drain():
        nonlocal frontier
        while frontier in ready:
            checkpoint();source=ready.pop(frontier)
            try:yield source,stats
            finally:source.release()
            frontier+=1
    def sources():
        yield from drain()
        if missing:
            capability=execution() if execution is not None else _LocalExecution(portfolio,binding)
            with capability.batch(missing) as batch:
                stats['workers']=len(getattr(capability,'workers',()))
                for completion in batch.completed():
                    checkpoint()
                    outcome=experiment.save_from(completion.number,completion.artifact.view)
                    stats['calculated_trials']+=1
                    stats['retained_trials' if outcome['retained'] else 'unretained_trials']+=1
                    stats['evicted_experiments']+=outcome['evicted_experiments']
                    if outcome['retained']:
                        completion.release();source=_Source(completion.number,experiment)
                    else:source=_Source(completion.number,experiment,completion)
                    ready[completion.number]=source
                    event(completion.number)
                    yield from drain()
        if frontier!=config['requested']+1:raise ValueError('Incomplete ordered trial frontier.')
    iterator=sources()
    try:yield iterator
    finally:
        iterator.close()
        for source in ready.values():source.release()


def run(portfolio,configuration,experiment,progress=None,*,capture=None,execution=None,binding=None):
    """Collect ordered complete evidence under existing eager admission limits."""
    started=time.perf_counter()
    binding=checkpoint_binding(portfolio,configuration) if binding is None else binding
    config=validate_configuration(portfolio,configuration)
    if trial_checkpoints.canonical(config)!=trial_checkpoints.canonical(binding['configuration']):
        raise ValueError('Calculation binding differs from the recorded plan.')
    for dates in config['samples']:portfolio.admit_eager_result(len(dates),config['options'])
    with ordered_sources(portfolio,binding,experiment,progress,execution=execution) as sources:
        def completed():
            for source,stats in sources:
                collector=portfolio.result_collector(len(config['samples'][source.number-1]),config['options'])
                summary=source.replay_into(collector.period)
                yield source.number,collector.finish(summary),stats
        result=robustness.consume_trials(config,completed(),capture=capture,started=started)
    return dict(diagnostic_version=DIAGNOSTIC_VERSION,contract_version=portfolio_results.CONTRACT_VERSION,
                checkpoint_identity=experiment.identity,result=result)


def run_into(portfolio,configuration,experiment,writer,progress=None,*,execution=None,binding=None):
    """Replay the same ordered sources into the existing bounded evidence sink."""
    started=time.perf_counter()
    try:
        binding=checkpoint_binding(portfolio,configuration) if binding is None else binding
        config=validate_configuration(portfolio,configuration)
        if trial_checkpoints.canonical(config)!=trial_checkpoints.canonical(binding['configuration']):
            raise ValueError('Calculation binding differs from the recorded plan.')
        if writer.expected_trials!=config['requested']:
            raise ValueError('Evidence trial count differs from the recorded plan.')
        rows=[];stats={}
        with ordered_sources(portfolio,binding,experiment,progress,execution=execution) as sources:
            for source,stats in sources:
                writer.start_trial(source.number);counts=[0,0,0]
                requested=config['options'].get('rank_to',50)-config['options'].get('rank_from',1)+1
                def emit(period):
                    writer.period(period)
                    counts[0]+=1;counts[1]+=period['names']==0;counts[2]+=period['names']<requested
                summary=source.replay_into(emit);writer.end_trial(summary)
                rows.append(robustness.summarize(summary,source.number,config['samples'][source.number-1],period_counts=counts))
        result=robustness.summarize_trials(config,rows,started);result['execution']=dict(stats)
        portfolio.s.backtest_control.checkpoint()
        manifest=writer.finish(result)
        return dict(diagnostic_version=DIAGNOSTIC_VERSION,contract_version=portfolio_results.CONTRACT_VERSION,
                    checkpoint_identity=experiment.identity,result=result,evidence=manifest)
    except BaseException:
        writer.failed=True
        raise

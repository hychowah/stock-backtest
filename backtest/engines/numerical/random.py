"""Offline random-trial recovery over an explicitly borrowed CB-09 portfolio.

No runtime discovery, planner replacement, application routing or user store.
Caller holds source-before-import and cache ownership through store, portfolio,
provider and attachment closure. Validate current inputs even on full recovery.
"""
from backtest import portfolio_results
from backtest.runtime import backtest_control

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

from backtest import calendar_requests as numerical_calendar
from backtest.engines.numerical import trial as numerical_trial
from backtest import portfolio_results as portfolio_results
from backtest.engines.original import robustness as robustness
from backtest.engines.numerical import checkpoints as trial_checkpoints

DIAGNOSTIC_VERSION = 1
ROOT = Path(__file__).resolve().parents[3]
# Direct-file children load the source owner by filename before package imports.
SOURCE_ROOTS = ('website/runtime_access.py','backtest/engines/numerical/random.py','backtest/engines/numerical/portfolio.py',
                'backtest/engines/numerical/numba.py','backtest/engines/numerical/runtime.py',
                'backtest/engines/numerical/runtime_child.py','backtest/engines/numerical/session.py',
                'backtest/engines/numerical/execution.py','backtest/engines/numerical/trial_pool.py',
                'backtest/engines/numerical/trial_worker.py',
                'backtest/engines/numerical/checkpoints.py','backtest/engines/original/robustness.py',
                'backtest/engines/numerical/rust.py','backtest/engines/numerical/rust_kernel.rs')

def source_identity():
    """Hash the transitive local Python imports, without importing providers.

    Keys are repository-relative POSIX paths. Policy sources and extraction,
    numerical decisions, SQL selection, calendar, reducer and adapter code all
    participate. This conservative closure may reject safe reuse after an
    unrelated local dependency edit; it cannot reuse changed calculation code.
    """
    return _source_closure(ROOT, SOURCE_ROOTS)


def _source_closure(root, roots):
    """Resolve absolute/relative local imports and package initializers statically.

    Reading syntax does not execute package code or load optional providers.
    Keep the original flat-script search order for remaining command modules.
    """
    root=Path(root).resolve()
    pending=[root/name for name in roots]
    seen={}

    def resolve(parts):
        if not parts:return []
        candidates=[]
        for folder in (root, root/'scripts', root/'tools', root/'website'):
            target=folder.joinpath(*parts)
            path=target.with_suffix('.py')
            if not path.is_file():path=target/'__init__.py'
            if not path.is_file():continue
            # Importing a submodule also executes each enclosing initializer.
            for parent in path.parents:
                if parent==folder:break
                init=parent/'__init__.py'
                if init.is_file():candidates.append(init)
            return [*candidates,path]
        return []

    while pending:
        path=pending.pop()
        key=path.relative_to(root).as_posix()
        if key in seen:continue
        content=path.read_bytes();seen[key]=hashlib.sha256(content).hexdigest()
        if path.suffix!='.py':
            if key!='backtest/engines/numerical/rust_kernel.rs':
                raise ValueError('Unsupported numerical source resource.')
            continue
        package=list(path.relative_to(root).parts[:-1])
        for node in ast.walk(ast.parse(content,filename=key)):
            if isinstance(node,ast.Import):
                for alias in node.names:pending.extend(resolve(alias.name.split('.')))
            elif isinstance(node,ast.ImportFrom):
                base=(package[:len(package)-node.level+1] if node.level else [])
                if node.module:base+=node.module.split('.')
                pending.extend(resolve(base))
                for alias in node.names:
                    if alias.name!='*':pending.extend(resolve([*base,alias.name]))
    return dict(sorted(seen.items()))


def validate_configuration(portfolio,configuration):
    """Validate every recorded schedule; never resample a recovery plan."""
    portfolio._validate_inputs()
    config=numerical_calendar.validate_plan(portfolio._calendar().sessions,configuration,
        checkpoint=backtest_control.checkpoint)
    trial_checkpoints.binding_json(dict(generation='validation',policy='validation',schema='validation',
        result_contract=portfolio_results.CONTRACT_VERSION,implementation={'validation':True},
        execution={'validation':True},configuration=config))
    if 'strategy' in config['options']:
        from backtest.application import strategy_requests
        strategy_requests.check_options(config['options'])
    else:portfolio.validate_selection(config['options'])
    return config


def checkpoint_binding(portfolio,configuration,*,execution=None,scalar_capture=None):
    """One source-owned complete calculation signature; diagnostics excluded."""
    config=validate_configuration(portfolio,configuration)
    inputs=portfolio.inputs
    if execution is None:
        provider=portfolio.provider
        execution=provider_execution(inputs,provider.limits,getattr(provider,'compiler',None))
        execution['provider']=type(provider).__module__+'.'+type(provider).__qualname__
        execution['threads']=provider.stats.get('threads',1)
    binding=dict(generation=inputs.signature,policy=inputs.policy.signature,
        schema=inputs.policy.field_schema,result_contract=2 if scalar_capture is not None else portfolio_results.CONTRACT_VERSION,
        implementation=source_identity(),execution=execution,configuration=config)
    if scalar_capture is not None:
        from backtest.engines.numerical import formulas, scalar
        binding['execution']['scalar']=dict(version=1,capture=deepcopy(scalar_capture),
            arithmetic=formulas.policy_fingerprint(),resources=scalar.resources(execution['limits']))
    trial_checkpoints.binding_json(binding)
    return binding


def provider_execution(inputs,limits,compiler):
    """Describe the numerical contract without constructing its provider."""
    return dict(python=platform.python_version(),implementation=sys.implementation.name,
        architecture=platform.machine(),byteorder=sys.byteorder,sqlite=sqlite3.sqlite_version,
        versions={name:version(name) for name in ('numpy','numba','llvmlite')},
        provider='backtest.engines.numerical.numba.NumbaExecutor',
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

    def replay_evidence(self,writer):
        if self.completion is not None:return self.completion.artifact.replay_into(writer)
        summary=self.experiment.replay_evidence(self.number,writer)
        if summary is None:raise ValueError('Expected scalar checkpoint disappeared.')
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
        scalar_resources=None
        if self.binding['result_contract']==2:
            from backtest.engines.numerical import scalar
            scalar_resources=scalar.Resources.__new__(scalar.Resources)
            scalar.Resources.__init__(scalar_resources,self.portfolio.inputs,self.binding['execution']['limits'])
            evaluator=scalar.TrialEvaluator(scalar_resources,calculation_identity=numerical_trial.calculation_identity(self.binding))
        else:
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
                        expected_spec=spec,limits=limits,checkpoint=backtest_control.checkpoint)
                    yield completion
                    completion.release();active.remove(completion)
        try:yield Batch()
        finally:
            for completion in active:completion.release()
            if scalar_resources is not None:scalar_resources.close()


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
    config=binding['configuration'];checkpoint=backtest_control.checkpoint
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


def run_into(portfolio,configuration,experiment,writer,progress=None,*,execution=None,binding=None,producer=None):
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
                scalar=binding['result_contract']==2
                selection=(binding['execution']['scalar']['capture']['selection'] if scalar else config['options'])
                requested=selection.get('rank_to',50)-selection.get('rank_from',1)+1
                def emit(period):
                    writer.period(period)
                    counts[0]+=1;counts[1]+=period['names']==0;counts[2]+=period['names']<requested
                if scalar:
                    class Destination:
                        _order=writer._order
                        def _write(self,record):
                            writer._write(record)
                            if record['type']=='period':
                                count=record['value']['names']
                                counts[0]+=1;counts[1]+=count==0;counts[2]+=count<requested
                    summary=source.replay_evidence(Destination())
                else:summary=source.replay_into(emit)
                writer.end_trial(summary)
                rows.append(robustness.summarize(summary,source.number,config['samples'][source.number-1],period_counts=counts))
        result=robustness.summarize_trials(config,rows,started);result['execution']=dict(stats)
        if producer is not None:result['producer']=deepcopy(producer)
        backtest_control.checkpoint()
        manifest=writer.finish(result)
        return dict(diagnostic_version=DIAGNOSTIC_VERSION,contract_version=binding['result_contract'],
                    checkpoint_identity=experiment.identity,result=result,evidence=manifest)
    except BaseException:
        writer.failed=True
        raise

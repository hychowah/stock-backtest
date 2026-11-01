"""Offline random-trial recovery over an explicitly borrowed CB-09 portfolio.

No runtime discovery, planner replacement, application routing or user store.
Caller holds source-before-import and cache ownership through store, portfolio,
provider and attachment closure. Validate current inputs even on full recovery.
"""
import ast
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


def checkpoint_binding(portfolio,configuration):
    """One source-owned complete calculation signature; diagnostics excluded."""
    config=validate_configuration(portfolio,configuration)
    inputs,provider=portfolio.inputs,portfolio.provider
    execution=dict(python=platform.python_version(),implementation=sys.implementation.name,
        architecture=platform.machine(),byteorder=sys.byteorder,sqlite=sqlite3.sqlite_version,
        versions={name:version(name) for name in ('numpy','numba','llvmlite')},
        provider=type(provider).__module__+'.'+type(provider).__qualname__,
        catalog=json.loads(json.dumps(inputs.policy.fields)),bankruptcy=[list(v) for v in sorted(inputs.bankrupt)],
        limits=deepcopy(provider.limits),fastmath=False,compiler_cache=False,
        threads=provider.stats.get('threads',1),compiler=deepcopy(getattr(provider,'compiler',None)))
    binding=dict(generation=inputs.signature,policy=inputs.policy.signature,
        schema=inputs.policy.field_schema,result_contract=portfolio_results.CONTRACT_VERSION,
        implementation=source_identity(),execution=execution,configuration=config)
    trial_checkpoints.binding_json(binding)
    return binding


def run(portfolio,configuration,experiment,progress=None,*,capture=None):
    """Commit each fresh trial before completion events and ordered capture.

    Full recovery calls no provider.begin/evaluate or SQL staging. The borrowed
    provider may already be compiled by its owner; this adapter initializes no
    provider or persistent factor cache. CB-06 retains its separate bounded cache.
    """
    started=time.perf_counter()
    binding=checkpoint_binding(portfolio,configuration)
    if trial_checkpoints.canonical(binding) != trial_checkpoints.canonical(experiment.binding):
        raise ValueError('Checkpoint experiment belongs to a different calculation binding.')
    config=binding['configuration']
    evaluator=numerical_trial.TrialEvaluator(portfolio,
        calculation_identity=numerical_trial.calculation_identity(binding))
    stats=dict(recovered_trials=0,calculated_trials=0,retained_trials=0,unretained_trials=0,
               evicted_experiments=0,workers=0)

    def event(completed,number):
        if progress:
            progress(dict(type='progress',completed=completed,total=config['requested'],trial=number,**stats))

    def completed():
        for number,dates in enumerate(config['samples'],1):
            portfolio.s.backtest_control.checkpoint()
            event(number-1,number)
            result=experiment.load(number)
            if result is None:
                collector=portfolio.result_collector(len(dates),config['options'])
                summary=evaluator.evaluate_into(numerical_trial.specification(binding,number),collector.period)
                result=collector.finish(summary)
                outcome=experiment.save(number,result)
                stats['calculated_trials']+=1
                stats['retained_trials' if outcome['retained'] else 'unretained_trials']+=1
                stats['evicted_experiments']+=outcome['evicted_experiments']
            else:stats['recovered_trials']+=1
            event(number,number)
            yield number,result,stats
    result=robustness.consume_trials(config,completed(),capture=capture,started=started)
    return dict(diagnostic_version=DIAGNOSTIC_VERSION,contract_version=portfolio_results.CONTRACT_VERSION,
                checkpoint_identity=experiment.identity,result=result)


def run_into(portfolio,configuration,experiment,writer,progress=None):
    """Produce complete evidence with one period retained; no full-result capture.

    Validate current inputs before reuse. Seal and retain each trial before its
    completed progress event. The caller owns the stream and final publication.
    A callback failure leaves prior committed checkpoints and incomplete output.
    """
    started=time.perf_counter()
    try:
        binding=checkpoint_binding(portfolio,configuration)
        if trial_checkpoints.canonical(binding)!=trial_checkpoints.canonical(experiment.binding):
            raise ValueError('Checkpoint experiment belongs to a different calculation binding.')
        config=binding['configuration']
        evaluator=numerical_trial.TrialEvaluator(portfolio,
            calculation_identity=numerical_trial.calculation_identity(binding))
        if writer.expected_trials!=config['requested']:
            raise ValueError('Evidence trial count differs from the recorded plan.')
        stats=dict(recovered_trials=0,calculated_trials=0,retained_trials=0,unretained_trials=0,
                   evicted_experiments=0,workers=0)
        rows=[]
        def event(completed,number):
            if progress:progress(dict(type='progress',completed=completed,total=config['requested'],trial=number,**stats))
        for number,dates in enumerate(config['samples'],1):
            portfolio.s.backtest_control.checkpoint();event(number-1,number)
            writer.start_trial(number)
            counts=[0,0,0]
            requested=config['options'].get('rank_to',50)-config['options'].get('rank_from',1)+1
            def emit(period):
                writer.period(period)
                counts[0]+=1;counts[1]+=period['names']==0;counts[2]+=period['names']<requested
            summary=experiment.replay_into(number,emit)
            if summary is None:
                summary=evaluator.evaluate_into(numerical_trial.specification(binding,number),emit)
                view=writer.end_trial(summary)
                outcome=experiment.save_from(number,view)
                stats['calculated_trials']+=1
                stats['retained_trials' if outcome['retained'] else 'unretained_trials']+=1
                stats['evicted_experiments']+=outcome['evicted_experiments']
            else:
                writer.end_trial(summary);stats['recovered_trials']+=1
            rows.append(robustness.summarize(summary,number,dates,period_counts=counts))
            event(number,number)
        result=robustness.summarize_trials(config,rows,started);result['execution']=stats
        portfolio.s.backtest_control.checkpoint()
        manifest=writer.finish(result)
        return dict(diagnostic_version=DIAGNOSTIC_VERSION,contract_version=portfolio_results.CONTRACT_VERSION,
                    checkpoint_identity=experiment.identity,result=result,evidence=manifest)
    except BaseException:
        writer.failed=True
        raise

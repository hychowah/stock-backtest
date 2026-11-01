"""Parent checkpoint ordering, lazy recovery and bounded parallel presentation."""
from copy import deepcopy
import io
import json
import sqlite3
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests'),str(ROOT/'tools'),str(ROOT/'website')]
import backtest_control
import numerical_random as random
import numerical_session
from numerical_books import PythonExecutor
from numerical_execution import ExecutionPolicy
from numerical_identity import compiler_identity
from numerical_numba import NumbaExecutor
from numerical_portfolio import NumericalPortfolio, compare_results
from numerical_trial_pool import TrialPool
from numerical_workspace import RequestWorkspace
import result_evidence
import robustness
import test_numerical_generation as generations
import trial_checkpoints


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=generations.GenerationTests('test_export_values_order_missingness_and_mutable_books_reuse')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.fixture.prepare()
        self.inputs=self.fixture.attach()
        self.policy=ExecutionPolicy(dict(workers=2,threads_per_worker=1,close_seconds=.5,
            artifact_bytes=8*1024**2,piece_bytes=127,record_bytes=16384))
        self.workspace=RequestWorkspace(self.inputs,result_workspace_bytes=64*1024**2)
        self.addCleanup(self.workspace.close)
        self.compiler=compiler_identity(self.inputs,1)
        self.provider=None;self.portfolio=None;self.pools=[];self.store_count=0

    def local(self):
        if self.portfolio is None:
            self.provider=NumbaExecutor(self.inputs,limits=self.policy.provider_limits)
            self.addCleanup(self.provider.close)
            self.portfolio=NumericalPortfolio(self.inputs,self.provider)
            self.addCleanup(self.portfolio.close)
        return self.portfolio

    def configuration(self,count=4,**options):
        return robustness.plan(self.workspace.db,start='2015-01-05',end='2016-12-30',
            trials=count,seed=42,min_cap=0.,min_ev=0.,rank_to=5,**options)

    def binding(self,config):
        execution=random.provider_execution(self.inputs,self.policy.provider_limits,self.compiler)
        execution['trial_pool']=self.policy.execution_identity(self.compiler)
        return random.checkpoint_binding(self.workspace,config,execution=execution)

    def experiment(self,config,**limits):
        self.store_count+=1
        store=trial_checkpoints.Store(self.fixture.root/('coordinator-'+str(self.store_count)+'.sqlite'),**limits)
        self.addCleanup(store.close)
        return store.open(self.binding(config))

    def pool(self):
        pool=TrialPool(source_root=ROOT,scratch=self.fixture.root/('pool-'+str(len(self.pools))),
            reference=self.inputs.worker_reference(),source_identity=random.source_identity(),
            compiler_identity=self.compiler,policy=self.policy)
        self.pools.append(pool);self.addCleanup(pool.close)
        return pool

    def run_parallel(self,config,experiment,**callbacks):
        return random.run(self.workspace,config,experiment,execution=self.pool,
                          binding=self.binding(config),**callbacks)['result']

    def force_second_first(self,pool):
        send,event=pool._send,pool._event;delayed=[]
        def send_later(worker,value):
            if value.get('command')=='trial' and worker.index==0 and not delayed and pool.stats['completed_trials']==0:
                delayed.append((worker,value));return
            return send(worker,value)
        def next_event(*args):
            worker,value=event(*args)
            if value.get('event')=='completed' and delayed:send(*delayed.pop())
            return worker,value
        self.enterContext(patch.object(pool,'_send',side_effect=send_later))
        self.enterContext(patch.object(pool,'_event',side_effect=next_event))

    def test_parallel_local_original_eager_streaming_parity_and_prompt_ordered_commits(self):
        maximum_absolute=maximum_relative=0.;cases=0
        pool=self.pool();self.force_second_first(pool)
        for stock_pool in ('legacy','cached'):
            for order in ('filter_first','rank_first'):
                for metric in self.fixture.s.metrics.METRICS:
                    config=self.configuration(3,pool=stock_pool,selection_order=order,metric=metric,
                        filters=[dict(field='pe',op='gt',value=-1e9)])
                    experiment=self.experiment(config);commits=[];captures=[];events=[]
                    save=experiment.save_from
                    def save_observed(number,view):
                        outcome=save(number,view);commits.append(number);return outcome
                    with patch.object(experiment,'save_from',side_effect=save_observed):
                        actual=random.run(self.workspace,config,experiment,events.append,capture=lambda n,r:captures.append((n,r)),
                            execution=lambda:pool,binding=self.binding(config))['result']
                    self.assertEqual([n for n,r in captures],[1,2,3])
                    if cases==0:self.assertEqual(commits[:2],[2,1])
                    self.assertEqual(pool.stats['reserved_slots'],0)
                    self.assertEqual(actual['execution']['calculated_trials'],3)
                    for number,result in captures:
                        expected=self.fixture.s.backtest_dates(self.fixture.db,dates=config['samples'][number-1],
                            **{k:config[k] for k in ('start','end','months')},**config['options'])
                        agreement=compare_results(expected,result);self.assertTrue(agreement['exact'],agreement)
                        maximum_absolute=max(maximum_absolute,agreement['maximum_absolute']);maximum_relative=max(maximum_relative,agreement['maximum_relative']);cases+=1
                    stream=io.BytesIO();writer=result_evidence.Writer(stream,trials=3,metadata={},max_bytes=8*1024**2,piece_bytes=127,record_bytes=16384)
                    result=random.run_into(self.workspace,config,experiment,writer,execution=lambda:pool,binding=self.binding(config))
                    self.assertEqual(result['result']['distributions'],actual['distributions'])
                    self.assertEqual(result['result']['execution']['recovered_trials'],3)
                    # A separately bound local diagnostic shares evaluator and financial contract.
                    local_exp=trial_checkpoints.Store(self.fixture.root/('local-'+str(cases)+'.sqlite'))
                    self.addCleanup(local_exp.close)
                    binding=random.checkpoint_binding(self.local(),config)
                    observed=[]
                    random.run(self.local(),config,local_exp.open(binding),capture=lambda n,r:observed.append(r))
                    for (_,a),b in zip(captures,observed):self.assertTrue(compare_results(a,b)['exact'])
        print(json.dumps(dict(check='parallel-coordinator-financial',cases=cases,maximum_absolute=maximum_absolute,
            maximum_relative=maximum_relative,tolerance=1e-12)),flush=True)

    def test_zero_retention_slow_first_has_bounded_leases_and_no_deadlock(self):
        config=self.configuration(6);experiment=self.experiment(config,max_payload_bytes=0)
        pool=self.pool();self.force_second_first(pool);saves=[];outputs=[];save=experiment.save_from
        def saved(number,view):
            outcome=save(number,view);saves.append(number)
            self.assertLessEqual(pool.stats['reserved_slots'],2)
            if number==2:self.assertEqual(pool.stats['reserved_slots'],2)
            return outcome
        with patch.object(experiment,'save_from',side_effect=saved):
            result=random.run(self.workspace,config,experiment,capture=lambda n,r:outputs.append(n),
                execution=lambda:pool,binding=self.binding(config))['result']
        self.assertEqual(saves[:2],[2,1]);self.assertEqual(outputs,list(range(1,7)))
        self.assertEqual(result['execution']['unretained_trials'],6)
        self.assertEqual(pool.stats['peak_reserved_slots'],2);self.assertEqual(pool.stats['reserved_slots'],0)
        self.assertEqual(experiment.store.measurements()['trials'],0)

    def test_fresh_parallel_stream_and_one_missing_uses_one_worker_under_capacity(self):
        config=self.configuration(3,pool='cached',selection_order='rank_first')
        experiment=self.experiment(config);pool=self.pool();binding=self.binding(config)
        stream=io.BytesIO();writer=result_evidence.Writer(stream,trials=3,metadata={},
            max_bytes=8*1024**2,piece_bytes=127,record_bytes=16384)
        result=random.run_into(self.workspace,config,experiment,writer,execution=lambda:pool,binding=binding)
        self.assertEqual(result['result']['execution']['calculated_trials'],3)
        self.assertEqual(result['result']['execution']['workers'],2)
        expected=robustness.run(self.fixture.db,config,workers=1)
        self.assertEqual(result['result']['distributions'],expected['distributions'])
        reader=result_evidence.Reader(stream,max_bytes=8*1024**2)
        observed=[]
        for view in reader.trials():
            actual=dict(periods=list(view.periods()),**view.summary)
            number=len(observed)+1
            reference=self.fixture.s.backtest_dates(self.fixture.db,dates=config['samples'][number-1],
                **{key:config[key] for key in ('start','end','months')},**config['options'])
            self.assertEqual(view.number,number)
            self.assertTrue(compare_results(reference,actual)['exact'])
            observed.append(actual)
        self.assertEqual(len(observed),3)
        experiment.store.db.execute('DELETE FROM trials WHERE number=2')
        subset=self.pool()
        replay=random.run(self.workspace,config,experiment,execution=lambda:subset,binding=binding)['result']
        self.assertEqual(replay['execution']['recovered_trials'],2)
        self.assertEqual(replay['execution']['workers'],1)
        self.assertEqual(subset.stats['started_workers'],1)
        self.assertEqual(subset.execution_identity,pool.execution_identity)

    def test_mixed_gaps_duplicate_schedules_scan_before_pool_and_preserve_rows(self):
        config=self.configuration(5);config['samples'][3]=deepcopy(config['samples'][1])
        experiment=self.experiment(config);binding=self.binding(config)
        # Retain trials 2 and 4 without changing execution binding.
        local=random._LocalExecution(self.local(),binding)
        with local.batch([random.numerical_trial.specification(binding,n) for n in (2,4)]) as batch:
            for completion in batch.completed():experiment.save_from(completion.number,completion.artifact.view)
        previous={n:experiment.load(n) for n in (2,4)};lookups=[];replay=experiment.replay_into
        def inspected(number,emit):lookups.append(number);return replay(number,emit)
        def start():
            self.assertEqual(lookups[:5],[1,2,3,4,5]);return self.pool()
        captured=[]
        with patch.object(experiment,'replay_into',side_effect=inspected):
            result=random.run(self.workspace,config,experiment,capture=lambda n,r:captured.append(n),
                execution=start,binding=binding)['result']
        self.assertEqual(captured,[1,2,3,4,5]);self.assertEqual(result['execution']['recovered_trials'],2)
        self.assertEqual(result['execution']['calculated_trials'],3)
        for n in (2,4):self.assertEqual(previous[n],experiment.load(n))

    def test_full_hit_new_session_constructs_no_provider_or_pool_and_identity_is_predicted(self):
        config=self.configuration(2);experiment=self.experiment(config)
        self.run_parallel(config,experiment)
        configuration=dict(threads=1,generation_path=str(self.fixture.store.path),
            checkpoint_path=str(experiment.store.path),source_root=str(ROOT),scratch=str(self.fixture.root/'session'),
            execution=dict(workers=2,threads_per_worker=1,close_seconds=.5,
                artifact_bytes=8*1024**2,piece_bytes=127,record_bytes=16384))
        with patch.object(numerical_session,'GenerationStore',return_value=self.fixture.store),\
             patch.object(numerical_session,'NumbaExecutor',side_effect=AssertionError('No provider on full recovery')):
            session=numerical_session.Session(configuration)
            try:
                self.assertIsNone(session.provider);self.assertEqual(session.expected_compiler,self.compiler)
                with patch.object(session,'pool',side_effect=AssertionError('No pool on full recovery')):
                    result=session.calculate('random',dict(start=config['start'],end=config['end'],months=config['months'],
                        trials=2,seed=42,**config['options']),None,lambda plan:None,planned=config)
                self.assertEqual(result['execution']['recovered_trials'],2)
                self.assertIsNone(session.provider);self.assertIsNone(session.trial_pool)
            finally:
                workspace=session.workspace
                session.close()
                self.assertTrue(workspace.closed)
                with self.assertRaises(sqlite3.ProgrammingError):workspace.db.execute('SELECT 1')

    def test_invalid_late_dates_and_execution_mismatch_precede_recovery(self):
        config=self.configuration();experiment=self.experiment(config)
        changed=deepcopy(config);changed['samples'][-1]=['2099-01-01']
        with patch.object(experiment,'replay_into',side_effect=AssertionError('No invalid lookup')):
            with self.assertRaises(ValueError):self.run_parallel(changed,experiment)
        changed=self.binding(config);changed['execution']['trial_pool']['workers']=3
        with patch.object(experiment,'replay_into',side_effect=AssertionError('No mismatched lookup')):
            with self.assertRaisesRegex(ValueError,'different calculation binding'):
                random.run(self.workspace,config,experiment,execution=self.pool,binding=changed)
        self.assertFalse(self.pools)

    def test_custom_portfolio_staging_errors_keep_financial_contract_and_close_transaction(self):
        portfolio=self.local();config=self.configuration(1)
        for error in (sqlite3.OperationalError('fictional SQL'),KeyError('fictional row')):
            with patch('numerical_portfolio.stage_book',side_effect=error):
                with self.assertRaisesRegex(ValueError,'SQL staging contract differs'):
                    portfolio.backtest_dates(dates=config['samples'][0],
                        **{key:config[key] for key in ('start','end','months')},**config['options'])
            self.assertFalse(portfolio.db.in_transaction)

    def test_borrowed_python_provider_binding_fresh_and_recovered_without_compiler(self):
        provider=PythonExecutor(self.inputs);self.addCleanup(provider.close)
        portfolio=NumericalPortfolio(self.inputs,provider);self.addCleanup(portfolio.close)
        config=self.configuration(2);binding=random.checkpoint_binding(portfolio,config)
        self.assertEqual(binding['execution']['provider'],'numerical_books.PythonExecutor')
        self.assertIsNone(binding['execution']['compiler'])
        store=trial_checkpoints.Store(self.fixture.root/'python-diagnostic.sqlite');self.addCleanup(store.close)
        experiment=store.open(binding);captures=[]
        random.run(portfolio,config,experiment,capture=lambda n,r:captures.append(r))
        for actual,dates in zip(captures,config['samples']):
            expected=self.fixture.s.backtest_dates(self.fixture.db,dates=dates,
                **{key:config[key] for key in ('start','end','months')},**config['options'])
            self.assertTrue(compare_results(expected,actual)['exact'])
        with patch.object(provider,'begin',side_effect=AssertionError('No recovered provider')):
            result=random.run(portfolio,config,experiment)['result']
        self.assertEqual(result['execution']['recovered_trials'],2)
        class OtherPythonProvider(PythonExecutor):pass
        other=OtherPythonProvider(self.inputs);self.addCleanup(other.close)
        alternate=NumericalPortfolio(self.inputs,other);self.addCleanup(alternate.close)
        self.assertNotEqual(random.checkpoint_binding(alternate,config)['execution']['provider'],
                            binding['execution']['provider'])
        with patch.dict(provider.stats,threads=7):
            self.assertEqual(random.checkpoint_binding(portfolio,config)['execution']['threads'],7)

    def test_missing_or_corrupt_recovered_row_fails_without_recalculation(self):
        config=self.configuration(2);experiment=self.experiment(config);self.run_parallel(config,experiment)
        replay=experiment.replay_into;calls=0
        def vanished(number,emit):
            nonlocal calls
            calls+=1
            if calls==3:return None
            return replay(number,emit)
        with patch.object(experiment,'replay_into',side_effect=vanished),\
             patch.object(self,'pool',side_effect=AssertionError('No fallback')):
            with self.assertRaisesRegex(ValueError,'disappeared'):self.run_parallel(config,experiment)
        experiment.store.db.execute("UPDATE trials SET sha256='corrupt' WHERE number=2")
        with patch.object(self,'pool',side_effect=AssertionError('No corrupt fallback')):
            with self.assertRaisesRegex(ValueError,'Corrupt'):self.run_parallel(config,experiment)

    def test_progress_capture_save_and_stream_failures_keep_commits_and_close_pool(self):
        for failure in ('progress','capture','save','sink'):
            config=self.configuration(3);experiment=self.experiment(config);pool=self.pool()
            events=[];save=experiment.save_from
            def progress(event):
                events.append(event)
                if failure=='progress' and event['calculated_trials']==1:raise RuntimeError('fictional progress')
            def capture(number,result):
                if failure=='capture':raise RuntimeError('fictional capture')
            def saved(number,view):
                if failure=='save' and experiment.store.measurements()['trials']>=1:raise RuntimeError('fictional save')
                return save(number,view)
            with patch.object(experiment,'save_from',side_effect=saved):
                with self.assertRaisesRegex(RuntimeError,'fictional'):
                    if failure=='sink':
                        writer=result_evidence.Writer(io.BytesIO(),trials=3,metadata={},max_bytes=8*1024**2,piece_bytes=127,record_bytes=16384)
                        with patch.object(writer,'period',side_effect=RuntimeError('fictional sink')):
                            random.run_into(self.workspace,config,experiment,writer,execution=lambda:pool,binding=self.binding(config))
                        self.assertTrue(writer.failed)
                    else:random.run(self.workspace,config,experiment,progress,capture=capture,execution=lambda:pool,binding=self.binding(config))
            self.assertGreaterEqual(experiment.store.measurements()['trials'],1)
            self.assertTrue(pool.closed,pool.closure());self.assertEqual(pool.stats['reserved_slots'],0)

    def test_cancellation_before_lookup_during_save_wait_and_replay(self):
        config=self.configuration(3);experiment=self.experiment(config)
        with patch.object(self.fixture.s.backtest_control,'checkpoint',side_effect=backtest_control.Cancelled),\
             patch.object(experiment,'replay_into',side_effect=AssertionError('No cancelled lookup')):
            with self.assertRaises(backtest_control.Cancelled):self.run_parallel(config,experiment)
        for phase in ('save','wait','replay'):
            experiment=self.experiment(config);pool=self.pool()
            if phase=='save':
                target=patch.object(experiment,'save_from',side_effect=backtest_control.Cancelled)
            elif phase=='wait':
                original=pool._event
                def event(*args):
                    if pool.stats['started_workers']==2:raise backtest_control.Cancelled()
                    return original(*args)
                target=patch.object(pool,'_event',side_effect=event)
            else:
                original=experiment.replay_into
                def replay(number,emit):
                    if experiment.store.measurements()['trials']:raise backtest_control.Cancelled()
                    return original(number,emit)
                target=patch.object(experiment,'replay_into',side_effect=replay)
            with target:
                with self.assertRaises(backtest_control.Cancelled):
                    random.run(self.workspace,config,experiment,execution=lambda:pool,binding=self.binding(config))
            self.assertTrue(pool.closed,pool.closure());self.assertEqual(pool.stats['reserved_slots'],0)


if __name__=='__main__':unittest.main()

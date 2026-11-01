"""Random complete-result parity and replay with fictional owned numerical inputs."""
from copy import deepcopy
from contextlib import closing,ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import test_bench_methods as shared
import test_numerical_generation as generations
from bench_candidates import NumericInputs,PythonExecutor
from bench_candidates_numba import NumbaExecutor
from numerical_portfolios import NumericalPortfolio,compare_results
import numerical_trials as diagnostic
import robustness
import trial_checkpoints

s=shared.s


class NumericalTrialsTests(unittest.TestCase):
    setUp=shared.SharedMethodsTests.setUp

    def evaluator(self, candidate_assembly='compiled'):
        inputs=NumericInputs(self.reader,s);self.addCleanup(inputs.close)
        provider=NumbaExecutor(inputs,limits=dict(threads=2,request_plan=True,candidate_assembly=candidate_assembly))
        self.addCleanup(provider.close)
        portfolio=NumericalPortfolio(inputs,provider);self.addCleanup(portfolio.close)
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        store=trial_checkpoints.Store(Path(folder.name)/'trials.sqlite');self.addCleanup(store.close)
        return inputs,provider,portfolio,store

    def config(self,**options):
        return robustness.plan(self.db,start='2015-01-02',end='2016-12-30',trials=3,seed=42,**options)

    def test_100_annual_source_guard_trials_complete_trailing_and_mixed(self):
        inputs,provider,portfolio,store=self.evaluator('source')
        trailing=[dict(field=name,op='gt',value=0.) for name in ('return_1y','return_3y')]
        observations=[]
        for pool in ('legacy','cached'):
            for filters in (trailing,trailing+[dict(field='pe',op='lt',value=20.)]):
                config=robustness.plan(self.db,start='2015-01-05',end='2016-12-30',months=12,
                    trials=100,seed=42,pool=pool,rank_to=100,metric='ev_ebitda_3y',
                    min_cap=0.,min_ev=0.,filters=filters)
                experiment=store.open(diagnostic.checkpoint_binding(portfolio,config))
                self.assertEqual(experiment.read(),[])
                expected=[];ordinary=robustness.run(self.db,config,workers=1,capture=lambda n,r:expected.append(r))
                captured=[];actual=diagnostic.run(portfolio,config,experiment,capture=lambda n,r:captured.append(r))['result']
                self.assertEqual((actual['completed'],actual['valid'],actual['incomplete']),(100,100,0))
                self.assertEqual(actual['execution']['recovered_trials'],0)
                self.assertEqual(actual['distributions'],ordinary['distributions'])
                self.assertEqual(len(captured),100)
                maximum_absolute=maximum_relative=0.
                for left,right in zip(expected,captured,strict=True):
                    agreement=compare_results(left,right);self.assertTrue(agreement['exact'],agreement)
                    self.assertTrue(all(0<len(p['holdings'])<100 for p in right['periods']))
                    maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                    maximum_relative=max(maximum_relative,agreement['maximum_relative'])
                observations.append(dict(configuration=config,seconds=actual['seconds'],
                    execution=actual['execution'],maximum_absolute=maximum_absolute,
                    maximum_relative=maximum_relative,storage=store.measurements()))
        print(json.dumps(dict(check='100-annual-source-synthetic',scope='2015-2016 five companies; no full-window capacity',
            observations=observations)),flush=True)

    def test_full_month_pool_metric_filter_rank_matrix_and_exact_recovery(self):
        inputs,provider,portfolio,store=self.evaluator();cases=0;holding_occurrences=0
        maximum_absolute=maximum_relative=0.
        for pool in ('legacy','cached'):
            for metric in s.metrics.METRICS:
                for rank_from,rank_to in ((1,100),(2,3)):
                    for filters in ([],[dict(field='pe',op='lt',value=20.)],
                                    [dict(field='return_1y',op='gt',value=0.)]):
                        for months in (1,3,6,12,24):
                            config=self.config(pool=pool,metric=metric,rank_from=rank_from,rank_to=rank_to,
                                min_cap=0.,min_ev=0.,filters=filters,months=months)
                            expected=[];ordinary=robustness.run(self.db,config,capture=lambda n,r:expected.append(r))
                            experiment=store.open(diagnostic.checkpoint_binding(portfolio,config))
                            captured=[]
                            envelope=diagnostic.run(portfolio,config,experiment,capture=lambda n,r:captured.append(r))
                            self.assertEqual(set(envelope),{'diagnostic_version','contract_version','checkpoint_identity','result'})
                            actual=envelope['result']
                            self.assertNotIn('trial_results',actual)
                            self.assertEqual(actual['distributions'],ordinary['distributions'])
                            self.assertEqual((actual['completed'],actual['valid'],actual['incomplete']),
                                             (ordinary['completed'],ordinary['valid'],ordinary['incomplete']))
                            for reference,observed in zip(expected,captured):
                                agreement=compare_results(reference,observed)
                                self.assertTrue(agreement['exact'],(config,agreement))
                                holding_occurrences+=sum(len(p['holdings']) for p in observed['periods'])
                                maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                                maximum_relative=max(maximum_relative,agreement['maximum_relative'])
                            with patch.object(provider,'begin',side_effect=AssertionError('Replay must not begin provider')), \
                                    patch.object(provider,'evaluate',side_effect=AssertionError('Replay must not calculate')), \
                                    patch('numerical_portfolios.stage_book',side_effect=AssertionError('Replay must not stage')):
                                replayed=[]
                                replay=diagnostic.run(portfolio,config,experiment,capture=lambda n,r:replayed.append(r))['result']
                            self.assertEqual(captured,replayed)
                            self.assertEqual(actual['trials'],replay['trials'])
                            self.assertEqual(replay['execution']['recovered_trials'],3)
                            self.assertEqual(replay['execution']['calculated_trials'],0)
                            cases+=1
        self.assertEqual(cases,120)
        self.assertLessEqual(portfolio.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],1)
        print(json.dumps(dict(check='random-complete-result-matrix',cases=cases,trials=cases*3,
            holding_occurrences=holding_occurrences,maximum_absolute=maximum_absolute,
            maximum_relative=maximum_relative,tolerance=1e-12,storage=store.measurements())),flush=True)

    def test_committed_before_capture_and_progress_failure_retry_and_cancel(self):
        inputs,provider,portfolio,store=self.evaluator();config=self.config(months=12)
        experiment=store.open(diagnostic.checkpoint_binding(portfolio,config))
        def capture(number,result):
            self.assertEqual(experiment.load(number),result)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):diagnostic.run(portfolio,config,experiment,capture=capture)
        self.assertIsNotNone(experiment.load(1));self.assertIsNone(experiment.load(2))
        def progress(event):
            if event['completed']==2:
                self.assertIsNotNone(experiment.load(2));raise RuntimeError('fictional progress failure')
        with self.assertRaisesRegex(RuntimeError,'progress'):diagnostic.run(portfolio,config,experiment,progress)
        self.assertIsNotNone(experiment.load(2));self.assertIsNone(experiment.load(3))
        captured=[]
        result=diagnostic.run(portfolio,config,experiment,capture=lambda n,r:captured.append(n))['result']
        self.assertEqual(captured,[1,2,3])
        self.assertEqual(result['execution']['recovered_trials'],2)
        self.assertEqual(result['execution']['calculated_trials'],1)
        with patch.object(s.backtest_control,'checkpoint',side_effect=KeyboardInterrupt), \
                patch.object(experiment,'load',side_effect=AssertionError('Cancel before recovery')):
            with self.assertRaises(KeyboardInterrupt):diagnostic.run(portfolio,config,experiment)

    def test_duplicate_schedules_recorded_dates_invalid_late_trial_and_oversize(self):
        inputs,provider,portfolio,store=self.evaluator();config=self.config(months=12)
        config['samples']=[config['samples'][0][:] for _ in range(3)]
        with patch.object(portfolio.s.schedule_calendar.SessionCalendar,'sample',side_effect=AssertionError('Never resample')):
            experiment=store.open(diagnostic.checkpoint_binding(portfolio,config))
            captured=[];events=[]
            result=diagnostic.run(portfolio,config,experiment,events.append,capture=lambda n,r:captured.append(n))['result']
        self.assertEqual(captured,[1,2,3]);self.assertEqual(result['unique_schedules'],1)
        self.assertEqual([n for n,r in experiment.read()],[1,2,3])
        self.assertEqual([e['completed'] for e in events],[0,1,2,3])
        malformed=deepcopy(config);malformed['samples'][-1]=['2015-01-03']
        with patch.object(experiment,'load',side_effect=AssertionError('Validate all dates before lookup')):
            with self.assertRaises(ValueError):diagnostic.run(portfolio,malformed,experiment)
        store.max_payload_bytes=0
        changed=deepcopy(config);changed['seed']=43
        unretained=store.open(diagnostic.checkpoint_binding(portfolio,changed))
        captures=[]
        outcome=diagnostic.run(portfolio,changed,unretained,capture=lambda n,r:captures.append(r))['result']
        self.assertEqual(outcome['completed'],3);self.assertEqual(len(captures),3)
        self.assertEqual(outcome['execution']['unretained_trials'],3)
        self.assertEqual(unretained.read(),[])

    def test_binding_all_local_sources_versions_provider_options_and_generation(self):
        inputs,provider,portfolio,store=self.evaluator();config=self.config()
        original=diagnostic.checkpoint_binding(portfolio,config)
        sources=diagnostic.source_identity();read_bytes=Path.read_bytes
        for key in sources:
            def modified(path,target=ROOT/key):
                value=read_bytes(path)
                return value+b'\n' if path==target else value
            with patch.object(Path,'read_bytes',modified):
                self.assertNotEqual(diagnostic.source_identity(),sources,key)
        for name in ('numpy','numba','llvmlite'):
            version=diagnostic.version
            with patch.object(diagnostic,'version',side_effect=lambda package,n=name:'changed' if package==n else version(package)):
                self.assertNotEqual(diagnostic.checkpoint_binding(portfolio,config),original)
        for obj,key in ((inputs,'signature'),(inputs.policy,'signature'),(inputs.policy,'field_schema')):
            with patch.object(obj,key,'changed'):
                self.assertNotEqual(diagnostic.checkpoint_binding(portfolio,config),original)
        experiment=store.open(original)
        with patch.dict(provider.limits,{'request_plan':False}):
            with self.assertRaisesRegex(ValueError,'binding'):diagnostic.run(portfolio,config,experiment)
        self.assertNotIn(str(ROOT),trial_checkpoints.canonical(original))
        self.assertTrue({'scripts/metrics.py','scripts/portfolio_results.py','scripts/robustness.py',
            'scripts/schedule_calendar.py','scripts/research.py','scripts/numerical_policy.py',
            'scripts/numerical_trial.py','scripts/result_evidence.py',
            'tools/bench_candidates_numba.py','tools/portfolio_workspace.py'} <= sources.keys())

    def test_consumer_rejects_noncontiguous_and_missing_results(self):
        inputs,provider,portfolio,store=self.evaluator();config=self.config()
        result=portfolio.backtest_dates(dates=config['samples'][0],start=config['start'],end=config['end'])['result']
        for stream in ([],[(2,result,{})],[(1,result,{}),(1,result,{})],
                       [(1,result,{}),(2,result,{})],[(True,result,{})]):
            with self.assertRaises(ValueError):robustness.consume_trials(config,iter(stream))

    def test_durable_snapshots_reopen_and_export_after_generation_replacement_and_eviction(self):
        import backtest_jobs
        import backtest_queue
        import saved_backtests

        inputs,provider,portfolio,store=self.evaluator()
        config=self.config(months=12,rank_to=3,metric='ev_ebitda',pool='cached')
        binding=diagnostic.checkpoint_binding(portfolio,config);experiment=store.open(binding)
        trials=[]
        result=diagnostic.run(portfolio,config,experiment,capture=lambda n,r:trials.append(r))['result']
        result['trial_results']=trials
        self.assertTrue(all(period['holdings'] for trial in trials for period in trial['periods']))
        folder=Path(self.root)/'durable-evidence';folder.mkdir()
        library_path=folder/'saved-backtests.sqlite';queue_path=folder/'backtest-queue.sqlite'
        library=saved_backtests.Store(library_path);queue=backtest_queue.Store(queue_path)
        options=dict(start=config['start'],end=config['end'],months=config['months'],
                     trials=config['requested'],seed=config['seed'],**config['options'])
        catalog=dict(metrics={'ev_ebitda':dict(label='Original saved metric')},
                     filters={'pe':dict(label='Original saved P/E')})
        presentation=dict(coverage='Original saved coverage',notice=dict(text='Original saved warning',severity='warning'),
                          rangeNote='Original saved window',periodLabel='Original saved periods')
        modern=dict(version=2,kind='random',settings=dict(mode='random',**options),result=result,
                    catalog=catalog,presentation=presentation,captured_at='2026-10-27T00:00:00Z')
        legacy=deepcopy(modern);legacy['version']=1;legacy.pop('presentation')
        legacy['context']=dict(notes=[['screen-coverage',presentation['coverage'],'hint'],
            ['screen-status',presentation['notice']['text'],'screen-message warning'],
            ['range-note',presentation['rangeNote'],'hint']],pill=presentation['periodLabel'])
        saved_records=[library.save('Original library v1',legacy),library.save('Original library v2',modern)]
        submission=dict(id='1'*32,name='Original queue submission',mode='random',options=options,
                        catalog=catalog,presentation=presentation)
        item=queue.enqueue(submission)
        held=queue.change(item['id'],'hold',dict(revision=item['revision'],edit_id='2'*32))
        edit=dict(edit_id=held['edit']['id'],edit_revision=held['edit']['revision'],
                  **{key:value for key,value in submission.items() if key!='id'})
        edit['name']='Original completed queue name'
        saved_edit=queue.change(item['id'],'update',edit)
        self.assertEqual(saved_edit['edit']['state'],'saved')
        self.assertEqual(queue.claim()['id'],item['id'])
        queue.progress(item['id'],'configuration',config)
        saved_backtests.validate(modern)
        queue.finish(item['id'],'complete',snapshot=modern)

        before=[library.get(row['id']) for row in saved_records]+[queue.get(item['id'])]
        def raw_rows():
            with closing(sqlite3.connect(library_path)) as db:
                library_rows=db.execute('SELECT * FROM records ORDER BY id').fetchall()
            with closing(sqlite3.connect(queue_path)) as db:
                queue_rows=db.execute('SELECT * FROM jobs ORDER BY id').fetchall()
                edit_rows=db.execute('SELECT * FROM edits ORDER BY job_id').fetchall()
            return library_rows,queue_rows,edit_rows
        originals=raw_rows()
        self.assertEqual(json.loads(originals[1][0][-1]),config,'The queue retains the exact sampled date plan.')

        # Replace actual fictional price inputs and attach a newly built numeric
        # generation. This changes financial results as well as its identity.
        with self.db:
            self.db.execute("UPDATE prices SET adjusted=adjusted*1.1 WHERE day>='2016-01-04'")
        replacement=NumericInputs(self.reader,s);self.addCleanup(replacement.close)
        self.assertNotEqual(replacement.signature,inputs.signature)
        replacement_provider=NumbaExecutor(replacement,limits=deepcopy(provider.limits))
        self.addCleanup(replacement_provider.close)
        replacement_portfolio=NumericalPortfolio(replacement,replacement_provider)
        self.addCleanup(replacement_portfolio.close)
        replacement_binding=diagnostic.checkpoint_binding(replacement_portfolio,config)
        self.assertNotEqual(replacement_binding['generation'],binding['generation'])
        replacement_experiment=store.open(replacement_binding)
        self.assertIsNone(replacement_experiment.load(1))
        store.max_experiments=1
        changed=diagnostic.run(replacement_portfolio,config,replacement_experiment)['result']
        self.assertNotEqual(changed['distributions'],result['distributions'])
        self.assertGreater(changed['execution']['evicted_experiments'],0)
        self.assertEqual(experiment.read(),[])
        self.assertEqual(store.measurements()['experiments'],1)

        # Reopening durable evidence must work even if every calculation and
        # checkpoint entry point is unavailable. Neither store may revalidate
        # old results against the new financial generation.
        with ExitStack() as guards:
            for owner,name in ((diagnostic,'run'),(s,'backtest_dates'),(s,'backtest'),
                    (robustness,'plan'),(robustness,'run'),(backtest_jobs,'calculate'),
                    (trial_checkpoints.Experiment,'load'),(trial_checkpoints.Store,'open')):
                guards.enter_context(patch.object(owner,name,side_effect=AssertionError('Stored snapshots must not calculate')))
            reopened=saved_backtests.Store(library_path);reopened_queue=backtest_queue.Store(queue_path)
            after=[reopened.get(row['id']) for row in saved_records]+[reopened_queue.get(item['id'])]
            self.assertEqual(after,before)
            self.assertEqual(reopened_queue.change(item['id'],'update',edit),
                             {key:value for key,value in after[-1].items() if key!='snapshot'})
            self.assertEqual(reopened_queue.enqueue(submission)['state'],'complete')
            self.assertEqual(reopened_queue.claim(),None)
            self.assertEqual(raw_rows(),originals,'Opening and exact retries preserve compressed snapshots and receipts.')
            exported=subprocess.run(['node',str(ROOT/'tests/check-checkpoint-snapshots.cjs')],
                input=json.dumps(dict(before=before,after=after,presentation=presentation)),
                text=True,capture_output=True,timeout=30)
            self.assertEqual(exported.returncode,0,exported.stdout+'\n'+exported.stderr)
            print(exported.stdout.strip(),flush=True)


class CurrentAttachmentTests(unittest.TestCase):
    def test_freshness_checked_before_full_checkpoint_recovery(self):
        fixture=generations.GenerationTests('test_export_values_order_missingness_and_mutable_books_reuse')
        fixture.setUp();self.addCleanup(fixture.doCleanups);fixture.prepare();inputs=fixture.attach()
        self.addCleanup(inputs.close)
        provider=NumbaExecutor(inputs,limits=dict(threads=2,request_plan=True,candidate_assembly='compiled'))
        self.addCleanup(provider.close)
        portfolio=NumericalPortfolio(inputs,provider);self.addCleanup(portfolio.close)
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        store=trial_checkpoints.Store(Path(folder.name)/'trials.sqlite');self.addCleanup(store.close)
        config=robustness.plan(fixture.db,start='2015-01-02',end='2016-12-30',trials=2,seed=42)
        experiment=store.open(diagnostic.checkpoint_binding(portfolio,config))
        diagnostic.run(portfolio,config,experiment)
        fixture.binding['prices']={'fictional_revision':1}
        with patch.object(experiment,'load',side_effect=AssertionError('Freshness before recovery')):
            with self.assertRaisesRegex(ValueError,'stale'):diagnostic.run(portfolio,config,experiment)
        fixture.binding['prices']={}


if __name__=='__main__':unittest.main()

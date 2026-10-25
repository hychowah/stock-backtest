"""Complete portfolio parity and containment for the common candidate adapter."""
from contextlib import closing, ExitStack, nullcontext
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sqlite3
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import test_bench_methods as shared
from bench_candidates import NumericInputs, PythonExecutor
import bench_candidates_run as runner
from bench_candidates_process import OwnedProcess


class CandidateRequestTests(unittest.TestCase):
    def setUp(self):
        self.fixture=shared.SharedMethodsTests('test_empty_trials_remain_visible_and_excluded_from_distributions')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.inputs=NumericInputs(self.fixture.reader,shared.s)
        self.addCleanup(self.inputs.close)
        self.executor=PythonExecutor(self.inputs,limits=dict(capture=False))
        self.addCleanup(self.executor.close)

    def test_batched_requests_preserve_complete_source_evidence_and_replay(self):
        for pool in ('legacy','cached'):
            for profile in ('F0','F1','F2'):
                for metric in shared.s.metrics.METRICS:
                    config=self.fixture.configuration(pool,profile,metric=metric)
                    reference,summary=self.fixture.reference(config)
                    counts={}
                    for staging in runner.STAGING:
                        with self.subTest(pool=pool,profile=profile,metric=metric,staging=staging):
                            path=self.fixture.root/f'{pool}-{profile}-{metric}-{staging}.sqlite'
                            freshness=Mock()
                            actual=dict.fromkeys(('snapshots','screening_metrics','filter_values'),0)
                            original=runner.stage_book
                            def observed(db,book,pool,**kwargs):
                                result=original(db,book,pool,**kwargs)
                                for table in actual:
                                    actual[table]+=db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                                return result
                            with patch.object(runner,'stage_book',side_effect=observed), \
                                    patch.object(self.executor,'evaluate',wraps=self.executor.evaluate) as evaluate:
                                measured,picks=runner.run_candidate(self.inputs,self.executor,config,
                                    self.fixture.reader,path,freshness=freshness,budget_seconds=10.,staging=staging)
                            freshness.assert_called_once_with()
                            self.assertTrue(shared.baseline.compare(reference,picks)['exact'])
                            self.assertTrue(shared.baseline.compare(summary,measured['summary'])['exact'])
                            self.assertTrue(shared.baseline.compare(picks,shared.methods.replay(path))['exact'])
                            self.assertEqual(measured['committed_trials'],3)
                            self.assertTrue(any(len(call.args[0])>1 for call in evaluate.call_args_list))
                            self.assertEqual(measured['staging'],staging)
                            self.assertEqual(measured['staged_rows'],actual)
                            self.assertGreater(actual['snapshots'],0)
                            self.assertEqual(actual['filter_values']>0,profile!='F0')
                            with closing(sqlite3.connect(path)) as store:
                                binding=json.loads(store.execute('SELECT value FROM binding').fetchone()[0])
                            self.assertEqual(binding['identity']['staging'],staging)
                            counts[staging]=actual
                    self.assertEqual(counts['all']['snapshots'],counts['requested']['snapshots'])
                    self.assertEqual(counts['all']['filter_values'],counts['requested']['filter_values'])
                    self.assertGreater(counts['all']['screening_metrics'],counts['requested']['screening_metrics'])

    def test_interruption_keeps_only_completed_trials_and_fresh_retry_works(self):
        config=self.fixture.configuration()
        reference,_=self.fixture.reference(config)
        def stop(event):
            if event['completed']==1:
                raise RuntimeError('Stop after one durable trial')
        for staging in runner.STAGING:
            path=self.fixture.root/f'batch-interrupted-{staging}.sqlite'
            with self.assertRaisesRegex(RuntimeError,'one durable trial'):
                runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,path,
                    freshness=lambda:None,budget_seconds=10.,progress=stop,staging=staging)
            self.assertTrue(shared.baseline.compare(reference[:1],shared.methods.replay(path))['exact'])
            self.assertEqual(self.executor.last_request['committed_trials'],1)
            self.assertEqual(self.executor.last_request['staging'],staging)
            self.assertGreater(self.executor.last_request['staged_rows']['snapshots'],0)
            _,retry=runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,
                self.fixture.root/f'batch-retry-{staging}.sqlite',freshness=lambda:None,
                budget_seconds=10.,staging=staging)
            self.assertTrue(shared.baseline.compare(reference,retry)['exact'])

    def test_real_filter_fixture_definitions_are_separate_from_primary_manifest(self):
        records=runner.smoke_requests(self.fixture.db,end='2016-12-30')
        self.assertEqual(len(records),6)
        self.assertEqual({row['configuration']['options']['pool'] for row in records},{'legacy','cached'})
        self.assertTrue(all(row['configuration']['requested']==2 for row in records))
        mixed=[row for row in records if row['id'].endswith('mixed')]
        self.assertTrue(all(row['configuration']['options']['metric']=='ev_ebitda_3y' for row in mixed))

    def test_existing_result_store_is_preserved_on_rejected_fresh_request(self):
        config=self.fixture.configuration()
        path=self.fixture.root/'existing.sqlite'
        path.write_bytes(b'preserve existing evidence')
        with self.assertRaisesRegex(ValueError,'new result store'):
            runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,path,
                freshness=lambda:None,budget_seconds=10.)
        self.assertEqual(path.read_bytes(),b'preserve existing evidence')

    def test_staging_projection_preserves_selection_missing_pairs_and_complete_books(self):
        for pool in ('legacy','cached'):
            self.executor.begin(dict(options=shared.baseline.options(pool,'F0')))
            original=self.executor.evaluate([('2015-01-02','2016-01-04',pool)],
                shared.baseline.options(pool,'F0'))[0]
            for metric in shared.s.metrics.METRICS:
                for missing in ('none','one','all'):
                    book=deepcopy(original)
                    if missing!='none':
                        book['metrics']=[row for row in book['metrics']
                            if not (row[1]==metric and (missing=='all' or row[0]=='A'))]
                    preserved=deepcopy(book)
                    with closing(runner.memory_workspace(self.fixture.reader,shared.s)) as complete, \
                            closing(runner.memory_workspace(self.fixture.reader,shared.s)) as projected:
                        for db in (complete,projected):
                            db.execute("UPDATE companies SET sector='Technology',exchange='Nasdaq' WHERE symbol='A'")
                        counts=dict.fromkeys(('snapshots','screening_metrics','filter_values'),0)
                        self.assertEqual(runner.stage_book(complete,book,pool),1)
                        self.assertEqual(runner.stage_book(projected,book,pool,
                            ranking_metric=metric,staged_rows=counts),1)
                        for table,count in counts.items():
                            self.assertEqual(count,projected.execute('SELECT COUNT(*) FROM '+table).fetchone()[0])
                        self.assertEqual(counts['snapshots'],len(book['snapshots']))
                        self.assertEqual(counts['screening_metrics'],sum(row[1]==metric for row in book['metrics']))
                        changes=({},dict(rank_from=2,rank_to=3),dict(min_cap=130e6,max_cap=180e6),
                            dict(min_ev=150e6,min_yield=.1,max_multiple=10.),
                            dict(sector='Technology',exchange='Nasdaq'),dict(sector='__MISSING__'),
                            dict(rank_from=100,rank_to=110),dict(min_cap=1e100))
                        for extra in changes:
                            options=dict(dict(period=(1,1),pool=pool,metric=metric,min_cap=0.,min_ev=0.),**extra)
                            selected=shared.s.r._select(complete,**options)
                            self.assertEqual(selected,shared.s.r._select(projected,**options))
                            if missing=='all':self.assertEqual(selected,[])
                            if missing=='one':self.assertNotIn('A',{row['symbol'] for row in selected})
                        self.assertEqual(book,preserved)
                        runner.stage_book(projected,book,pool,ranking_metric='invalid')
                        with self.assertRaisesRegex(ValueError,'valid ranking metric'):
                            shared.s.r._select(projected,period=(1,1),metric='invalid')

    def test_projection_does_not_hide_malformed_pairs_or_changed_book_identity(self):
        self.executor.begin(dict(options=shared.baseline.options('legacy','F0')))
        book=self.executor.evaluate([('2015-01-02','2016-01-04','legacy')])[0]
        book['metrics'].append(('A','unused',1.))
        with closing(runner.memory_workspace(self.fixture.reader,shared.s)) as db:
            for metric in (None,'ev_ebitda'):
                with self.assertRaises(ValueError):
                    runner.stage_book(db,book,'legacy',ranking_metric=metric)
        evaluate=self.executor.evaluate
        def changed(*args,**kwargs):
            books=evaluate(*args,**kwargs)
            books[0]['pool']='changed'
            return books
        for staging in runner.STAGING:
            with patch.object(self.executor,'evaluate',side_effect=changed):
                with self.assertRaisesRegex(ValueError,'book identity'):
                    runner.run_candidate(self.inputs,self.executor,self.fixture.configuration(),
                        self.fixture.reader,self.fixture.root/f'changed-{staging}.sqlite',
                        freshness=lambda:None,budget_seconds=10.,staging=staging)

    def test_request_default_is_complete_and_invalid_variant_fails(self):
        self.assertEqual(runner.parser().parse_args(['--runtime','runtime','--workdir','work']).staging,'all')
        for staging in runner.STAGING:
            self.assertEqual(runner.parser().parse_args([
                '--runtime','runtime','--workdir','work','--staging',staging]).staging,staging)
        config=self.fixture.configuration()
        measured,_=runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,
            self.fixture.root/'default-staging.sqlite',freshness=lambda:None,budget_seconds=10.)
        self.assertEqual(measured['staging'],'all')
        with self.assertRaisesRegex(ValueError,'all or requested'):
            runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,
                self.fixture.root/'invalid-staging.sqlite',freshness=lambda:None,
                budget_seconds=10.,staging='invalid')

    def test_worker_uses_frozen_staging_in_report_and_durable_binding(self):
        config=self.fixture.configuration('cached','F2',metric='ev_ebitda_3y')
        reference,summary=self.fixture.reference(config)
        runtime=self.fixture.root/'runtime'
        (runtime/'data').mkdir(parents=True)
        shutil.copyfile(self.fixture.path,runtime/'data/schedules.sqlite')
        for staging in runner.STAGING:
            workdir=self.fixture.root/('worker-'+staging)
            workdir.mkdir()
            reference_file=workdir/'reference.json'
            shared.baseline.publish(reference_file,reference)
            specification=workdir/'specification.json'
            shared.baseline.publish(specification,dict(staging=staging,
                source_hashes=runner.hashes(runner.source_files()),input_identity_sha256='fixture',
                request_budget=10.,smoke_budget=10.,requests=[dict(id='fixture',kind='untimed_correctness',
                    configuration=config,evidence_file=str(reference_file),summary=summary)]))
            args=SimpleNamespace(worker='python',runtime=runtime,workdir=workdir,
                specification=specification,result=workdir/'result.json',staging=staging)
            with patch.object(runner.sys,'stdin',io.StringIO('GO\n')), \
                    patch.dict(os.environ),patch.object(runner.baseline,'bootstrap'), \
                    patch.object(runner,'intermediate_proof',return_value=dict(comparison=dict(exact=True))), \
                    patch.object(runner,'emit'):
                runner.worker(args)
            report=shared.baseline.load(args.result)
            self.assertEqual(report['status'],'complete')
            self.assertTrue(report['financial_agreement'])
            self.assertEqual(report['staging'],staging)
            case=report['cases'][0]
            self.assertEqual(case['staging'],staging)
            self.assertEqual(case['correctness']['staging'],staging)
            self.assertGreater(case['correctness']['staged_rows']['snapshots'],0)
            with closing(sqlite3.connect(workdir/case['result_store_file'])) as store:
                identity=json.loads(store.execute('SELECT value FROM binding').fetchone()[0])['identity']
            self.assertEqual(identity['staging'],staging)
            self.assertTrue(case['comparison']['exact'])
            self.assertTrue(case['summary_comparison']['exact'])
            self.assertTrue(case['replay_comparison']['exact'])

    def test_parent_freezes_variant_before_launch_and_records_it(self):
        config=self.fixture.configuration()
        reference,summary=self.fixture.reference(config)
        case=dict(id='fixture')
        def connect(*args,**kwargs):
            db=sqlite3.connect(self.fixture.path)
            db.row_factory=sqlite3.Row
            return db
        for staging in runner.STAGING:
            args=runner.parser().parse_args(['--runtime',str(self.fixture.root),
                '--workdir',str(self.fixture.root/('parent-'+staging)),
                '--methods','numba','--staging',staging,'--case','fixture'])
            def isolated(arguments,method,specification,result):
                frozen=shared.baseline.load(specification)
                self.assertEqual(frozen['staging'],staging)
                self.assertEqual(arguments.staging,staging)
                return dict(staging=staging,cases=[dict(id='fixture',kind='primary',status='matched',
                    measurement=dict(wall_seconds=1.))])
            with ExitStack() as stack:
                stack.enter_context(patch.object(runner,'os',SimpleNamespace(name='nt',environ=os.environ)))
                stack.enter_context(patch.dict(os.environ))
                stack.enter_context(patch.object(runner.baseline,'bootstrap'))
                stack.enter_context(patch.object(runner.baseline,'assert_workdir'))
                stack.enter_context(patch.object(runner.baseline,'load',wraps=shared.baseline.load))
                stack.enter_context(patch.object(runner.baseline,'validate_manifest'))
                stack.enter_context(patch.object(runner.baseline,'identity',return_value=dict(fixture=True)))
                stack.enter_context(patch.object(runner.baseline,'configuration',return_value=config))
                stack.enter_context(patch.object(runner.baseline,'request',return_value=(
                    dict(summary=summary,wall_seconds=2.),reference)))
                stack.enter_context(patch.object(runner.baseline.coordinator,'access',return_value=nullcontext()))
                stack.enter_context(patch.object(shared.s.r,'connect',side_effect=connect))
                stack.enter_context(patch.object(shared.s,'connect',side_effect=connect))
                stack.enter_context(patch.object(runner,'smoke_requests',return_value=[]))
                stack.enter_context(patch.object(runner,'reference_smokes',return_value=[]))
                stack.enter_context(patch.object(runner,'run_isolated',side_effect=isolated))
                stack.enter_context(patch.object(runner,'emit'))
                args.manifest=self.fixture.root/'manifest.json'
                shared.baseline.publish(args.manifest,dict(primary_cases=[case],sha256='fixture'))
                runner.parent(args)
            report=shared.baseline.load(args.workdir/'comparison.json')
            self.assertEqual(report['staging'],staging)
            self.assertEqual(report['runs'][0]['staging'],staging)


class PlannedCandidateRequestTests(CandidateRequestTests):
    def setUp(self):
        super().setUp()
        self.executor.limits['request_plan'] = True

    def test_rank_slice_three_year_and_empty_requests_preserve_source_and_replay(self):
        for pool in ('legacy', 'cached'):
            for label, changes in (('slice', dict(rank_from=2, rank_to=100, metric='ev_ebitda_3y')),
                                   ('metadata', dict(sector='Energy',exchange='NYSE',
                                       max_cap=180e6,min_ev=100e6,max_multiple=10.,min_yield=.1)),
                                   ('empty', dict(min_cap=1e100))):
                config = self.fixture.configuration(pool, **changes)
                reference, summary = self.fixture.reference(config)
                for staging in runner.STAGING:
                    path = self.fixture.root / (pool + '-' + label + '-' + staging + '.sqlite')
                    measured, picks = runner.run_candidate(self.inputs, self.executor,
                        config, self.fixture.reader, path, freshness=lambda: None,
                        budget_seconds=10.,staging=staging)
                    self.assertTrue(shared.baseline.compare(reference, picks)['exact'])
                    self.assertTrue(shared.baseline.compare(summary, measured['summary'])['exact'])
                    self.assertTrue(shared.baseline.compare(picks, shared.methods.replay(path))['exact'])

    def test_request_plan_keeps_repeated_books_and_omits_only_unused_lookups(self):
        config = self.fixture.configuration()
        config['samples'][1] = list(config['samples'][0])
        self.executor.begin(config)
        plan = self.executor.request_plan
        self.executor.evaluate(plan.books)
        self.assertGreater(len(plan.books), len(set(plan.books)))
        self.assertEqual(plan.slots, (0, 1, 3))
        self.assertEqual(self.executor.stats['planned_lookup_slots'], [0, 1, 3])
        self.assertLessEqual(self.executor.stats['price_queries'],
                             self.executor.stats['candidate_rows'] * 4)

    def test_extended_real_checks_keep_all_profiles_and_add_slice_and_empty(self):
        records = runner.smoke_requests(self.fixture.db, end='2016-12-30', extended=True)
        self.assertEqual(len(records), 10)
        self.assertEqual(sum(row['id'].endswith('empty') for row in records), 2)
        self.assertEqual(sum(row['id'].endswith('rank-slice') for row in records), 2)

    def test_lookup_requirements_follow_the_policy_expression_dependencies(self):
        options = dict(shared.baseline.options('legacy', 'F0'),
                       filters=[dict(field='pe', op='gt', value=0.)])
        with patch.dict(self.inputs.policy.expression_map,
                        filter_pe=('input', 'trailing_3y')):
            self.executor.begin(dict(options=options))
            self.assertIn(6, self.executor.request_plan.slots)
        options['filters'] = [dict(field='return_1y', op='gt', value=0.)]
        with patch.dict(self.inputs.policy.expression_map,
                        filter_return_1y=('const', 2.)):
            self.executor.begin(dict(options=options))
            self.assertEqual(self.executor.request_plan.slots, (0, 1, 3))


class ProcessContainmentTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)

    def process(self,hang):
        script=self.root/'owned.py'
        database=self.root/'evidence.sqlite'
        script.write_text('''import json,sqlite3,subprocess,sys,time
print(json.dumps(dict(event='worker_ready')),flush=True)
assert input()=='GO'
db=sqlite3.connect(sys.argv[1])
db.execute('CREATE TABLE trials(number INTEGER PRIMARY KEY)')
db.execute('INSERT INTO trials VALUES(1)');db.commit();db.close()
if sys.argv[2]=='hang':
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    print(json.dumps(dict(event='committed',child=child.pid)),flush=True)
    time.sleep(60)
else:
    print(json.dumps(dict(event='committed')),flush=True)
''')
        return OwnedProcess([sys.executable,str(script),str(database),'hang' if hang else 'exit']),database

    def wait_event(self,owned,name):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            event=owned.event()
            if event and event.get('event')==name:
                return event
        self.fail('Owned child did not emit '+name)

    def test_owned_timeout_closes_descendants_and_preserves_committed_sqlite(self):
        owned,database=self.process(True)
        with owned:
            self.wait_event(owned,'worker_ready')
            owned.start()
            self.wait_event(owned,'committed')
            owned.terminate()
        self.assertIsNotNone(owned.process.returncode)
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute('SELECT * FROM trials').fetchall(),[(1,)])
            db.execute('INSERT INTO trials VALUES(2)');db.commit()

    def test_normal_completion_waits_for_owned_process_and_closes_pipes(self):
        owned,database=self.process(False)
        with owned:
            self.wait_event(owned,'worker_ready')
            owned.start()
            self.wait_event(owned,'committed')
        self.assertEqual(owned.process.returncode,0)
        self.assertTrue(owned.process.stdout.closed)

    def test_parent_hard_timeout_collects_committed_prefix_after_group_closure(self):
        case='legacy-F0-42'
        expected=[dict(value=1.)]
        reference=self.root/'reference.json';reference.write_text(json.dumps(expected))
        specification=self.root/'specification.json'
        specification.write_text(json.dumps(dict(staging='requested',requests=[dict(id=case,evidence_file=str(reference))])))
        result=self.root/'result.json'
        result.write_text(json.dumps(dict(method='python',cases=[dict(id=case,kind='primary',status='running')])))
        store=self.root/('python-'+case+'.sqlite')
        with closing(sqlite3.connect(store)) as db:
            db.execute('CREATE TABLE trials(number INTEGER PRIMARY KEY,evidence TEXT)')
            db.execute('INSERT INTO trials VALUES(1,?)',(json.dumps(expected[0]),));db.commit()
        class FakeOwned:
            def __init__(self,*args,**kwargs):
                self.process=SimpleNamespace(wait=lambda timeout:1)
                self.events=iter([dict(event='worker_ready'),dict(event='request_start',case=case,kind='primary')])
                self.closed=False
            def __enter__(self):return self
            def __exit__(self,*args):self.closed=True
            def event(self,timeout):return next(self.events,{})
            def start(self):pass
            def terminate(self):pass
        owned=FakeOwned()
        args=SimpleNamespace(runtime=self.root,workdir=self.root,setup_budget=1.,
                             request_budget=1.,smoke_budget=1.,staging='requested')
        with patch('bench_candidates_process.OwnedProcess',return_value=owned) as spawn, \
                patch.object(runner.time,'monotonic',side_effect=[0.,0.,0.,0.,100.]):
            report=runner.run_isolated(args,'python',specification,result)
        command=spawn.call_args.args[0]
        self.assertEqual(command[command.index('--staging')+1],'requested')
        self.assertTrue(owned.closed)
        self.assertEqual(report['status'],'incomplete')
        self.assertTrue(report['owned_descendants_closed'])
        self.assertEqual(report['cases'][0]['status'],'hard_timeout')
        self.assertEqual(report['cases'][0]['committed_trials'],1)
        self.assertTrue(report['cases'][0]['partial_comparison']['exact'])


if __name__=='__main__':
    unittest.main()

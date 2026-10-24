"""Complete portfolio parity and containment for the common candidate adapter."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
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
                config=self.fixture.configuration(pool,profile)
                reference,summary=self.fixture.reference(config)
                path=self.fixture.root/f'{pool}-{profile}-batch.sqlite'
                freshness=Mock()
                evaluate=Mock(wraps=self.executor.evaluate)
                self.executor.evaluate=evaluate
                measured,picks=runner.run_candidate(self.inputs,self.executor,config,
                    self.fixture.reader,path,freshness=freshness,budget_seconds=10.)
                freshness.assert_called_once_with()
                self.assertTrue(shared.baseline.compare(reference,picks)['exact'])
                self.assertTrue(shared.baseline.compare(summary,measured['summary'])['exact'])
                self.assertTrue(shared.baseline.compare(picks,shared.methods.replay(path))['exact'])
                self.assertEqual(measured['committed_trials'],3)
                self.assertTrue(any(len(call.args[0])>1 for call in evaluate.call_args_list))
                self.executor.evaluate=evaluate._mock_wraps

    def test_interruption_keeps_only_completed_trials_and_fresh_retry_works(self):
        config=self.fixture.configuration()
        reference,_=self.fixture.reference(config)
        path=self.fixture.root/'batch-interrupted.sqlite'
        def stop(event):
            if event['completed']==1:
                raise RuntimeError('Stop after one durable trial')
        with self.assertRaisesRegex(RuntimeError,'one durable trial'):
            runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,path,
                freshness=lambda:None,budget_seconds=10.,progress=stop)
        self.assertTrue(shared.baseline.compare(reference[:1],shared.methods.replay(path))['exact'])
        self.assertEqual(self.executor.last_request['committed_trials'],1)
        _,retry=runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,
            self.fixture.root/'batch-retry.sqlite',freshness=lambda:None,budget_seconds=10.)
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


class PlannedCandidateRequestTests(CandidateRequestTests):
    def setUp(self):
        super().setUp()
        self.executor.limits['request_plan'] = True

    def test_rank_slice_three_year_and_empty_requests_preserve_source_and_replay(self):
        for pool in ('legacy', 'cached'):
            for label, changes in (('slice', dict(rank_from=2, rank_to=100, metric='ev_ebitda_3y')),
                                   ('empty', dict(min_cap=1e100))):
                config = self.fixture.configuration(pool, **changes)
                reference, summary = self.fixture.reference(config)
                path = self.fixture.root / (pool + '-' + label + '.sqlite')
                measured, picks = runner.run_candidate(self.inputs, self.executor,
                    config, self.fixture.reader, path, freshness=lambda: None, budget_seconds=10.)
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
        specification.write_text(json.dumps(dict(requests=[dict(id=case,evidence_file=str(reference))])))
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
                             request_budget=1.,smoke_budget=1.)
        with patch('bench_candidates_process.OwnedProcess',return_value=owned), \
                patch.object(runner.time,'monotonic',side_effect=[0.,0.,0.,0.,100.]):
            report=runner.run_isolated(args,'python',specification,result)
        self.assertTrue(owned.closed)
        self.assertEqual(report['status'],'incomplete')
        self.assertTrue(report['owned_descendants_closed'])
        self.assertEqual(report['cases'][0]['status'],'hard_timeout')
        self.assertEqual(report['cases'][0]['committed_trials'],1)
        self.assertTrue(report['cases'][0]['partial_comparison']['exact'])


if __name__=='__main__':
    unittest.main()

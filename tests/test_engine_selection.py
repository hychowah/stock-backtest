"""Pinned application engines, optional setup and immutable producer evidence."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.inputs import daily
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'scripts'),str(ROOT/'website')]
import backtest_jobs
import backtest_queue
import engine_selection
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.application import preparation as numerical_preparation
import test_calculations as calculations
from test_queue import request


class SelectionTests(unittest.TestCase):
    setUp=calculations.CalculationTests.setUp

    def selectable(self):
        preparation=Mock();preparation.status.return_value=dict(state='unavailable')
        owner=engine_selection.Selectable(preparation)
        self.addCleanup(owner.retire);self.addCleanup(owner.close)
        return owner

    def test_original_is_independent_and_known_producer_is_result_evidence(self):
        owner=self.selectable()
        with patch.object(numerical_preparation,'dependencies',side_effect=numerical_preparation.PreparationError('dependencies unavailable')):
            expected=self.service.calculate('custom',self.options,None,None)
            actual=owner.calculate('custom',dict(self.options,engine='original'),None,None)
            self.assertEqual(actual.pop('producer'),dict(engine='original',label='Original'))
            self.assertEqual(calculations.financial_result(actual),calculations.financial_result(expected))
            self.assertTrue(owner.ready_for({}));self.assertFalse(owner.ready_for({'engine':'experimental'}))
            self.assertEqual(owner.queue_engines(),{'original'})
            with self.assertRaises(backtest_jobs.Unavailable):owner.calculate('custom',dict(self.options,engine='experimental'),None,None)
        owner.preparation._runtime.assert_not_called()

    def test_engine_policy_and_recorded_plan_checked_before_dispatch(self):
        owner=self.selectable()
        for engine in (None,1,False,'unknown'):
            with self.assertRaises(ValueError):owner.preflight(dict(self.options,engine=engine))
        calendar=dict(version=1,start=self.options['start'],end=self.options['end'],interval=dict(unit='month',count=3))
        self.assertEqual(owner.preflight(dict(calendar=calendar)),'original')
        self.assertEqual(owner.preflight(dict(calendar=calendar,engine='experimental')),'experimental')
        spread=dict(self.options,filters=[dict(field='operating_yield_spread_3y',op='gt',value=5)])
        self.assertEqual(owner.preflight(spread),'original')
        self.assertEqual(owner.preflight(dict(spread,engine='experimental')),'experimental')
        with self.assertRaisesRegex(ValueError,'Invalid recorded random plan'):
            owner.preflight(self.options,planned={})
        random=dict(self.options,trials=2,seed=42)
        plans=[];owner.calculate('random',random,None,plans.append)
        before=deepcopy(plans[0])
        owner.calculate('random',dict(random,engine='original',selection_order='filter_first'),None,None,planned=plans[0])
        self.assertEqual(plans[0],before)
        with self.assertRaisesRegex(ValueError,'differ'):
            owner.calculate('random',dict(random,selection_order='rank_first'),None,None,planned=plans[0])

    def test_manual_identity_and_queue_receipts_keep_engine_and_plan(self):
        owner=self.selectable();jobs=backtest_jobs.Jobs(owner);self.addCleanup(jobs.close)
        options=dict(self.options,engine='original')
        jobs.start('a'*32,'custom',options);jobs.runs['a'*32]['thread'].join(5)
        value=jobs.snapshot('a'*32);self.assertEqual(value['engine'],'original')
        self.assertEqual(value['result']['producer']['engine'],'original')
        with self.assertRaisesRegex(ValueError,'different settings'):jobs.start('a'*32,'custom',dict(options,engine='experimental'))
        store=backtest_queue.Store(self.root/'queue.sqlite')
        submission=request(mode='random',options=dict(self.options,engine='experimental',seed=42,trials=2))
        item=store.enqueue(submission)
        with self.assertRaises(backtest_queue.Conflict):store.enqueue(dict(submission,options=dict(submission['options'],engine='original')))
        job=store.claim();plan={'options':self.options,'seed':42,'requested':2,'start':self.options['start'],'end':self.options['end'],'months':3,'samples':[['2015-01-02']]}
        store.progress(item['id'],'configuration',plan);store.recover()
        reopened=backtest_queue.Store(store.path)
        self.assertEqual(reopened.claim()['plan'],backtest_queue.encode(plan));store.recover()
        held=store.change(item['id'],'hold',dict(revision=store.get(item['id'])['revision']))
        renamed=dict(submission,name='Renamed',revision=held['revision'])
        store.change(item['id'],'update',renamed)
        self.assertEqual(json.loads(store.claim()['plan']),plan);store.recover()
        held=store.change(item['id'],'hold',dict(revision=store.get(item['id'])['revision']))
        store.change(item['id'],'update',dict(renamed,revision=held['revision'],options=dict(submission['options'],engine='original')))
        self.assertIsNone(store.claim()['plan'])

    def test_unavailable_queue_engine_waits_without_blocking_original(self):
        owner=self.selectable();store=backtest_queue.Store(self.root/'queue.sqlite')
        first=store.enqueue(request('Experimental',options=dict(self.options,engine='experimental')))
        second=store.enqueue(request('Original',options=self.options))
        with patch.object(owner,'status',return_value=dict(state='unavailable')):
            claimed=store.claim(owner.queue_engines())
            self.assertEqual(claimed['id'],second['id'])
            consumer=backtest_queue.Queue(store,calculations=owner,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')));consumer._run(claimed)
            self.assertEqual(store.get(second['id'])['snapshot']['result']['producer']['engine'],'original')
            self.assertEqual(store.get(first['id'])['state'],'queued')
        with patch.object(owner,'status',return_value=dict(state='current')):
            self.assertEqual(store.claim(owner.queue_engines())['id'],first['id'])

    def test_http_retries_reconcile_accepted_engine_when_preparation_is_stale(self):
        from http.client import HTTPConnection
        from threading import Thread
        import serve_app
        owner=self.selectable();owner.status=lambda:dict(state='current')
        owner.experimental.calculate=Mock(return_value=dict(periods=[],options={}))
        store=backtest_queue.Store(self.root/'retry-queue.sqlite');store.pause(True)
        consumer=backtest_queue.Queue(store,calculations=owner,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')))
        with patch.object(serve_app.backtest_queue,'Queue',return_value=consumer):
            server=serve_app.Server(('127.0.0.1',0),serve_app.Handler)
        server.calculations=owner;server.backtest_jobs.calculations=owner
        listener=Thread(target=server.serve_forever);listener.start()
        def post(path,payload):
            client=HTTPConnection(*server.server_address,timeout=5)
            try:
                client.request('POST',path,json.dumps(payload));response=client.getresponse()
                return response.status,json.loads(response.read())
            finally:client.close()
        try:
            payload=dict(mode='custom',options=dict(self.options,engine='experimental'))
            path='/api/backtest-runs/'+'c'*32
            self.assertEqual(post(path,payload)[0],202)
            server.backtest_jobs.runs['c'*32]['thread'].join(5)
            queued=request(options=payload['options'])
            self.assertEqual(post('/api/backtest-queue',queued)[0],200)
            owner.status=lambda:dict(state='unavailable')
            self.assertEqual(post(path,payload)[1]['state'],'complete')
            self.assertEqual(post('/api/backtest-queue',queued)[1]['options']['engine'],'experimental')
            self.assertEqual(post('/api/backtest-runs/'+'d'*32,payload)[0],503)
            self.assertEqual(post(path,dict(payload,options=dict(self.options,engine='original')))[0],400)
            self.assertEqual(post('/api/backtest-queue',dict(queued,options=self.options))[0],409)
            owner.experimental.calculate.assert_called_once()
        finally:
            server.shutdown();listener.join(5);server.server_close()

    def test_optional_rebuild_does_not_prepare_numerical_stack(self):
        import data_manager
        owner=self.selectable()
        jobs=data_manager.Jobs(owner.preparation,optional_preparation=True)
        options=data_manager.options(dict(scope='symbols',symbols='A',start='2015-01-01',end='2016-12-30',datasets=['prices']))
        with patch.object(daily,'prepare'),patch.object(data_manager.subprocess,'run'),patch.object(data_manager,'inspect',return_value={}):
            jobs._work('rebuild',options)
            self.assertIsNone(jobs.state['error']);self.assertTrue(jobs.rebuilt)
            owner.preparation.prepare.assert_not_called();owner.preparation.invalidate.assert_called_once()
            jobs._work('prepare',options)
            owner.preparation.prepare.assert_called_once()

    def test_original_and_stored_reading_with_native_imports_forbidden(self):
        code=r'''
import sys,json,sqlite3
from pathlib import Path
from unittest.mock import Mock,patch
root,dbpath=map(Path,sys.argv[1:3]);sys.path[:0]=[str(root),str(root/'scripts'),str(root/'website')]
class NoNative:
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in ('numpy','numba','llvmlite'):raise AssertionError('Original imported numerical dependencies')
sys.meta_path.insert(0,NoNative())
from backtest.inputs import daily
import serve_app,engine_selection,saved_backtests
owner=engine_selection.Selectable(Mock())
def connect():
 db=sqlite3.connect(dbpath);db.row_factory=sqlite3.Row;return db
with patch.object(daily,'connect',side_effect=connect):
 result=owner.calculate('custom',dict(start='2015-01-01',end='2016-12-30',months=3,rank_to=1),None,None)
store=saved_backtests.Store(dbpath.parent/'saved-test.sqlite')
snapshot=dict(version=2,kind='custom',settings=dict(mode='custom'),result=result,catalog=dict(metrics={},filters={}),presentation={})
item=store.save('Original',snapshot);assert store.get(item['id'])['snapshot']==snapshot
owner.close();owner.retire();print('optional dependencies verified')
'''
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT),str(self.path)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)


class RuntimeSelectionTests(unittest.TestCase):
    def setUp(self):
        from test_candidate_calculations import CandidateTests
        CandidateTests.setUp(self)
    def make(self,**kw):
        from test_candidate_calculations import CandidateTests
        return CandidateTests.make(self,**kw)
    def assert_closed(self,value):
        from test_candidate_calculations import CandidateTests
        CandidateTests.assert_closed(self,value)
    def test_matched_fixed_seeded_random_replay_and_return_to_original(self):
        from test_candidate_calculations import CandidateTests
        from backtest.engines.numerical.portfolio import compare_results
        from test_operating_spread_engine import financial_inputs, FILTERS
        financial_inputs(self.fixture.fixture.db)
        self.fixture.binding['daily'] = dict(operating_spread=True)
        self.fixture.prepare()
        (self.root/'binding.json').write_text(json.dumps(self.fixture.binding))
        candidate=CandidateTests.candidate(self)
        owner=engine_selection.Selectable(candidate.preparation);owner.experimental=candidate
        owner.status=lambda:dict(state='current')
        self.addCleanup(owner.close);self.addCleanup(owner.retire)
        def connect():
            db=sqlite3.connect(self.fixture.fixture.path);db.row_factory=sqlite3.Row;return db
        with patch('backtest.inputs.daily.connect',side_effect=connect),patch('backtest.runtime.cache_access.workspace',self.fixture.owner):
            for mode,extra in (('custom',{}),('random',dict(trials=2,seed=2607948532))):
                options=dict(start='2015-01-02',end='2016-12-30',months=12,pool='cached',min_cap=0.,min_ev=0.,rank_to=5,selection_order='rank_first',filters=FILTERS,**extra)
                plans=[]
                experimental=owner.calculate(mode,dict(options,engine='experimental'),None,plans.append)
                original=owner.calculate(mode,dict(options,engine='original'),None,None,planned=plans[0] if plans else None)
                self.assertTrue(all(period['names'] for period in
                    (original['periods'] if mode=='custom' else original['trial_results'][0]['periods'])))
                self.assertIsNone(candidate.runtime);self.assertEqual(experimental.pop('producer')['engine'],'experimental')
                self.assertEqual(original.pop('producer')['engine'],'original')
                if mode=='custom':self.assertTrue(compare_results(original,experimental)['exact'])
                else:
                    self.assertEqual(original['distributions'],experimental['distributions'])
                    for a,b in zip(original['trial_results'],experimental['trial_results']):self.assertTrue(compare_results(a,b)['exact'])
                self.assert_closed(candidate.created[-1])
                if mode=='random':
                    store=backtest_queue.Store(self.root/'selected-queue.sqlite')
                    item=store.enqueue(request(mode='random',options=dict(options,engine='experimental')))
                    store.claim();store.progress(item['id'],'configuration',plans[0])
                    store.recover()
                    consumer=backtest_queue.Queue(backtest_queue.Store(store.path),calculations=owner,library=backtest_queue.saved_backtests.Store((backtest_queue.Store(store.path)).path.with_name('saved-library.sqlite')))
                    consumer._run(consumer.store.claim())
                    completed=consumer.store.get(item['id'])
                    self.assertEqual(completed['state'],'complete')
                    self.assertEqual(completed['options']['engine'],'experimental')
                    self.assertEqual(completed['snapshot']['result']['producer']['engine'],'experimental')
                    self.assertEqual(completed['snapshot']['result']['configuration'],plans[0])
                    self.assertGreater(completed['snapshot']['result']['execution']['recovered_trials'],0)


if __name__=='__main__':unittest.main()

"""Durable queue transactions, consumer ownership and real engine recovery."""
from contextlib import ExitStack
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website'),str(ROOT/'tests')]
import backtest_control
import backtest_queue as queue
import cache_access
import schedules
import serve
import test_robustness as fixtures


def request(name='Test',**values):
    value=dict(id=uuid.uuid4().hex,name=name,mode='custom',
               options=dict(start='2015-01-01',end='2016-12-30',months=3,rank_to=1),
               catalog=dict(metrics={},filters={}),presentation={})
    value.update(values);return value


def wait_for(test,predicate):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.02)
    test.fail('Queue operation did not finish.')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.store=queue.Store(Path(self.folder.name)/'queue.sqlite')

    def change(self,record,action,**options):
        return self.store.change(record['id'],action,dict(revision=record['revision'],**options))

    def test_idempotent_submission_survives_edits_and_deletion(self):
        submission=request();item=self.store.enqueue(submission)
        self.assertEqual(self.store.enqueue(submission)['id'],item['id'])
        with self.assertRaises(queue.Conflict):self.store.enqueue(dict(submission,name='Different'))
        held=self.change(item,'hold')
        edited=self.change(held,'update',**{key:value for key,value in request('Edited').items() if key!='id'})
        self.assertEqual(self.store.enqueue(submission)['name'],'Edited')
        self.change(edited,'delete')
        self.assertEqual(self.store.listing()['records'],[])
        with self.assertRaises(queue.Conflict):self.store.enqueue(submission)
        with self.assertRaises(queue.Missing):self.store.get(item['id'])

    def test_edit_hold_order_and_atomic_revision_conflicts(self):
        first=self.store.enqueue(request('First'));second=self.store.enqueue(request('Second'))
        self.change(second,'move',direction=-1)
        self.assertEqual([r['name'] for r in self.store.listing()['records']],['Second','First'])
        with self.assertRaises(queue.Conflict):self.change(second,'hold')
        first=self.store.get(first['id']);held=self.change(first,'hold')
        self.assertEqual(self.store.claim()['id'],second['id'])
        self.assertIsNone(self.store.claim(),'Held settings cannot start.')
        edited=self.change(held,'update',**{key:value for key,value in request('New settings',options=dict(first['options'],rank_to=2)).items() if key!='id'})
        self.assertEqual(edited['state'],'queued');self.assertEqual(edited['options']['rank_to'],2)
        self.assertEqual(self.store.claim()['id'],first['id'])
        with self.assertRaises(queue.Conflict):self.change(edited,'delete')

    def test_pause_and_recovery_preserve_stop_and_held_intent(self):
        first=self.store.enqueue(request('First'));second=self.store.enqueue(request('Second'))
        self.store.pause(True);self.assertIsNone(self.store.claim())
        self.store.pause(False);running=self.store.claim()
        stopping=self.change(self.store.get(running['id']),'stop')
        held=self.change(second,'hold')
        self.store.recover()
        self.assertEqual(self.store.get(stopping['id'])['state'],'cancelled')
        self.assertEqual(self.store.get(held['id'])['state'],'held')
        with self.assertRaises(queue.Conflict):self.change(first,'hold')

    def test_invalid_requests_and_atomic_capacity_across_stores(self):
        for invalid in (request(mode='latest'),request(name=''),request(options={}),request(options={'start':'2015','end':'2016','min_ev':float('inf')})):
            with self.assertRaises(ValueError):self.store.enqueue(invalid)
        other=queue.Store(self.store.path);results=[]
        def add(store):
            try:results.append(store.enqueue(request())['id'])
            except queue.Conflict:results.append('full')
        with patch.object(queue,'LIMIT',1):
            threads=[Thread(target=add,args=(store,)) for store in (self.store,other)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(5)
        self.assertEqual(results.count('full'),1);self.assertEqual(len(self.store.listing()['records']),1)

    def test_restart_recovers_running_with_original_random_seed(self):
        submission=request(mode='random',options=dict(request()['options'],trials=2))
        item=self.store.enqueue(submission);claimed=self.store.claim();seed=claimed['seed']
        reopened=queue.Store(self.store.path);reopened.recover()
        retry=reopened.claim()
        self.assertEqual(retry['id'],item['id']);self.assertEqual(retry['seed'],seed)
        self.assertEqual(retry['state'],'running')

    def test_name_only_edit_keeps_recorded_dates_and_parameter_edit_replans(self):
        submission=request(mode='random',options=dict(request()['options'],trials=2,seed=None))
        item=self.store.enqueue(submission);claimed=self.store.claim();seed=claimed['seed']
        self.assertIsInstance(seed,int,'A null seed still records a fresh seed at admission.')
        plan={'seed':seed,'samples':[['2015-01-05']],'requested':2}
        self.store.progress(item['id'],'configuration',plan);self.store.recover()
        held=self.change(self.store.get(item['id']),'hold')
        renamed=self.change(held,'update',**{key:value for key,value in dict(submission,name='Renamed').items() if key!='id'})
        self.assertEqual(renamed['configuration']['seed'],seed)
        retry=self.store.claim();self.assertEqual(json.loads(retry['plan']),plan);self.assertEqual(retry['seed'],seed)
        self.store.recover();held=self.change(self.store.get(item['id']),'hold')
        edited=self.change(held,'update',**{key:value for key,value in dict(submission,options=dict(submission['options'],months=6)).items() if key!='id'})
        self.assertIsNone(edited['configuration']);self.assertIsNone(self.store.claim()['plan'])


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        fixtures.RobustnessTests.setUp(self)
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.folder=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.path=self.folder/'daily.sqlite'
        db=sqlite3.connect(self.path);self.db.backup(db);db.close()
        self.owner=cache_access.WorkspaceAccess(self.folder/'financial.lock')
        self.context.enter_context(patch.object(cache_access,'workspace',self.owner))
        self.closed=[];owner=self.owner;closed=self.closed
        class Database(sqlite3.Connection):
            def close(db):closed.append(getattr(owner.state,'held',False));super().close()
        def connect():
            db=sqlite3.connect(self.path,factory=Database);db.row_factory=sqlite3.Row;return db
        self.context.enter_context(patch.object(schedules,'connect',side_effect=connect))
        self.entered=Event();self.release=Event()
        original=schedules.compute_period
        def compute(*args,**kwargs):
            self.entered.set()
            while not self.release.wait(.01):backtest_control.checkpoint()
            return original(*args,**kwargs)
        self.context.enter_context(patch.object(schedules,'compute_period',side_effect=compute))
        self.store=queue.Store(self.folder/'queue.sqlite');self.consumer=queue.Queue(self.store)
        self.addCleanup(self.finish)

    def finish(self):self.release.set();self.consumer.close()

    def terminal(self,identifier):
        return wait_for(self,lambda:(record if (record:=self.store.get(identifier))['state'] in ('complete','failed','cancelled') else None))

    def test_sequential_execution_pause_hold_delete_failure_and_open_results(self):
        self.store.pause(True)
        invalid=self.store.enqueue(request('Invalid',options=dict(request()['options'],months=7)))
        first=self.store.enqueue(request('First'))
        deleted=self.store.enqueue(request('Delete before running'))
        held=self.store.enqueue(request('Held'))
        self.store.change(deleted['id'],'delete',{'revision':deleted['revision']})
        self.store.change(held['id'],'hold',{'revision':held['revision']})
        self.consumer.start();self.store.pause(False)
        self.assertEqual(self.terminal(invalid['id'])['state'],'failed')
        self.assertTrue(self.entered.wait(5))
        self.store.pause(True);self.release.set()
        done=self.terminal(first['id'])
        self.assertEqual(done['state'],'complete');self.assertTrue(done['snapshot']['result']['periods'])
        self.assertEqual(self.store.get(held['id'])['state'],'held')
        self.assertTrue(all(self.closed),'Every calculation database closes under financial ownership.')
        self.assertNotIn('snapshot',self.store.listing()['records'][1],'Lists must not load full results.')
        self.consumer.close()
        reopened=queue.Store(self.store.path)
        self.assertEqual(reopened.get(first['id'])['snapshot'],done['snapshot'])
        self.assertTrue(reopened.listing()['paused'])

    def test_two_consumers_never_recover_or_run_the_active_owner(self):
        item=self.store.enqueue(request())
        self.consumer.start();self.assertTrue(self.entered.wait(5))
        other=queue.Queue(queue.Store(self.store.path));other.start()
        try:
            time.sleep(.3)
            self.assertEqual(len(self.closed),0)
            self.assertEqual(self.store.get(item['id'])['state'],'running')
            self.release.set();self.terminal(item['id'])
            self.assertEqual(len(self.closed),1)
        finally:other.close()

    def test_crashed_process_releases_queue_ownership_before_recovery(self):
        item=self.store.enqueue(request())
        child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'claim',str(self.store.path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'claimed')
            self.consumer.start();time.sleep(.25)
            self.assertFalse(self.entered.is_set(),'A second process must not steal the running item.')
            child.kill();child.wait(5)
            self.assertTrue(self.entered.wait(5),'Process exit must release the OS queue lock.')
            self.release.set();self.assertEqual(self.terminal(item['id'])['state'],'complete')
        finally:
            if child.poll() is None:child.kill();child.wait(5)
            child.stdin.close();child.stdout.close()

    def test_user_stop_rolls_back_then_next_job_runs(self):
        item=self.store.enqueue(request('Stop'));next_item=self.store.enqueue(request('Next'))
        self.consumer.start();self.assertTrue(self.entered.wait(5))
        active=self.store.get(item['id']);self.store.change(item['id'],'stop',{'revision':active['revision']})
        self.assertEqual(self.terminal(item['id'])['state'],'cancelled')
        db=sqlite3.connect(self.path)
        try:self.assertEqual(db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],0)
        finally:db.close()
        self.release.set();self.assertEqual(self.terminal(next_item['id'])['state'],'complete')

    def test_financial_contention_defers_work_instead_of_failing_it(self):
        item=self.store.enqueue(request())
        with self.owner.hold():
            self.consumer.start()
            wait_for(self,lambda:(self.store.get(item['id'])['progress'] or {}).get('type')=='waiting')
            self.assertFalse(self.entered.is_set())
            self.assertEqual(self.store.get(item['id'])['state'],'running')
        self.release.set();self.assertEqual(self.terminal(item['id'])['state'],'complete')

    def test_server_shutdown_requeues_interrupted_work_and_reuses_seed(self):
        item=self.store.enqueue(request(mode='random',options=dict(request()['options'],trials=2)))
        self.consumer.start();self.assertTrue(self.entered.wait(5))
        first_config=self.store.get(item['id'])['configuration']
        self.consumer.close()
        with self.store.database() as db:
            first_plan=json.loads(db.execute('SELECT plan FROM jobs WHERE id=?',(item['id'],)).fetchone()[0])
        self.assertEqual(self.store.get(item['id'])['state'],'queued')
        self.assertEqual(self.closed,[True])
        self.context.enter_context(patch.object(queue.backtest_jobs.robustness,'plan',side_effect=AssertionError('Recovery must reuse the recorded dates.')))
        self.release.set();self.consumer=queue.Queue(self.store);self.consumer.start()
        complete=self.terminal(item['id'])
        self.assertEqual(complete['configuration']['seed'],first_config['seed'])
        self.assertEqual(complete['snapshot']['result']['configuration']['samples'],first_plan['samples'])
        self.assertEqual(len(complete['snapshot']['result']['trial_results']),2)
        self.assertTrue(complete['snapshot']['result']['trial_results'][0]['periods'][0]['holdings'])

    def test_real_http_queue_admission_mutations_results_and_origins(self):
        class Handler(serve.Handler):
            def log_message(self,*args):pass
        server=serve.Server(('127.0.0.1',0),Handler);server.backtest_queue=self.consumer
        thread=Thread(target=server.serve_forever);thread.start()
        def http(method,path='',payload=None,headers=None):
            client=HTTPConnection(*server.server_address,timeout=5)
            try:
                client.request(method,'/api/backtest-queue'+path,json.dumps(payload) if payload is not None else None,headers or {})
                response=client.getresponse();return response.status,json.loads(response.read())
            finally:client.close()
        try:
            self.assertEqual(http('POST','/pause',{'paused':True})[0],200)
            submission=request();status,item=http('POST',payload=submission);self.assertEqual(status,200)
            self.assertEqual(http('POST',payload=submission)[1]['id'],item['id'])
            self.assertEqual(len(http('GET')[1]['records']),1)
            status,held=http('POST','/'+item['id']+'/hold',{'revision':item['revision']});self.assertEqual(status,200)
            self.assertEqual(http('POST','/'+item['id']+'/release',{'revision':item['revision']})[0],409)
            self.assertEqual(http('POST','/'+item['id']+'/release',{'revision':held['revision']})[0],200)
            self.assertEqual(http('POST',payload=request(),headers={'Origin':'http://foreign.test'})[0],403)
            self.release.set();http('POST','/pause',{'paused':False});self.terminal(item['id'])
            status,result=http('GET','/'+item['id']);self.assertEqual(status,200);self.assertIn('snapshot',result)
            self.assertNotIn('snapshot',http('GET')[1]['records'][0])
            self.assertEqual(http('DELETE','/'+item['id'],{'revision':result['revision']})[0],200)
        finally:server.shutdown();thread.join(5);server.server_close()


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='claim':
        store=queue.Store(Path(sys.argv[2]))
        with cache_access.WorkspaceAccess(store.path.with_suffix('.lock')).hold():
            store.claim();print('claimed',flush=True);sys.stdin.read(1)
    else:unittest.main()

"""HTTP disconnects leave jobs running; explicit stops retain engine cleanup."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.inputs import daily
from contextlib import ExitStack
from http.client import HTTPConnection
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website'),str(ROOT/'tests')]
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import backtest_control as control
import backtest_jobs
from backtest.runtime import cache_access as cache_access
from backtest.engines.original import schedules as schedules
import serve
import test_robustness as fixtures


class JobTests(unittest.TestCase):
    def setUp(self):
        fixtures.RobustnessTests.setUp(self)
        self.context=ExitStack();self.addCleanup(self.context.close)
        folder=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.path=folder/'daily.sqlite'
        target=sqlite3.connect(self.path);self.db.backup(target);target.close()
        self.owner=cache_access.WorkspaceAccess(folder/'cache.lock')
        self.context.enter_context(patch.object(cache_access,'workspace',self.owner))
        self.closures=[]
        owner=self.owner;closures=self.closures
        class Database(sqlite3.Connection):
            def close(db):
                closures.append(getattr(owner.state,'held',False))
                super().close()
        def connect():
            db=sqlite3.connect(self.path,factory=Database);db.row_factory=sqlite3.Row;return db
        self.context.enter_context(patch.object(daily,'connect',side_effect=connect))
        self.entered=Event();self.release=Event()
        original=schedules.compute_period
        def compute(*args,**kwargs):
            result=original(*args,**kwargs);self.entered.set()
            while not self.release.wait(.01):control.checkpoint()
            return result
        self.context.enter_context(patch.object(schedules,'compute_period',side_effect=compute))
        class Handler(serve.Handler):
            def log_message(self,*args):pass
        self.server=serve.Server(('127.0.0.1',0),Handler)
        self.thread=Thread(target=self.server.serve_forever);self.thread.start()
        self.addCleanup(self.finish)
        self.identifier='a'*32
        self.options=dict(start='2015-01-01',end='2016-12-30',months=3,rank_to=1)

    def finish(self):
        self.release.set();self.server.shutdown();self.thread.join(5);self.server.server_close()

    def request(self,method='GET',suffix='',payload=None,identifier=None,headers=None):
        client=HTTPConnection(*self.server.server_address,timeout=5)
        try:
            body=json.dumps(payload) if payload is not None else None
            client.request(method,'/api/backtest-runs/'+(identifier or self.identifier)+suffix,body=body,headers=headers or {})
            response=client.getresponse();return response.status,json.loads(response.read())
        finally:client.close()

    def start(self,mode='custom',options=None):
        return self.request('POST',payload=dict(mode=mode,options=options or self.options))

    def terminal(self):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            status,result=self.request()
            if result['state'] not in ('running','stopping'):return result
            time.sleep(.01)
        self.fail('Job did not finish.')

    def test_closed_browser_does_not_cancel_and_reopen_gets_complete_result(self):
        status,run=self.start();self.assertEqual(status,202)
        self.assertTrue(self.entered.wait(5))
        # The POST connection and a subsequent polling connection both close.
        self.assertEqual(self.request()[1]['state'],'running')
        time.sleep(.1)
        self.assertEqual(self.request()[1]['state'],'running')
        self.assertEqual(self.closures,[])
        self.release.set();result=self.terminal()
        self.assertEqual(result['state'],'complete')
        self.assertTrue(result['result']['periods'])
        self.assertEqual(result['options'],self.options)
        self.assertEqual(self.request()[1]['result'],result['result'])
        status,metadata=self.request(suffix='/status')
        self.assertEqual(status,200)
        self.assertEqual(metadata['state'],'complete')
        self.assertEqual(metadata['options'],self.options)
        self.assertNotIn('result',metadata,'Recovery must inspect status without transferring holding lists.')
        self.assertEqual(self.closures,[True])

    def test_disconnect_before_start_response_still_runs_and_retries_same_id(self):
        client=socket.create_connection(self.server.server_address,timeout=5)
        body=json.dumps(dict(mode='custom',options=self.options)).encode()
        client.sendall(f'POST /api/backtest-runs/{self.identifier} HTTP/1.0\r\nHost: localhost\r\nContent-Length: {len(body)}\r\n\r\n'.encode()+body)
        client.close()
        self.assertTrue(self.entered.wait(5))
        self.assertEqual(self.start()[0],202)
        self.assertEqual(len(self.server.backtest_jobs.runs),1)
        self.release.set();self.assertEqual(self.terminal()['state'],'complete')
        self.assertEqual(len(self.closures),1)

    def test_explicit_stop_rolls_back_then_closes_database_under_ownership(self):
        self.start();self.assertTrue(self.entered.wait(5))
        self.assertEqual(self.request('POST','/stop')[0],202)
        self.assertEqual(self.terminal()['state'],'cancelled')
        self.assertEqual(self.closures,[True])
        db=sqlite3.connect(self.path)
        try:self.assertEqual(db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],0)
        finally:db.close()
        self.assertEqual(self.request('POST','/stop')[1]['state'],'cancelled')

    def test_random_run_retains_progress_configuration_and_all_trial_holdings(self):
        self.start('random',dict(self.options,trials=2,seed=42))
        self.assertTrue(self.entered.wait(5))
        run=self.request()[1]
        self.assertEqual(run['configuration']['seed'],42)
        self.assertIsNotNone(run['progress'])
        self.release.set();run=self.terminal()
        self.assertEqual(run['state'],'complete')
        self.assertEqual(run['result']['completed'],2)
        self.assertEqual(len(run['result']['trial_results']),2)
        self.assertTrue(run['result']['trial_results'][0]['periods'][0]['holdings'])

    def test_shutdown_joins_job_before_server_ownership_can_end(self):
        self.start();self.assertTrue(self.entered.wait(5))
        self.server.shutdown();self.thread.join(5)
        self.assertFalse(self.thread.is_alive())
        self.server.server_close()
        self.assertEqual(self.server.backtest_jobs.snapshot(self.identifier)['state'],'cancelled')
        self.assertEqual(self.closures,[True])
        self.assertFalse(self.server.backtest_jobs.runs[self.identifier]['thread'].is_alive())
        with self.assertRaises(backtest_jobs.Busy):
            self.server.backtest_jobs.start('b'*32,'custom',self.options)

    def test_duplicate_id_and_busy_rejection_do_not_start_more_work(self):
        self.start();self.assertTrue(self.entered.wait(5))
        self.assertEqual(self.start()[0],202)
        self.assertEqual(self.start(options=dict(self.options,rank_to=2))[0],400)
        self.assertEqual(self.request('POST',identifier='b'*32,payload=dict(mode='custom',options=self.options))[0],409)
        self.assertEqual(len(self.server.backtest_jobs.runs),1)

    def test_failures_are_retrievable_without_rerunning(self):
        self.start(options=dict(self.options,months=7))
        run=self.terminal();self.assertEqual(run['state'],'failed')
        self.assertTrue(run['error'])
        self.assertEqual(self.request()[1]['state'],'failed')
        self.assertEqual(self.closures,[True])

    def test_unknown_expired_invalid_and_cross_origin_requests(self):
        self.assertEqual(self.request()[0],404)
        self.assertEqual(self.request('POST','/stop')[0],404)
        self.assertEqual(self.request('POST',payload=dict(mode='custom',options=self.options),identifier='bad')[0],400)
        self.assertEqual(self.request('POST',payload=dict(mode='custom',options=self.options),headers={'Origin':'http://other.test'})[0],403)
        self.assertEqual(self.request('POST',payload=dict(mode='custom',options={'min_ev':float('inf')}))[0],400)
        self.release.set();self.start();self.terminal()
        self.server.backtest_jobs.runs[self.identifier]['finished']=time.time()-86401
        self.assertEqual(self.request()[0],404)

    def test_recorded_plan_submission_is_idempotent_and_rejects_changed_plan(self):
        self.release.set()
        options=dict(self.options,trials=2,seed=42)
        planned=backtest_jobs.robustness.plan(self.db,**options)
        payload=dict(mode='random',options=options,planned=planned)
        self.assertEqual(self.request('POST',payload=payload)[0],202)
        result=self.terminal()
        self.assertEqual(result['configuration'],planned)
        self.assertEqual(self.request('POST',payload=payload)[0],202)
        altered=json.loads(json.dumps(payload));altered['planned']['seed']=43
        self.assertEqual(self.request('POST',payload=altered)[0],400)

    def test_completed_result_retention_is_bounded(self):
        self.release.set()
        for digit in '12345':
            self.identifier=digit*32
            self.start();self.assertEqual(self.terminal()['state'],'complete')
        self.assertEqual(len(self.server.backtest_jobs.runs),4)
        self.assertEqual(self.request(identifier='1'*32)[0],404)


if __name__=='__main__':unittest.main()

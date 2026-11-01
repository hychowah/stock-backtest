"""Cooperative stop keeps transactions, worker cleanup and request ownership safe."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import daily
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT),str(ROOT/'tests')]
from backtest.runtime import backtest_control as control
from backtest.engines.original import book_batch as book_batch
from backtest.runtime import cache_access as cache_access
from backtest.engines.original import robustness as robustness
from backtest.engines.original import schedules as schedules
from website.server import app as serve
import test_robustness as fixtures


class CancellationTests(unittest.TestCase):
    config=fixtures.RobustnessTests.config

    def setUp(self):
        fixtures.RobustnessTests.setUp(self)

    def test_cancelled_fixed_books_roll_back_and_the_next_run_works(self):
        stopped=False
        original=schedules.prepare_period
        def prepare(*args,**kwargs):
            nonlocal stopped
            value=original(*args,**kwargs);stopped=True
            return value
        with control.cancel_when(lambda:stopped),patch.object(schedules,'prepare_period',side_effect=prepare):
            with self.assertRaises(control.Cancelled):
                schedules.backtest(self.db,start='2015-01-01',end='2016-12-30',months=3,rank_to=1)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM period_pools').fetchone()[0],0)
        self.assertTrue(schedules.backtest(self.db,start='2015-01-01',end='2016-12-30',months=3,rank_to=1)['periods'])

    def test_cancel_during_trial_write_keeps_only_completed_trials(self):
        configuration=self.config(trials=3,seed=11)
        planned=book_batch.plan(self.db,configuration)
        first=len(planned['trials'][0]);writes=0;stopped=False
        original=daily.store_period
        def store(*args,**kwargs):
            nonlocal writes,stopped
            original(*args,**kwargs);writes+=1
            if writes>first:stopped=True
        with control.cancel_when(lambda:stopped),patch.object(daily,'store_period',side_effect=store):
            with self.assertRaises(control.Cancelled):robustness.run(self.db,configuration,workers=1)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM period_pools').fetchone()[0],first)
        retry=robustness.run(self.db,configuration,workers=1)
        self.assertEqual(retry['completed'],3)
        self.assertEqual(retry['execution']['reused_books'],first)

    def test_parallel_stop_joins_workers_before_return_and_can_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'daily.sqlite'
            db=sqlite3.connect(path);db.row_factory=sqlite3.Row
            self.db.backup(db)
            try:
                configuration=self.config(trials=4,seed=41);stopped=False;executors=[]
                original=book_batch.ProcessPoolExecutor
                def executor(*args,**kwargs):
                    value=original(*args,**kwargs);executors.append(value);return value
                def progress(event):
                    nonlocal stopped
                    if event['completed']==1:stopped=True
                with control.cancel_when(lambda:stopped),patch.object(book_batch,'ProcessPoolExecutor',side_effect=executor):
                    with self.assertRaises(control.Cancelled):robustness.run(db,configuration,progress,workers=2)
                self.assertEqual(len(executors),1)
                self.assertIsNone(executors[0]._processes,'Executor shutdown must finish before returning.')
                self.assertFalse(db.in_transaction)
                self.assertEqual(robustness.run(db,configuration,workers=2)['completed'],4)
            finally:db.close()

    def test_cancellation_is_local_to_the_request_and_context_is_reset(self):
        errors=[]
        def other_request():
            try:control.checkpoint()
            except BaseException as error:errors.append(error)
        stopped=False
        with control.cancel_when(lambda:stopped):
            with self.assertRaises(control.Cancelled):
                with control.cancel_when(lambda:True):pass
            control.checkpoint();stopped=True
            thread=Thread(target=other_request);thread.start();thread.join(5)
            with self.assertRaises(control.Cancelled):control.checkpoint()
        self.assertEqual(errors,[])
        control.checkpoint()

    def test_disconnect_check_preserves_bytes_and_detects_closed_socket(self):
        connection,peer=socket.socketpair()
        try:
            handler=object.__new__(serve.Handler);handler.connection=connection
            check=handler.disconnect_check()
            with patch.object(serve.time,'monotonic',side_effect=[1,2,3]):
                self.assertFalse(check())
                peer.sendall(b'x');self.assertFalse(check())
                self.assertEqual(connection.recv(1),b'x')
                peer.close();self.assertTrue(check())
        finally:connection.close();peer.close()

    def test_real_http_abort_rolls_back_fixed_and_random_work_before_unlock(self):
        for endpoint in ('/api/schedule','/api/robustness'):
            with self.subTest(endpoint=endpoint),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'daily.sqlite'
                target=sqlite3.connect(path);self.db.backup(target);target.close()
                owner=cache_access.WorkspaceAccess(Path(folder)/'cache.lock')
                entered=Event();closed=Event();release=Event();close_ownership=[]
                class Database(sqlite3.Connection):
                    def close(db):
                        close_ownership.append(getattr(owner.state,'held',False))
                        super().close();closed.set()
                def connect():
                    db=sqlite3.connect(path,factory=Database);db.row_factory=sqlite3.Row;return db
                original=schedules.compute_period
                def compute(*args,**kwargs):
                    book=original(*args,**kwargs);entered.set()
                    while not release.wait(.01):control.checkpoint()
                    return book
                class Handler(serve.Handler):
                    def log_message(self,*args):pass
                server=serve.Server(('127.0.0.1',0),Handler)
                thread=Thread(target=server.serve_forever);thread.start()
                client=socket.create_connection(server.server_address,timeout=5)
                body=json.dumps(dict(start='2015-01-01',end='2016-12-30',months=3,rank_to=1,**({'trials':2,'seed':42} if endpoint.endswith('robustness') else {}))).encode()
                try:
                    with patch.object(cache_access,'workspace',owner),patch.object(daily,'connect',side_effect=connect),patch.object(schedules,'compute_period',side_effect=compute):
                        client.sendall(f'POST {endpoint} HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Length: {len(body)}\r\n\r\n'.encode()+body)
                        self.assertTrue(entered.wait(5),'The real route must reach calculation.')
                        client.close()
                        self.assertTrue(closed.wait(5),'An aborted request must close its database.')
                        self.assertEqual(close_ownership,[True],'Database closes before cache ownership ends.')
                finally:
                    release.set();client.close();server.shutdown();thread.join(5);server.server_close()
                db=sqlite3.connect(path)
                try:self.assertEqual(db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],0)
                finally:db.close()


if __name__=='__main__':unittest.main()

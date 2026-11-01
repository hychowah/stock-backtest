"""One application admission boundary, with real ordinary financial results."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.application.original_calculations import Original
from backtest.application.calculation_contract import Unavailable
from backtest.inputs import daily

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from contextlib import ExitStack
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website'),str(ROOT/'tests')]
from backtest.application import jobs as backtest_jobs
from backtest.application import queue as backtest_queue
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import cache_access as cache_access
from backtest.engines.original import robustness as robustness
from backtest.engines.original import schedules as schedules
import serve
from test_queue import request
import test_robustness as fixtures


def financial_result(value):
    # Execution diagnostics differ for fresh/replayed and memory/file databases.
    if isinstance(value,dict):return {k:financial_result(v) for k,v in value.items() if k not in ('seconds','execution')}
    if isinstance(value,list):return [financial_result(v) for v in value]
    return value


class CalculationTests(unittest.TestCase):
    def setUp(self):
        fixtures.RobustnessTests.setUp(self)
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.path=self.root/'daily.sqlite'
        db=sqlite3.connect(self.path);self.db.backup(db);db.close()
        self.owner=cache_access.WorkspaceAccess(self.root/'financial.lock')
        self.context.enter_context(patch.object(cache_access,'workspace',self.owner))
        self.closures=[];owner=self.owner;closures=self.closures
        class Database(sqlite3.Connection):
            def close(db):
                closures.append(getattr(owner.state,'held',False));super().close()
        def connect():
            db=sqlite3.connect(self.path,factory=Database);db.row_factory=sqlite3.Row;return db
        self.context.enter_context(patch.object(daily,'connect',side_effect=connect))
        self.options=dict(start='2015-01-01',end='2016-12-30',months=3,rank_to=1)
        self.service=Original()

    def handler(self,path,options):
        handler=object.__new__(serve.Handler)
        handler.server=type('Server',(),dict(lifecycle=None,calculations=self.service))()
        body=json.dumps(options).encode()
        handler.path=path;handler.rfile=io.BytesIO(body);handler.wfile=io.BytesIO()
        handler.headers={'Host':'127.0.0.1:8765','Content-Length':str(len(body))}
        handler.disconnect_check=lambda:lambda:False
        handler.statuses=[];handler.send_response=handler.statuses.append
        handler.send_header=lambda *args:None;handler.end_headers=lambda:None
        handler.replies=[];handler.reply=lambda status,value:handler.replies.append((status,value))
        return handler

    def test_jobs_queue_and_both_legacy_routes_share_owner_without_preholding(self):
        calls=[];original=self.service.calculate
        def calculate(*args,**kwargs):
            self.assertFalse(getattr(self.owner.state,'held',False))
            calls.append(args[0]);return original(*args,**kwargs)
        with patch.object(self.service,'calculate',side_effect=calculate):
            jobs=backtest_jobs.Jobs(self.service);jobs.start('a'*32,'custom',self.options)
            jobs.runs['a'*32]['thread'].join(5)
            self.assertEqual(jobs.snapshot('a'*32)['state'],'complete');jobs.close()
            store=backtest_queue.Store(self.root/'queue.sqlite')
            item=store.enqueue(request(options=self.options))
            queue=backtest_queue.Queue(store,calculations=self.service,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')))
            queue._run(store.claim());self.assertEqual(store.get(item['id'])['state'],'complete')
            fixed=self.handler('/api/schedule',self.options);fixed.do_POST()
            random=self.handler('/api/robustness',dict(self.options,trials=2,seed=42));random.do_POST()
        self.assertEqual(calls,['custom','custom','custom','random'])
        self.assertEqual(fixed.replies[0][0],200)
        self.assertEqual(json.loads(random.wfile.getvalue().splitlines()[-1])['type'],'complete')
        self.assertEqual(self.closures,[True]*4)
        server=serve.Server(('127.0.0.1',0),serve.Handler)
        try:
            self.assertIs(server.backtest_jobs.calculations,server.calculations)
            self.assertIs(server.backtest_queue.calculations,server.calculations)
        finally:server.server_close()

    def test_24_full_trials_replay_changed_filters_and_empty_selection(self):
        options=dict(self.options,trials=24,seed=42)
        plan=robustness.plan(self.db,**options)
        expected=[]
        reference=robustness.run(self.db,plan,capture=lambda number,trial:expected.append(trial))
        reference['trial_results']=expected
        configurations=[]
        actual=self.service.calculate('random',options,None,configurations.append)
        self.assertEqual(financial_result(actual),financial_result(reference))
        self.assertEqual(actual['execution'].keys(),reference['execution'].keys())
        self.assertEqual(configurations,[plan]);self.assertEqual(len(actual['trial_results']),24)
        with patch.object(robustness,'plan',side_effect=AssertionError('Must reuse the recorded plan')):
            replay=self.service.calculate('random',options,None,None,planned=plan)
        self.assertEqual(financial_result(replay),financial_result(actual))
        empty=self.service.calculate('custom',dict(self.options,min_cap=1e12),None,None)
        self.assertTrue(all(not period['holdings'] for period in empty['periods']))
        self.assertIsNone(empty['cagr'])

    def test_stop_during_canonical_planning_precedes_configuration_and_execution(self):
        from backtest import calendar_requests as calendar_requests
        from backtest.runtime import backtest_control as backtest_control
        configuration=[]
        original=calendar_requests.c.SessionCalendar.sample
        service=self.service
        def stop_before_draws(calendar,*args,**kwargs):
            service.close()
            return original(calendar,*args,**kwargs)
        options=dict(calendar=dict(version=1,start='2015-01-01',end='2016-12-30',
            interval=dict(unit='week',count=1)),trials=100,seed=42,rank_to=1)
        with patch.object(calendar_requests.c.SessionCalendar,'sample',stop_before_draws), \
                patch.object(robustness,'run',side_effect=AssertionError('Stopped plan must not execute')) as run:
            with self.assertRaises(backtest_control.Cancelled):
                service.calculate('random',options,None,configuration.append)
        self.assertEqual(configuration,[]);run.assert_not_called()
        self.assertEqual(self.closures,[True])

    def test_readiness_changes_while_queue_admission_waits(self):
        waiting=Event();outcome=[];ready=True
        def current():
            self.assertTrue(getattr(self.owner.state,'held',False));return ready
        self.service.ready=current
        def calculate():
            try:self.service.calculate('custom',self.options,lambda event:waiting.set() if event else None,None,admission='queue')
            except Exception as error:outcome.append(error)
        with self.owner.hold():
            thread=Thread(target=calculate);thread.start()
            self.assertTrue(waiting.wait(3));ready=False
        thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(len(outcome),1)
        self.assertIsInstance(outcome[0],Unavailable)
        self.assertEqual(self.closures,[])

    def test_queue_never_retries_validation_or_callback_failures(self):
        for failure in (ValueError('invalid calculation'),cache_access.Contention('inside execution')):
            with self.subTest(failure=type(failure).__name__),patch.object(schedules,'backtest',side_effect=failure) as evaluate:
                with self.assertRaises(type(failure)):
                    self.service.calculate('custom',self.options,None,None,admission='queue')
                evaluate.assert_called_once()
        def configuration(value):raise ValueError('callback failure')
        with self.assertRaisesRegex(ValueError,'callback failure'):
            self.service.calculate('random',dict(self.options,trials=2),None,configuration)
        self.assertEqual(self.closures,[True]*3)
        self.assertFalse(getattr(self.owner.state,'held',False))
        with patch.object(cache_access,'access',side_effect=ValueError('not contention')) as access:
            with self.assertRaisesRegex(ValueError,'not contention'):
                self.service.calculate('custom',self.options,None,None,admission='queue')
            access.assert_called_once()

    def test_unavailable_admitted_inputs_remain_a_legacy_503(self):
        self.service.ready=lambda:False
        for path in ('/api/schedule','/api/robustness'):
            handler=self.handler(path,self.options);handler.do_POST()
            self.assertEqual(handler.replies[0][0],503);self.assertEqual(handler.statuses,[])
        self.assertEqual(self.closures,[])

    def test_legacy_errors_before_and_after_stream_headers_and_summary_capture(self):
        invalid=self.handler('/api/robustness',dict(self.options,trials=0));invalid.do_POST()
        self.assertEqual(invalid.replies[0][0],400);self.assertEqual(invalid.statuses,[])
        stream=self.handler('/api/robustness',dict(self.options,trials=2))
        with patch.object(robustness,'run',side_effect=ValueError('after planning')):stream.do_POST()
        self.assertEqual(stream.statuses,[200]);self.assertEqual(stream.replies,[])
        self.assertEqual([json.loads(line)['type'] for line in stream.wfile.getvalue().splitlines()],['configuration','error'])
        plain=self.handler('/api/robustness',dict(self.options,trials=2,seed=42))
        with patch.object(robustness,'run',wraps=robustness.run) as run:plain.do_POST()
        self.assertIsNone(run.call_args.kwargs['capture'])
        self.assertNotIn('trial_results',json.loads(plain.wfile.getvalue().splitlines()[-1])['result'])

    def test_legacy_disconnect_cleans_up_without_complete_frame(self):
        stream=self.handler('/api/robustness',dict(self.options,trials=2))
        class Disconnected(io.BytesIO):
            def write(self,value):raise BrokenPipeError()
        stream.wfile=Disconnected()
        with patch.object(robustness,'run') as run:stream.do_POST()
        run.assert_not_called();self.assertEqual(self.closures,[True]);self.assertEqual(stream.replies,[])

    def test_shutdown_rejects_a_late_http_body_before_any_calculation(self):
        body_entered=Event();release=Event();outcome=[]
        class Handler(serve.Handler):
            def log_message(self,*args):pass
            def disconnect_check(self):
                body_entered.set()
                if not release.wait(5):raise AssertionError('Late-body test did not release.')
                return lambda:False
        server=serve.Server(('127.0.0.1',0),Handler)
        self.service=server.calculations
        listener=Thread(target=server.serve_forever);listener.start()
        def send():
            client=HTTPConnection(*server.server_address,timeout=5)
            try:
                client.request('POST','/api/schedule',json.dumps(self.options))
                response=client.getresponse();outcome.append((response.status,json.loads(response.read())))
            finally:client.close()
        sender=Thread(target=send);sender.start()
        try:
            self.assertTrue(body_entered.wait(3));server.shutdown();listener.join(3)
            self.assertTrue(self.service.closed.is_set());release.set();sender.join(3)
            server.server_close();server.server_close()
            self.assertEqual(outcome[0][0],400);self.assertIn('stopping',outcome[0][1]['error'])
            self.assertEqual(self.closures,[])
        finally:
            release.set();sender.join(5)
            if listener.is_alive():server.shutdown();listener.join(5)
            server.server_close()


if __name__=='__main__':unittest.main()

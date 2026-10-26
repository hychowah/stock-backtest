"""Shared workspace ownership covers database use, closure and preparation."""
from contextlib import ExitStack
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website')]
import cache_access as access
import research
import schedules
import serve


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.path=root/'workspace.lock'
        self.owner=access.WorkspaceAccess(self.path)
        self.context.enter_context(patch.object(access,'workspace',self.owner))

    def probe(self):
        return subprocess.run([sys.executable,str(Path(__file__).resolve()),'probe',str(self.path)],capture_output=True,text=True,timeout=15).returncode

    def test_reentrant_preparation_and_other_process_exclusion(self):
        calls=[]
        @access.exclusive
        def nested():calls.append('nested')
        with access.access():
            nested()
            self.assertEqual(self.probe(),2)
        self.assertEqual(calls,['nested']);self.assertEqual(self.probe(),0)

    def test_release_after_exception(self):
        with self.assertRaisesRegex(RuntimeError,'failure'):
            with access.access():raise RuntimeError('failure')
        self.assertEqual(self.probe(),0)

    def test_preparation_entrypoints_take_shared_ownership(self):
        self.assertTrue(hasattr(research.prepare,'__wrapped__'))
        self.assertTrue(hasattr(schedules.prepare,'__wrapped__'))
        for prepare in (research.prepare,schedules.prepare):
            class Entered(Exception):pass
            with patch.object(access,'access',side_effect=Entered),self.assertRaises(Entered):prepare()

    def test_fixed_and_random_requests_hold_ownership_through_database_close(self):
        for path in ('/api/schedule','/api/robustness'):
            with self.subTest(path=path):
                entered=Event();finish=Event();responses=[];close_probes=[];errors=[]
                db=SimpleNamespace(execute=lambda *a:None,close=lambda:close_probes.append(self.probe()))
                def calculate(*args,**kwargs):entered.set();finish.wait(10);return {'result':'complete'}
                handler=object.__new__(serve.Handler)
                handler.disconnect_check=lambda:lambda:False
                handler.path=path;handler.client_address=('127.0.0.1',1)
                handler.server=SimpleNamespace();handler.headers={'Host':'127.0.0.1:3000','Content-Length':'2'}
                handler.rfile=io.BytesIO(b'{}');handler.reply=lambda status,payload:responses.append(status)
                handler.stream_batch=calculate
                def request():
                    try:handler.do_POST()
                    except BaseException as error:errors.append(error)
                with patch.object(schedules,'connect',return_value=db),patch.object(schedules,'backtest',side_effect=calculate),patch.object(serve.robustness,'plan',return_value={}):
                    thread=Thread(target=request);thread.start()
                    try:
                        self.assertTrue(entered.wait(5))
                        self.assertEqual(self.probe(),2,'A second server must not rebuild during calculation or streaming.')
                    finally:finish.set();thread.join(20)
                self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
                self.assertEqual(close_probes,[2],'Ownership must remain held while the DB closes.')
                self.assertEqual(self.probe(),0)
                if path.endswith('schedule'):self.assertEqual(responses,[200])


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='probe':
        try:
            with access.WorkspaceAccess(Path(sys.argv[2])).hold(timeout=.15):pass
        except ValueError:sys.exit(2)
    else:unittest.main()

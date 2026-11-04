"""Shared workspace ownership covers database use, closure and preparation."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.application import original_calculations
from backtest.application.original_calculations import Original
from backtest.inputs import daily
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT)]
from backtest.runtime import cache_access as access
from backtest.inputs import research as research
from backtest.engines.original import schedules as schedules
from backtest.application import jobs as backtest_jobs
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
        self.assertTrue(hasattr(daily.prepare,'__wrapped__'))
        for prepare in (research.prepare,daily.prepare):
            class Entered(Exception):pass
            with patch.object(access,'access',side_effect=Entered),self.assertRaises(Entered):prepare()

    def test_fixed_and_random_runs_hold_ownership_through_database_close(self):
        for mode in ('custom','random'):
            with self.subTest(mode=mode):
                entered=Event();finish=Event();close_probes=[]
                db=SimpleNamespace(execute=lambda *a:[],close=lambda:close_probes.append(self.probe()))
                def calculate(*args,**kwargs):entered.set();finish.wait(10);return {'result':'complete'}
                jobs=backtest_jobs.Jobs(Original())
                with patch.object(daily,'connect',return_value=db),patch.object(schedules,'backtest',side_effect=calculate),patch.object(original_calculations.robustness,'plan',return_value={'options':{}}),patch.object(original_calculations.robustness,'run',side_effect=calculate):
                    jobs.start('a'*32,mode,{});thread=jobs.runs['a'*32]['thread']
                    try:
                        self.assertTrue(entered.wait(5))
                        self.assertEqual(self.probe(),2,'A second server must not rebuild during calculation.')
                    finally:finish.set();thread.join(20)
                self.assertFalse(thread.is_alive());jobs.close()
                self.assertEqual(close_probes,[2],'Ownership must remain held while the DB closes.')
                self.assertEqual(self.probe(),0)


@unittest.skipUnless(sys.platform=='win32','Native LockFileEx reader-gate verification.')
class NativeReaderGateTests(unittest.TestCase):
    def test_multiple_readers_exclude_retirement_and_exclusive_excludes_attach(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as handles:
            path=Path(folder)/'mapping-gate.lock';path.write_bytes(b'0')
            first=handles.enter_context(path.open('rb',buffering=0))
            second=handles.enter_context(path.open('rb',buffering=0))
            exclusive=handles.enter_context(path.open('r+b',buffering=0))
            release_first=access._windows_reader_lock(first,False)
            release_second=access._windows_reader_lock(second,False)
            try:
                with self.assertRaises(BlockingIOError):access._windows_reader_lock(exclusive,True)
                release_first();release_first=None
                with self.assertRaises(BlockingIOError):access._windows_reader_lock(exclusive,True)
            finally:
                if release_first is not None:release_first()
                release_second()
            release_exclusive=access._windows_reader_lock(exclusive,True)
            try:
                with self.assertRaises(BlockingIOError):access._windows_reader_lock(first,False)
            finally:release_exclusive()
            access._windows_reader_lock(first,False)()


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='probe':
        try:
            with access.WorkspaceAccess(Path(sys.argv[2])).hold(timeout=.15):pass
        except ValueError:sys.exit(2)
    else:unittest.main()

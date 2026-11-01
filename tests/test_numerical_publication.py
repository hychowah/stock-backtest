"""Atomic runtime protocol publication, including actual Windows sharing handles."""
import errno
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).absolute().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import backtest_control as backtest_control
from backtest.engines.numerical import runtime as runtime


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'stats.json';self.path.write_text('{"old":true}')

    def denied(self, code=32):
        error=PermissionError(errno.EACCES,'PRIVATE-PATH-AND-EXCEPTION-CANARY')
        error.winerror=code
        return error

    def test_transient_replacement_preserves_previous_value_until_success(self):
        original=Path.replace;calls=[]
        def replace(pending,destination):
            calls.append(1)
            self.assertEqual(json.loads(self.path.read_bytes()),{'old':True})
            self.assertEqual(json.loads(pending.read_bytes()),{'new':True})
            if len(calls)<3:raise self.denied()
            return original(pending,destination)
        with patch.object(Path,'replace',replace),patch.object(runtime,'PUBLISH_RETRY_DELAYS',(.001,.001)):
            runtime.write_payload(self.path,{'new':True},100)
        self.assertEqual(len(calls),3);self.assertEqual(json.loads(self.path.read_bytes()),{'new':True})
        self.assertFalse(self.path.with_suffix('.pending').exists())

    def test_permanent_pending_and_replace_failures_are_bounded_and_safe(self):
        for phase in ('pending-write','replace'):
            with self.subTest(phase=phase):
                began=time.monotonic()
                patcher=patch.object(runtime,'_pending_write',side_effect=self.denied(5)) if phase=='pending-write' else patch.object(Path,'replace',side_effect=self.denied())
                with patcher as call,patch.object(runtime,'PUBLISH_RETRY_DELAYS',(.001,)*7):
                    with self.assertRaises(PermissionError) as caught:runtime.write_payload(self.path,{'new':1},100)
                self.assertEqual(call.call_count,8);self.assertLess(time.monotonic()-began,1)
                self.assertEqual(caught.exception.numerical_publication['phase'],phase)
                self.assertEqual(caught.exception.numerical_publication['role'],'statistics')
                self.assertEqual(json.loads(self.path.read_bytes()),{'old':True})

    def test_unrelated_errors_and_bounds_do_not_retry(self):
        for error in (OSError(errno.ENOSPC,'private'),self.denied(1314),PermissionError(errno.EACCES,'private')):
            with patch.object(Path,'replace',side_effect=error) as call:
                with self.assertRaises(OSError):runtime.write_payload(self.path,{'new':1},100)
                self.assertEqual(call.call_count,1)
        with patch.object(Path,'open') as call:
            with self.assertRaises(ValueError):runtime.write_payload(self.path,{'large':'x'*100},10)
            call.assert_not_called()

    def test_cancellation_interrupts_retry_wait_before_second_attempt(self):
        calls=0
        def checkpoint():
            nonlocal calls
            calls+=1
            if calls>=3:raise backtest_control.Cancelled()
        with patch.object(Path,'replace',side_effect=self.denied()) as call:
            with self.assertRaises(backtest_control.Cancelled):runtime.write_payload(self.path,{'new':1},100,checkpoint=checkpoint)
            self.assertEqual(call.call_count,1)
        self.assertEqual(json.loads(self.path.read_bytes()),{'old':True})

    @unittest.skipUnless(os.name=='nt','Native Windows sharing semantics required.')
    def test_real_handle_denial_pending_write_and_destination_replacement(self):
        import ctypes as c
        from ctypes import wintypes as w
        kernel=c.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
        kernel.CreateFileW.restype=w.HANDLE
        kernel.CloseHandle.argtypes=[w.HANDLE]
        for phase in ('pending-write','replace'):
            with self.subTest(phase=phase):
                target=self.path.with_suffix('.pending') if phase=='pending-write' else self.path
                target.write_text('{"locked":true}')
                # READ sharing permits observation but denies WRITE and DELETE.
                handle=kernel.CreateFileW(str(target),0x80000000,1,None,3,0,None)
                self.assertNotEqual(handle,c.c_void_p(-1).value)
                released=[]
                def release():time.sleep(.12);released.append(bool(kernel.CloseHandle(handle)))
                worker=Thread(target=release);worker.start()
                try:
                    with patch('backtest.runtime.diagnostics.event') as events:runtime.write_payload(self.path,{'new':phase},100)
                finally:worker.join()
                self.assertEqual(released,[True])
                self.assertTrue(events.called)
                self.assertEqual(events.call_args.kwargs['phase'],phase)
                self.assertIn(events.call_args.kwargs['winerror'],(5,32,33))
                self.assertEqual(json.loads(self.path.read_bytes()),{'new':phase})
                print(json.dumps(dict(check='native-publication-sharing',phase=phase,winerror=events.call_args.kwargs['winerror'],closed=True)),flush=True)

    @unittest.skipUnless(os.name=='nt','Native Windows sharing semantics required.')
    def test_real_permanent_replacement_denial_keeps_previous_and_pending(self):
        import ctypes as c
        from ctypes import wintypes as w
        kernel=c.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
        kernel.CreateFileW.restype=w.HANDLE;kernel.CloseHandle.argtypes=[w.HANDLE]
        handle=kernel.CreateFileW(str(self.path),0x80000000,1,None,3,0,None)
        self.assertNotEqual(handle,c.c_void_p(-1).value)
        began=time.monotonic()
        try:
            with self.assertRaises(PermissionError) as caught:runtime.write_payload(self.path,{'new':True},100)
            self.assertIn(caught.exception.winerror,(5,32,33))
            self.assertEqual(json.loads(self.path.read_bytes()),{'old':True})
            self.assertEqual(json.loads(self.path.with_suffix('.pending').read_bytes()),{'new':True})
        finally:self.assertTrue(kernel.CloseHandle(handle))
        self.assertLess(time.monotonic()-began,4)

if __name__=='__main__':unittest.main()

"""Worker control transport stays outside dense calculation checkpoints."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from threading import Event,Thread,get_ident
import json
import os
import subprocess
import time
import unittest
from unittest.mock import patch

from backtest.engines.numerical import trial_worker
from backtest.runtime import backtest_control
from backtest.variables import evaluation


class WorkerControlTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory(prefix='cv-worker-control-')
        self.addCleanup(self.folder.cleanup)
        self.marker=Path(self.folder.name)/'cancel'

    @contextmanager
    def observer(self,*,seconds=.1):
        control=trial_worker._Control(self.marker);parent=Event()
        thread=Thread(target=control.observe,args=(lambda:parent.wait(.05),seconds),
            name='private-worker-control')
        thread.start()
        try:
            self.assertTrue(control.ready.wait(2),'Control observer did not become ready.')
            yield control,parent,thread
        finally:
            control.finished.set();thread.join(2)
            self.assertFalse(thread.is_alive(),'Control observer closure is unconfirmed.')

    def wait_cancelled(self,control):
        self.assertTrue(control.stopped.wait(2),'Terminal marker was not observed.')
        self.assertTrue(control.cancelled())

    def test_preexisting_marker_prevents_admitted_work(self):
        self.marker.touch()
        with self.observer() as (control,parent,thread):
            admitted=[]
            with self.assertRaises(backtest_control.Cancelled):
                with backtest_control.cancel_when(control.cancelled):admitted.append(True)
            self.assertFalse(admitted)
            self.assertTrue(thread.is_alive())

    def test_real_entry_preexisting_marker_precedes_financial_and_native_imports(self):
        root=Path(__file__).resolve().parents[1]
        self.marker.touch();configuration=Path(self.folder.name)/'worker.json'
        configuration.write_text(json.dumps(dict(source_root=str(root),scratch=self.folder.name,close_seconds=2)))
        entry=root/'backtest/engines/numerical/trial_worker.py'
        code=r'''
import importlib.abc,runpy,sys
from pathlib import Path
root=Path(sys.argv[1]);entry=root/'backtest/engines/numerical/trial_worker.py'
if sys.platform=='win32':
    runpy.run_path(str(root/'tests/guarded_numerical_entries.py'),run_name='_private_numerical_entries')['install'](root)
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('backtest.financial','backtest.inputs','backtest.engines')):
            raise AssertionError('Financial/native import preceded terminal cancellation')
sys.meta_path.insert(0,Block())
sys.argv=[str(entry),*sys.argv[2:]]
runpy.run_path(str(entry),run_name='__main__')
'''
        command=[sys.executable,'-I','-B','-c',code,str(root),str(configuration)]
        startup={};close=None
        if os.name=='nt':
            import ctypes as c
            from ctypes import wintypes as w
            kernel=c.WinDLL('kernel32',use_last_error=True)
            kernel.GetCurrentProcess.restype=w.HANDLE
            kernel.DuplicateHandle.argtypes=[w.HANDLE,w.HANDLE,w.HANDLE,c.POINTER(w.HANDLE),w.DWORD,w.BOOL,w.DWORD]
            kernel.CloseHandle.argtypes=[w.HANDLE]
            current=kernel.GetCurrentProcess();sentinel=w.HANDLE()
            self.assertTrue(kernel.DuplicateHandle(current,current,current,c.byref(sentinel),0x100000,True,0))
            information=subprocess.STARTUPINFO();information.lpAttributeList=dict(handle_list=[sentinel.value])
            startup['startupinfo']=information;command+=['handle',str(sentinel.value)]
            close=lambda:kernel.CloseHandle(sentinel)
        else:
            reader,writer=os.pipe();startup['pass_fds']=(reader,);command+=['pipe',str(reader)]
            close=lambda:os.close(reader)
            self.addCleanup(os.close,writer)
        try:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**startup)
        finally:close()
        try:
            output,error=process.communicate(timeout=20)
            self.assertEqual(process.returncode,0,error.decode(errors='replace'))
            events=[json.loads(line) for line in output.splitlines()]
            self.assertEqual([item['event'] for item in events],['stage','cancelled','closed'])
            self.assertEqual(events[0]['stage'],'source-owned')
            self.assertEqual(events[1]['error_type'],'Cancelled')
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
            for stream in (process.stdout,process.stderr):
                if stream is not None:stream.close()
            if os.name=='nt':process._handle.Close()

    def test_checkpoint_predicate_performs_only_memory_reads(self):
        with self.observer() as (control,parent,thread):
            control.finished.set();thread.join(2)
            with patch.object(Path,'stat',side_effect=AssertionError('No checkpoint filesystem probe')):
                for index in range(200000):self.assertFalse(control.cancelled())

    def test_dense_real_encoding_observes_marker_on_control_thread(self):
        ordinary=Path.stat;probes=[];checkpoints=0;caller=get_ident()
        def observed(path,*args,**kwargs):
            if path==self.marker:probes.append(get_ident())
            return ordinary(path,*args,**kwargs)
        with patch.object(Path,'stat',observed),self.observer() as (control,parent,thread):
            began=Event();created=[]
            def publish():
                if began.wait(2):
                    created.append(time.perf_counter());self.marker.touch()
            publisher=Thread(target=publish,name='private-marker-publisher');publisher.start()
            self.addCleanup(publisher.join,2)
            def checkpoint():
                nonlocal checkpoints
                checkpoints+=1
                if checkpoints>=10000:began.set()
                backtest_control.checkpoint()
            with self.assertRaises(backtest_control.Cancelled):
                with backtest_control.cancel_when(control.cancelled):
                    deadline=time.monotonic()+3
                    while time.monotonic()<deadline:
                        evaluation._encode([dict(value=i,reason=None) for i in range(20000)],
                            evaluation.CEILINGS['output_bytes'],checkpoint)
            stopped=time.perf_counter();publisher.join(2)
            self.assertEqual(len(created),1)
            self.assertLess(stopped-created[0],2)
            self.assertGreater(checkpoints,10000)
            self.assertTrue(probes)
            self.assertNotIn(caller,probes)
            self.assertGreater(checkpoints,100*len(probes))

    def test_marker_cancellation_stays_latched_after_removal(self):
        with self.observer() as (control,parent,thread):
            self.marker.touch();self.wait_cancelled(control);self.marker.unlink()
            self.assertTrue(control.cancelled())
            self.assertTrue(thread.is_alive())

    def test_marker_observation_failure_aborts_and_observer_closes(self):
        ordinary=Path.stat;failure=PermissionError('Private marker observation failure')
        def failed(path,*args,**kwargs):
            if path==self.marker:raise failure
            return ordinary(path,*args,**kwargs)
        with patch.object(Path,'stat',failed),self.observer() as (control,parent,thread):
            with self.assertRaises(PermissionError) as caught:
                with backtest_control.cancel_when(control.cancelled):self.fail('Work admitted after control failure.')
            self.assertIs(caught.exception,failure)
            self.assertTrue(thread.is_alive())

    def test_marker_then_parent_loss_keeps_existing_terminal_safeguard(self):
        forced=Event();codes=[]
        def exited(code):codes.append(code);forced.set()
        with patch.object(trial_worker.os,'_exit',side_effect=exited),self.observer(seconds=.05) as (control,parent,thread):
            self.marker.touch();self.wait_cancelled(control)
            self.assertFalse(forced.is_set())
            parent.set()
            self.assertTrue(forced.wait(2),'Marker cancellation removed parent-loss protection.')
            self.assertEqual(codes,[72])
            thread.join(2)
            self.assertFalse(thread.is_alive())


if __name__=='__main__':unittest.main()

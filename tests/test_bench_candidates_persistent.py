"""Read-only mapped inputs and loaded-worker request/lifetime checks."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.financial import rules
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_bench_methods as shared
import numpy as np
from tools.experiments.bench_candidates import NumericInputs, PythonExecutor
import tools.experiments.bench_candidates_persistent as backend
class PersistentTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing source-policy fixture without inheriting its
        # unrelated adapter tests. It creates no production cache.
        self.fixture = shared.SharedMethodsTests('test_empty_trials_remain_visible_and_excluded_from_distributions')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.inputs = NumericInputs(self.fixture.reader, shared.s)
        self.addCleanup(self.inputs.close)
        self.root = self.fixture.root

    def options(self, pool='legacy', profile='F0'):
        return dict(shared.baseline.options(pool, profile), min_cap=0., min_ev=0.)

    def request(self, options):
        return dict(options=options)

    def books(self, pool='legacy'):
        return [('2015-01-02','2015-06-01',pool),
                ('2015-06-01','2016-01-04',pool),
                ('2016-01-04','2016-12-30',pool)]

    def test_export_reopens_readonly_without_private_price_copy(self):
        path = backend.export_inputs(self.inputs, self.root/'mapped')
        reopened = backend.open_inputs(path, shared.s)
        self.addCleanup(backend.close_inputs, reopened)
        self.assertIsInstance(reopened.raw_values,np.memmap)
        self.assertFalse(reopened.raw_values.flags.writeable)
        np.testing.assert_array_equal(reopened.raw_days,self.inputs.raw_days)
        np.testing.assert_array_equal(reopened.raw_values,self.inputs.raw_values)
        self.assertEqual(reopened.policy.signature,self.inputs.policy.signature)
        with self.assertRaises(ValueError):
            reopened.raw_values[0] = 123.
        mappings = reopened._persistent_mappings
        backend.close_inputs(reopened)
        self.assertTrue(all(array._mmap.closed for array in mappings))

    def test_export_rejects_tampered_metadata_and_buffers(self):
        path = backend.export_inputs(self.inputs, self.root/'tampered')
        manifest = json.loads(path.read_text())
        state = path.parent/manifest['state']
        original = state.read_bytes()
        state.write_bytes(original+b'changed')
        with self.assertRaisesRegex(ValueError,'metadata changed'):
            backend.open_inputs(path, shared.s)
        state.write_bytes(original)
        buffer = path.parent/next(iter(manifest['arrays']))
        with buffer.open('ab') as handle:
            handle.write(b'changed')
        with self.assertRaisesRegex(ValueError,'buffer content changed'):
            backend.open_inputs(path, shared.s)

    def test_loaded_workers_match_both_pools_and_reuse_processes_for_fresh_requests(self):
        limits = dict(workers=2,workdir=self.root/'workers',capture=True,setup_seconds=60.)
        executor = backend.attach(self.inputs,limits=limits)
        self.addCleanup(executor.close)
        pids = tuple(sorted(executor.stats['worker_pids']))
        self.assertEqual(len(set(pids)),2)
        ordinary = PythonExecutor(self.inputs,limits=dict(capture=True))
        self.addCleanup(ordinary.close)
        for pool,profile in [('legacy','F0'),('cached','F1'),('legacy','F2')]:
            options = self.options(pool,profile)
            request = self.request(options)
            ordinary.limits['capture'] = executor.limits['capture'] = profile != 'F1'
            ordinary.begin(request)
            executor.begin(request)
            expected = ordinary.evaluate(self.books(pool),options=options)
            actual = executor.evaluate(self.books(pool),options=options)
            self.assertTrue(shared.baseline.compare(expected,actual)['exact'])
            self.assertEqual(tuple(sorted(executor.stats['worker_pids'])),pids)
            for key,value in ordinary.trace.items():
                np.testing.assert_allclose(executor.trace[key],value,rtol=1e-12,atol=1e-12,equal_nan=True,
                                           err_msg=key)
            if profile == 'F1':self.assertEqual(executor.trace,{})
        self.assertEqual(executor.stats['requests'],3)
        directory = executor._directory
        executor.close()
        self.assertFalse(directory.exists())
        self.assertIsNone(executor._pool)
        with self.assertRaisesRegex(RuntimeError,'closed'):
            executor.begin(self.request(self.options()))

    def test_worker_limit_and_request_lifecycle_are_explicit(self):
        with self.assertRaisesRegex(ValueError,'between one and four'):
            backend.attach(self.inputs,limits=dict(workers=5,workdir=self.root/'bad'))
        executor = backend.attach(self.inputs,limits=dict(workers=1,workdir=self.root/'one',setup_seconds=60.))
        self.addCleanup(executor.close)
        with self.assertRaisesRegex(RuntimeError,'Begin a fresh request'):
            executor.evaluate(self.books())
        executor.begin(self.request(self.options()))
        self.assertEqual(executor.evaluate([]),[])
        executor.deadline = 0.00001
        with self.assertRaisesRegex(TimeoutError,'request budget'):
            executor.evaluate(self.books())

    def test_spawn_preserves_frozen_source_bankruptcy_override(self):
        with patch.object(rules,'BANKRUPT',{(2015,'A')}):
            frozen = NumericInputs(self.fixture.reader,shared.s)
        self.addCleanup(frozen.close)
        executor = backend.attach(frozen,limits=dict(workers=1,workdir=self.root/'bankruptcy',setup_seconds=60.))
        self.addCleanup(executor.close)
        options = self.options()
        request = self.request(options)
        executor.begin(request)
        actual = executor.evaluate(self.books(),options=options)
        ordinary = PythonExecutor(frozen)
        self.addCleanup(ordinary.close)
        ordinary.begin(request)
        expected = ordinary.evaluate(self.books(),options=options)
        self.assertTrue(shared.baseline.compare(expected,actual)['exact'])
        position = next(row for row in actual[0]['snapshots'] if row[0]=='A')
        self.assertEqual(position[-2:],(-1.,'Bankruptcy'))

    def test_forced_parent_exit_stops_loaded_workers(self):
        ready = self.root/'orphan-check.json'
        code = textwrap.dedent('''
            import json, sqlite3, sys, time
            from pathlib import Path
            sys.path.insert(0,str(Path(sys.argv[1])))
            import tools.experiments.bench_baseline as baseline
            baseline.bootstrap(sys.argv[2])
            from tools.experiments.bench_candidates import NumericInputs
            from tools.experiments.bench_candidates_persistent import attach
            db=sqlite3.connect(Path(sys.argv[3]).resolve().as_uri()+'?mode=ro',uri=True)
            db.row_factory=sqlite3.Row
            inputs=NumericInputs(db,baseline.s)
            executor=attach(inputs,limits=dict(workers=2,workdir=sys.argv[4],setup_seconds=30.))
            Path(sys.argv[5]).write_text(json.dumps(executor.stats['worker_pids']))
            while True: time.sleep(.1)
        ''')
        command = [sys.executable,'-c',code,str(ROOT),str(shared.RUNTIME),str(self.fixture.path),
                   str(self.root/'orphan-workers'),str(ready)]
        process = subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        pids = []
        try:
            deadline = time.monotonic()+30.
            while not ready.exists() and process.poll() is None and time.monotonic()<deadline:
                time.sleep(.05)
            if not ready.exists():
                if process.poll() is None:process.kill()
                output,error = process.communicate(timeout=10)
                self.fail('Owned worker host failed to start: '+output+error)
            pids = json.loads(ready.read_text())
            self.assertEqual(len(pids),2)
            process.kill()
            process.communicate(timeout=10)
            deadline = time.monotonic()+10.
            while any(_alive(pid) for pid in pids) and time.monotonic()<deadline:
                time.sleep(.05)
            self.assertFalse(any(_alive(pid) for pid in pids),'Loaded workers survived their parent.')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
            for pid in pids:
                if _alive(pid):
                    os.kill(pid,signal.SIGTERM)


def _alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p,ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000|0x1000,False,pid)
        if not handle:return False
        try:return kernel.WaitForSingleObject(handle,0) != 0
        finally:kernel.CloseHandle(handle)
    try:
        os.kill(pid,0)
        state = Path('/proc')/str(pid)/'stat'
        return not state.exists() or state.read_text().split(') ',1)[1][0] != 'Z'
    except ProcessLookupError:
        return False


if __name__ == '__main__':
    unittest.main()

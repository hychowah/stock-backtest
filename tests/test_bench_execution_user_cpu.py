"""Cumulative native user CPU qualification on disposable processes only.

These are periodic kernel termination thresholds, not exact caps. No WSL total
CPU or outside-supervisor guarantee follows. No financial or installed assets.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from bench_candidates_process import OwnedProcess, ProcessLimits, _pending_processes, user_cpu_ticks
from bench_execution_domain import DomainLimits, start_controller
from bench_execution import ExecutionEnvelope, environment
from bench_comparison import ComparisonProtocol, ComparisonError

# process_time includes kernel time. GetProcessTimes lets finite fixtures target
# user time specifically. A large pure-Python loop supplies most of that time.
USER_CLOCK = '''import ctypes
from ctypes import wintypes as w
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.GetCurrentProcess.restype=w.HANDLE
kernel.GetProcessTimes.argtypes=[w.HANDLE]+[ctypes.POINTER(w.FILETIME)]*4
def user_time():
 values=[w.FILETIME() for _ in range(4)]
 if not kernel.GetProcessTimes(kernel.GetCurrentProcess(),*[ctypes.byref(v) for v in values]):raise ctypes.WinError(ctypes.get_last_error())
 return ((values[3].dwHighDateTime<<32)|values[3].dwLowDateTime)/10000000
'''


def burn(seconds):
    return USER_CLOCK + '\nbegan=user_time()\nwhile user_time()-began<' + repr(seconds) + ':\n for i in range(20000): value=i*i\n'


class DeclarationTests(unittest.TestCase):
    def test_finite_representable_budget_and_environment_identity(self):
        original = ExecutionEnvelope(1024, 1024, 1024, 10., 1, user_cpu_seconds=2.)
        changed = replace(original, user_cpu_seconds=3.)
        def protocol(e):
            return ComparisonProtocol.freeze(configuration={'samples': [['2015-01-02','2015-02-02']],
                'requested': 1}, binding={'fixture': True}, environment=environment(e),
                costs=dict.fromkeys(('attachment','clone','setup','proof','request','collection','shutdown','finalization'), 1.),
                whole_seconds=10., max_control_drift=2., max_bracket_seconds=9.)
        self.assertNotEqual(protocol(original).identity, protocol(changed).identity)
        # The outer operation budget must never be restarted on each worker.
        self.assertIsNone(original.process_limits().user_cpu_seconds)
        for value in (None, True, 0, -1, float('nan'), float('inf'), 1e-10, 2**63/1e7, 10**1000):
            with self.subTest(value=str(value)):
                with self.assertRaises(ValueError): user_cpu_ticks(value)
                with self.assertRaises(ComparisonError): replace(original, user_cpu_seconds=value)
                with self.assertRaises(ValueError): DomainLimits(1024, 4, 25, 10., value)
        self.assertEqual(user_cpu_ticks(.25), 2500000)


@unittest.skipUnless(os.name == 'nt', 'Native Job Object cumulative user CPU')
class NativeUserCpuTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cb02-user-cpu-fixture-')
        self.root = Path(self.temporary.name)
        self.owners = []
        def cleanup():
            for owner in self.owners: owner.close()
            if not all(owner.closed for owner in self.owners):
                raise TimeoutError('Synthetic CPU fixture ownership remains pending.')
            self.temporary.cleanup()
        self.addCleanup(cleanup)

    def launch(self, body, seconds=1., go=True):
        path = self.root / ('controller-' + str(len(self.owners)) + '.py')
        path.write_text('import json,os,sys,time,subprocess\n' + body, encoding='utf-8')
        owner = start_controller([sys.executable, '-X', 'utf8', '-B', str(path)],
            DomainLimits(256*1024**2, 32, 25, 15., seconds, processes=8, close_seconds=2.))
        self.owners.append(owner)
        if go: owner.start()
        return owner

    def event(self, owner, name):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            event = owner.event(.02)
            if event and event.get('event') == name: return event
            if event is None and owner.process.poll() is not None: break
        self.fail('Missing synthetic CPU event ' + name)

    def exhausted(self, owner):
        # No owner polling or GO checkpoints cause the kernel termination.
        owner.process.wait(timeout=12)
        owner.close()
        facts = owner.closure()
        self.assertTrue(facts['closed'])
        self.assertTrue(facts['user_cpu']['exceeded'])
        self.assertEqual(owner.failure, 'limit')
        self.assertGreaterEqual(facts['user_cpu']['accounting']['user_ticks'],
                                facts['user_cpu']['configuration']['ticks'])
        print(json.dumps(dict(check='native_user_cpu_exhaustion', closure=facts)), flush=True)
        return facts

    def test_effective_limits_precede_resume_and_ordinary_completion_retains_accounting(self):
        resume = OwnedProcess._resume
        checks = []
        def verify(owner):
            checks.append(owner._user_cpu_configuration.copy())
            self.assertFalse(owner._resumed)
            self.assertFalse((self.root / 'application').exists())
            self.assertEqual(owner._account_job()['user_ticks'], 0)
            resume(owner)
        with patch.object(OwnedProcess, '_resume', verify):
            owner = self.launch('from pathlib import Path\nassert input()=="GO"\n'
                'Path(' + repr(str(self.root / 'application')) + ').touch()\n' + burn(.1), seconds=6.)
        owner.process.wait(timeout=8); owner.close()
        self.assertEqual(owner.process.returncode, 0)
        self.assertIsNone(owner.failure)
        self.assertTrue(checks[0]['verified_before_resume'])
        self.assertEqual(checks[0]['ticks'], 60000000)
        self.assertEqual(checks[0]['end_action'], 0)
        self.assertTrue(checks[0]['limit_flags'] & 4)
        self.assertFalse(owner.closure()['user_cpu']['exceeded'])
        self.assertIsNotNone(owner.closure()['user_cpu']['accounting'])
        self.assertGreaterEqual(owner.closure()['user_cpu']['accounting']['user_ticks'], 1000000)
        # Evidence consumers cannot change the retained threshold or counters.
        receipt = owner.closure()['user_cpu']
        receipt['configuration']['ticks'] = 1
        receipt['accounting']['user_ticks'] = 0
        self.assertEqual(owner.closure()['user_cpu']['configuration']['ticks'], 60000000)
        self.assertGreaterEqual(owner.closure()['user_cpu']['accounting']['user_ticks'], 1000000)

    def test_failed_effective_query_prevents_bootstrap_and_uses_registered_cleanup(self):
        verify = OwnedProcess._verify_user_cpu
        owners = []
        def fail(owner):
            owners.append(owner)
            query = owner.kernel.QueryInformationJobObject
            owner.kernel.QueryInformationJobObject = lambda *args: False
            try: verify(owner)
            finally: owner.kernel.QueryInformationJobObject = query
        marker = self.root / 'must-not-exist'
        with patch.object(OwnedProcess, '_verify_user_cpu', fail):
            with self.assertRaises(OSError):
                self.launch('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        self.assertFalse(marker.exists())
        self.assertFalse(owners[0]._resumed)
        self.assertTrue(owners[0].closed)
        self.assertNotIn(id(owners[0]), _pending_processes)

    def test_bootstrap_cpu_before_go_is_charged(self):
        owner = self.launch(burn(30.), seconds=.2, go=False)
        self.exhausted(owner)

    def test_blocked_controller_and_detached_compiler_share_budget(self):
        owner = self.launch('assert input()=="GO"\n'
            'subprocess.Popen([sys.executable,"-B","-c",' + repr(burn(30.)) + '],creationflags=8)\n'
            'print(json.dumps(dict(event="ready")),flush=True)\ntime.sleep(30)\n', seconds=.4)
        self.event(owner, 'ready')
        self.exhausted(owner)

    def test_sequential_exited_children_keep_one_cumulative_budget(self):
        child = burn(.35)
        owner = self.launch('assert input()=="GO"\n'
            'for i in range(30):\n'
            ' child=subprocess.Popen([sys.executable,"-B","-c",' + repr(child) + '])\n'
            ' child.wait()\n'
            ' print(json.dumps(dict(event="completed_child",index=i)),flush=True)\n'
            ' if i==0:time.sleep(.3)\n', seconds=1.2)
        self.event(owner, 'completed_child')
        first = owner._account_job()['user_ticks']
        self.assertGreaterEqual(first, 3500000)
        final = self.exhausted(owner)
        self.assertGreaterEqual(final['user_cpu']['accounting']['user_ticks'], first)
        self.assertGreater(final['user_cpu']['accounting']['total'], 2)

    def test_nested_worker_and_native_library_threads_charge_outer_job(self):
        # PBKDF2 runs in the native library. Threading does not create another
        # independent budget. The worker's own job has no user CPU threshold.
        library = ('import hashlib,threading\n'
            'def work():\n while True:hashlib.pbkdf2_hmac("sha256",b"x",b"y",200000)\n'
            'for i in range(2):threading.Thread(target=work).start()\n')
        worker = ('import subprocess,sys,time\nassert input()=="GO"\n'
            'subprocess.Popen([sys.executable,"-B","-c",' + repr(library) + '],creationflags=8)\n'
            'time.sleep(30)\n')
        nested = ('sys.path.insert(0,' + repr(str(ROOT / 'tools')) + ')\n'
            'from bench_candidates_process import OwnedProcess,ProcessLimits\n'
            'assert input()=="GO"\n'
            'child=OwnedProcess([sys.executable,"-B","-c",' + repr(worker) + '],'
            'limits=ProcessLimits(128*1024**2,6,25))\nchild.start()\n'
            'print(json.dumps(dict(event="nested")),flush=True)\ntime.sleep(30)\n')
        owner = self.launch(nested, seconds=.6)
        self.event(owner, 'nested')
        self.exhausted(owner)

    def test_exhaustion_and_partial_handle_failure_retain_accounting_until_retry(self):
        owner = self.launch(burn(30.), seconds=.3, go=False)
        owner.process.wait(timeout=12)
        def fail():
            for stream in (owner.process.stdin, owner.process.stdout):
                if not stream.closed: stream.close()
            raise OSError('Synthetic job handle close')
        with patch.object(owner, '_close_handles', fail):
            with self.assertRaises(OSError): owner.close()
        first = json.loads(json.dumps(owner.closure()['user_cpu']))
        self.assertTrue(first['exceeded'])
        self.assertFalse(owner.closed)
        self.assertIs(_pending_processes[id(owner)], owner)
        self.assertIsNotNone(owner.job)
        owner.close()
        self.assertEqual(first, owner.closure()['user_cpu'])
        self.assertTrue(owner.closed)
        self.assertNotIn(id(owner), _pending_processes)

    def test_cancellation_below_threshold_keeps_distinct_cause(self):
        owner = self.launch('assert input()=="GO"\nprint(json.dumps(dict(event="ready")),flush=True)\ntime.sleep(30)\n', seconds=6.)
        self.event(owner, 'ready')
        owner.terminate(); owner.close()
        self.assertIsNone(owner.failure)
        self.assertFalse(owner.closure()['user_cpu']['exceeded'])
        self.assertTrue(owner.closed)


if __name__ == '__main__': unittest.main()

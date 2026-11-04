"""Disposable exhaustion and lifetime probes; unsupported caps remain explicit."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest.runtime.process_owner import OwnedProcess, ProcessLimits, _pending_processes


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory(prefix='cb02-resource-')
        self.addCleanup(self.context.cleanup)
        self.root = Path(self.context.name)

    def worker(self, body, **changes):
        policy = dict(committed_bytes=256 * 1024**2, processes=4, cpu_percent=25,
                      output_bytes=128 * 1024, frame_bytes=4096, queued_events=16, close_seconds=2.)
        policy.update(changes)
        script = self.root / ('worker-' + str(len(list(self.root.iterdir()))) + '.py')
        script.write_text("import sys,subprocess,time,json,os\nassert input()=='GO'\n" + body, encoding='utf-8')
        owned = OwnedProcess([sys.executable, '-X', 'utf8', str(script)], limits=ProcessLimits(**policy))
        def cleanup():
            if not owned.closed:
                owned.terminate(); owned.close()
        self.addCleanup(cleanup)
        owned.start()
        return owned

    def event(self, owned, name):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            event = owned.event(timeout=.02)
            if event and event.get('event') == name: return event
            if owned.process.poll() is not None and event is None: break
        self.fail('Missing disposable event ' + name)

    def test_no_newline_frame_and_event_flood_stop_without_unbounded_queue(self):
        for body in ("sys.stdout.write('x'*100000);sys.stdout.flush();time.sleep(10)\n",
                     "for i in range(2000): print(json.dumps(dict(event='flood',i=i)),flush=True)\ntime.sleep(10)\n"):
            owned = self.worker(body)
            deadline = time.monotonic() + 5
            while not owned.failure and time.monotonic() < deadline: time.sleep(.01)
            self.assertEqual(owned.failure, 'limit')
            self.assertLessEqual(owned.events.qsize(), 16)
            owned.terminate(); owned.close()
            self.assertTrue(owned.closed)

    def test_eof_leader_exit_and_descendant_closure_are_separate(self):
        # The descendant closes stdout, so EOF+leader exit do not imply closure.
        owned = self.worker("child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\nprint(json.dumps(dict(event='child',pid=child.pid)),flush=True)\n")
        self.event(owned, 'child')
        owned.process.wait(timeout=5)
        owned.reader.join(timeout=2)
        self.assertTrue(owned.eof)
        self.assertFalse(owned.descendants_empty)
        owned.close()
        self.assertTrue(owned.closure()['descendants_empty'])
        self.assertTrue(owned.closed)

    def test_inherited_pipe_survives_leader_and_is_closed_by_owned_cleanup(self):
        owned = self.worker("subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])\nprint(json.dumps(dict(event='child')),flush=True)\n")
        self.event(owned, 'child'); owned.process.wait(timeout=5)
        self.assertTrue(owned.reader.is_alive())
        owned.close()
        self.assertTrue(owned.eof)
        self.assertTrue(owned.closed)

    def test_unconfirmed_descendants_keep_handles_for_cleanup_retry(self):
        owned = self.worker("print(json.dumps(dict(event='ready')),flush=True)\ntime.sleep(20)\n")
        self.event(owned, 'ready')
        with patch.object(owned, 'wait_empty', side_effect=TimeoutError('fixture closure')):
            with self.assertRaises(TimeoutError): owned.terminate()
            with self.assertRaises(TimeoutError): owned.close()
        self.assertFalse(owned.closed)
        self.assertFalse(owned.process.stdout.closed)
        owned.close(); self.assertTrue(owned.closed)

    def test_reader_start_failure_reaps_bootstrap_descendants(self):
        self.startup_failure(False)

    def test_initialization_cleanup_failure_retains_owner_until_retry(self):
        self.startup_failure(True)

    def test_reader_initialization_and_handle_close_failure_retry_after_eof(self):
        self.startup_failure('handles')

    def startup_failure(self, fail_close):
        script, marker = self.root / 'bootstrap.py', self.root / 'bootstrap-child'
        script.write_text("import subprocess,sys,time\nfrom pathlib import Path\nchild=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])\nPath(sys.argv[1]).write_text(str(child.pid))\nassert input()=='GO'\n")
        failure = RuntimeError('Synthetic reader startup failure')
        retained = []
        def fail_reader(thread):
            owner = thread._target.__self__
            retained.append(owner)
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue(marker.exists())
            raise failure
        from contextlib import ExitStack
        with ExitStack() as scope:
            scope.enter_context(patch('backtest.runtime.process_owner.Thread.start', fail_reader))
            if fail_close is True:
                scope.enter_context(patch.object(OwnedProcess, 'wait_empty', side_effect=TimeoutError('Synthetic closure')))
            elif fail_close == 'handles':
                def partial_close(owner):
                    for stream in (owner.process.stdin, owner.process.stdout):
                        if not stream.closed: stream.close()
                    raise OSError('Synthetic native job-handle close failure')
                scope.enter_context(patch.object(OwnedProcess, '_close_handles', partial_close))
            with self.assertRaises(RuntimeError) as caught:
                OwnedProcess([sys.executable, str(script), str(marker)],
                             limits=ProcessLimits(256 * 1024**2, 4, 25, close_seconds=1.))
            self.assertIs(caught.exception, failure)
        owner = retained[0]
        self.addCleanup(owner.close)
        if fail_close:
            self.assertIs(failure.owned_process, owner)
            self.assertIs(_pending_processes[id(owner)], owner)
            self.assertFalse(owner.closed)
            self.assertEqual(owner.process.stdout.closed, fail_close == 'handles')
            if fail_close == 'handles': self.assertTrue(owner.eof)
            owner.terminate(); owner.close()
        self.assertTrue(owner.closed)
        self.assertNotIn(id(owner), _pending_processes)

    def test_capability_report_does_not_promote_sampled_or_environment_caps(self):
        owned = self.worker("print(json.dumps(dict(event='ready')),flush=True)\ntime.sleep(20)\n")
        self.event(owned, 'ready')
        evidence = owned.capabilities()
        for field in ('resident_memory', 'threads', 'disk'):
            self.assertEqual(evidence[field]['status'], 'unsupported')
        for field in ('committed_memory', 'processes', 'cpu_rate'):
            self.assertEqual(evidence[field]['status'], 'hard' if os.name == 'nt' else 'unsupported')
        self.assertGreaterEqual(owned.tree_usage()['processes'], 1)
        print(json.dumps(dict(check='resource_capabilities', platform=sys.platform, evidence=evidence)), flush=True)

    @unittest.skipUnless(os.name == 'nt', 'Windows job limit probe')
    def test_native_descendant_memory_process_and_cpu_limits_are_applied(self):
        # Actual exhaustion, not an assertion about environment variables.
        owned = self.worker("child=subprocess.Popen([sys.executable,'-c',\"try:\\n x=bytearray(512*1024**2);print('unexpected')\\nexcept MemoryError:print('bounded')\"],stdout=subprocess.PIPE,text=True)\nprint(json.dumps(dict(event='memory',out=child.communicate()[0])),flush=True)\n")
        self.assertEqual(self.event(owned, 'memory')['out'].strip(), 'bounded')
        owned.close()
        limited = self.worker("try:\n child=subprocess.Popen([sys.executable,'-c',\"print('unexpected')\"],stdout=subprocess.PIPE,text=True);out=child.communicate()[0];result='bounded' if child.returncode or not out.strip() else 'unexpected'\nexcept OSError:result='bounded'\nprint(json.dumps(dict(event='process',result=result)),flush=True)\n", processes=2)
        self.assertEqual(self.event(limited, 'process')['result'], 'bounded')
        limited.close()
        from ctypes import wintypes as w
        import ctypes
        cpu = self.worker("print(json.dumps(dict(event='ready')),flush=True)\ntime.sleep(20)\n", cpu_percent=10)
        self.event(cpu, 'ready')
        class Rate(ctypes.Structure): _fields_ = [('flags',w.DWORD),('rate',w.DWORD)]
        rate = Rate()
        self.assertTrue(cpu.kernel.QueryInformationJobObject(cpu.job, 15, ctypes.byref(rate), ctypes.sizeof(rate), None))
        self.assertEqual((rate.flags, rate.rate), (5, 1000))

    @unittest.skipUnless(os.name == 'nt', 'Windows suspended-start probe')
    def test_native_interpreter_cannot_start_before_job_assignment(self):
        marker = self.root / 'early-interpreter.txt'
        script = self.root / 'early.py'
        # Deliberately runs before GO, as a venv/native bootstrap can do.
        script.write_text("from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('started')\nassert input()=='GO'\n")
        resume = OwnedProcess._resume
        def checked(owner):
            self.assertIsNotNone(owner.job)
            self.assertFalse(marker.exists())
            self.assertEqual(owner.tree_usage()['processes'], 1)
            return resume(owner)
        with patch.object(OwnedProcess, '_resume', checked):
            owned = OwnedProcess([sys.executable, str(script), str(marker)],
                                 limits=ProcessLimits(256 * 1024**2, 4, 25))
        self.addCleanup(owned.close)
        owned.start(); owned.process.wait(timeout=5); owned.close()
        self.assertTrue(marker.exists())
        self.assertTrue(owned.closed)

    def test_private_files_thread_growth_and_compiler_children_are_accounted(self):
        body = ("from threading import Thread,Event\nstop=Event()\n"
                "threads=[Thread(target=stop.wait,args=(10,)) for i in range(12)]\n"
                "for thread in threads:thread.start()\n"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])\n"
                "open(sys.argv[0]+'.compiler','wb').write(b'x'*1048576)\n"
                "print(json.dumps(dict(event='ready')),flush=True)\ntime.sleep(20)\n")
        owned = self.worker(body)
        self.event(owned, 'ready')
        usage = owned.tree_usage()
        self.assertGreaterEqual(usage['processes'], 2)
        self.assertGreaterEqual(usage['threads'], 13)
        self.assertEqual(sum(p.stat().st_size for p in self.root.glob('*.compiler')), 1048576)
        owned.terminate(); owned.close()
        self.root.rename(self.root.with_name(self.root.name + '-closed'))
        self.root.with_name(self.root.name + '-closed').rename(self.root)

    @unittest.skipIf(os.name == 'nt', 'Linux session escape probe')
    def test_observed_detached_child_is_rejected_and_owned_until_reaped(self):
        owned = self.worker("child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\nprint(json.dumps(dict(event='detached',pid=child.pid)),flush=True)\ntime.sleep(20)\n")
        self.event(owned, 'detached')
        self.assertGreaterEqual(owned.tree_usage()['processes'], 2)
        self.assertEqual(owned.failure, 'unsupported')
        self.assertFalse(owned.closed)
        owned.terminate(); owned.close()
        self.assertTrue(owned.closed)
        self.assertEqual(owned.capabilities()['containment']['status'], 'unsupported')


if __name__ == '__main__': unittest.main()

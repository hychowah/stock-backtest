"""Small disposable domain exhaustion/lifecycle probes; never use real assets."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest.runtime.process_owner import OwnedProcess, _pending_processes
from tools.experiments.bench_execution_domain import DomainLimits, start_controller
import tools.experiments.bench_execution_domain as domain
class DomainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cb02-domain-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def controller(self, body, **changes):
        values = dict(memory_bytes=128 * 1024**2, tasks=16, cpu_percent=10,
                      wall_seconds=12., user_cpu_seconds=8., processes=6,
                      output_bytes=128 * 1024, close_seconds=2.)
        values.update(changes)
        script = self.root / ('controller-' + str(len(list(self.root.iterdir()))) + '.py')
        script.write_text('import os,sys,json,subprocess,time\nassert input()=="GO"\n' + body,
                          encoding='utf-8')
        owned = start_controller([sys.executable, '-X', 'utf8', '-B', str(script)], DomainLimits(**values))
        self.addCleanup(owned.close)
        owned.start()
        return owned

    def event(self, owned, name):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            value = owned.event(.02)
            if value and value.get('event') == name: return value
            if value is None and owned.process.poll() is not None: break
        self.fail('Missing domain fixture event ' + name)

    def test_controller_and_detached_compiler_child_share_domain(self):
        flags = 'creationflags=0x8' if os.name == 'nt' else 'start_new_session=True'
        child = 'import time;time.sleep(20)'
        owned = self.controller('child=subprocess.Popen([sys.executable,"-c",' + repr(child) + '],'
            + flags + ')\nprint(json.dumps(dict(event="child",pid=child.pid)),flush=True)\n'
            'time.sleep(20)\n')
        self.event(owned, 'child')
        self.assertGreaterEqual(owned.tree_usage()['processes'], 2)
        self.assertIsNone(owned.failure)
        capabilities = owned.capabilities()
        self.assertEqual(capabilities['containment']['status'], 'hard')
        self.assertEqual(capabilities['user_cpu_time']['status'],
                         'hard' if os.name == 'nt' else 'unsupported')
        self.assertEqual(capabilities['cpu_time']['status'], 'unsupported')
        owned.terminate(); owned.close()
        self.assertTrue(owned.closure()['descendants_empty'])
        self.assertTrue(owned.closed)
        print(json.dumps(dict(check='controller_domain', platform=sys.platform,
                              capabilities=capabilities, closure=owned.closure())), flush=True)

    def test_leader_exit_does_not_release_detached_descendant_ownership(self):
        flags = 'creationflags=0x8' if os.name == 'nt' else 'start_new_session=True'
        owned = self.controller('child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(20)"],'
            + flags + ')\nprint(json.dumps(dict(event="child")),flush=True)\n')
        self.event(owned, 'child')
        # systemd owns leader-first cleanup itself. Native job closure must also
        # confirm emptiness independently of the interpreter's early exit.
        if os.name == 'nt': owned.process.wait(timeout=5)
        owned.close()
        self.assertTrue(owned.eof)
        self.assertTrue(owned.closed)

    def test_memory_exhaustion_is_inside_controller_domain(self):
        owned = self.controller('print(json.dumps(dict(event="allocating")),flush=True)\n'
            'try:\n x=bytearray(256*1024**2);print(json.dumps(dict(event="unbounded")),flush=True)\n'
            'except MemoryError:print(json.dumps(dict(event="bounded")),flush=True)\n')
        self.event(owned, 'allocating')
        if os.name == 'nt':
            self.event(owned, 'bounded')
        else:
            owned.process.wait(timeout=8)
            self.assertNotEqual(owned.process.returncode, 0)
        owned.close()
        self.assertTrue(owned.closed)

    @unittest.skipUnless(os.name == 'nt', 'Windows application-domain process exhaustion')
    def test_native_domain_process_and_cpu_limits_include_controller(self):
        owned = self.controller('try:\n'
            ' child=subprocess.Popen([sys.executable,"-c","print(123)"],stdout=subprocess.PIPE,text=True)\n'
            ' out=child.communicate()[0];bounded=child.returncode!=0 or not out.strip()\n'
            'except OSError:bounded=True\n'
            'print(json.dumps(dict(event="process",bounded=bounded)),flush=True)\n', processes=2)
        self.assertTrue(self.event(owned, 'process')['bounded'])
        from ctypes import wintypes as w
        import ctypes
        class Rate(ctypes.Structure): _fields_ = [('flags', w.DWORD), ('rate', w.DWORD)]
        rate = Rate()
        self.assertTrue(owned.kernel.QueryInformationJobObject(owned.job, 15,
            ctypes.byref(rate), ctypes.sizeof(rate), None))
        self.assertEqual((rate.flags, rate.rate), (5, 1000))
        owned.close()

    @unittest.skipIf(os.name == 'nt', 'Linux task and kernel-lifetime controls')
    def test_thread_exhaustion_and_effective_cpu_configuration(self):
        owned = self.controller('from threading import Thread,Event\nstop=Event()\ncount=0\n'
            'try:\n'
            ' for i in range(32):\n  Thread(target=stop.wait,args=(5,)).start();count+=1\n'
            'except RuntimeError:print(json.dumps(dict(event="bounded",count=count)),flush=True)\n'
            'stop.set()\n', tasks=8)
        self.assertLess(self.event(owned, 'bounded')['count'], 8)
        self.assertEqual(owned.configuration['pids.max'], '8')
        self.assertNotEqual(owned.configuration['cpu.max'].split()[0], 'max')
        owned.close(); self.assertTrue(owned.closed)

    @unittest.skipIf(os.name == 'nt', 'Linux manager independent lifetime')
    def test_manager_stops_blocked_controller_without_owner_checkpoints(self):
        owned = self.controller('print(json.dumps(dict(event="blocked")),flush=True)\ntime.sleep(20)\n',
                                wall_seconds=.5)
        self.event(owned, 'blocked')
        began = time.monotonic()
        owned.process.wait(timeout=5)
        self.assertNotEqual(owned.process.returncode, 0)
        owned.close()
        self.assertLess(time.monotonic() - began, 5)
        self.assertTrue(owned.closed)

    def test_failed_closure_keeps_domain_until_retry(self):
        owned = self.controller('print(json.dumps(dict(event="ready")),flush=True)\ntime.sleep(20)\n')
        self.event(owned, 'ready')
        with patch.object(owned, 'wait_empty', side_effect=TimeoutError('Synthetic domain closure')):
            with self.assertRaises(TimeoutError): owned.terminate()
            with self.assertRaises(TimeoutError): owned.close()
        self.assertIs(_pending_processes[id(owned)], owned)
        self.assertFalse(owned.closed)
        owned.close()
        self.assertTrue(owned.closed)
        self.assertNotIn(id(owned), _pending_processes)

    def test_reader_start_failure_uses_same_domain_cleanup(self):
        owners = []
        failure = RuntimeError('Synthetic reader failure')
        def fail(thread):
            owners.append(thread._target.__self__)
            raise failure
        with patch('backtest.runtime.process_owner.Thread.start', fail):
            with self.assertRaises(RuntimeError) as caught:
                self.controller('time.sleep(20)\n')
        self.assertIs(caught.exception, failure)
        self.assertTrue(owners[0].closed)
        self.assertTrue(owners[0].descendants_empty)

    @unittest.skipUnless(os.name == 'nt', 'Windows pre-bootstrap assignment failure')
    def test_native_assignment_failure_prevents_application_effects(self):
        marker = self.root / 'must-not-exist'
        with patch.object(OwnedProcess, '_assign_job', side_effect=OSError('Synthetic assignment')):
            with self.assertRaises(OSError):
                start_controller([sys.executable, '-c',
                    'from pathlib import Path;Path(' + repr(str(marker)) + ').touch()'],
                    DomainLimits(128 * 1024**2, 16, 10, 10., 8.))
        self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == 'nt', 'Linux unsupported backend fails closed')
    def test_missing_manager_never_falls_back_to_process_sessions(self):
        with patch.dict(os.environ, DBUS_SESSION_BUS_ADDRESS='unix:path=/nonexistent-cb02-bus'):
            with self.assertRaises(OSError) as caught: self.controller('time.sleep(20)\n')
        retained = getattr(caught.exception, 'owned_process', None)
        if retained is not None:
            retained.close()
            self.assertNotIn(id(retained), _pending_processes)

    @unittest.skipIf(os.name == 'nt', 'Linux delayed manager creation')
    def test_creation_visible_after_client_exit_keeps_owner_until_manager_stop(self):
        # The client fixture delays its request. After it dies, publish the
        # unique unit as a delayed manager request would. Absence before then
        # must never count as confirmed closure.
        binary = self.root / 'bin'; binary.mkdir()
        client = binary / 'systemd-run'
        client.write_text('#!/bin/sh\nexec /usr/bin/sleep 30\n')
        client.chmod(0o700)
        limits = DomainLimits(64 * 1024**2, 16, 10, 10., 8., close_seconds=.5)
        with patch.dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH']):
            with self.assertRaises(OSError) as caught:
                start_controller(['/usr/bin/sleep', '20'], limits)
        owned = caught.exception.owned_process
        self.assertIsNotNone(owned.process.poll())
        self.assertFalse(owned.closed)
        self.assertIs(_pending_processes[id(owned)], owned)
        with self.assertRaises(TimeoutError): owned.close()
        self.assertFalse(owned.closed)
        result = subprocess.run(['systemd-run', '--user', '--quiet', '--collect', '--unit=' + owned.unit,
            '-p', 'MemoryMax=64M', '-p', 'TasksMax=16', '-p', 'CPUQuota=10%',
            '-p', 'RuntimeMaxSec=10', '-p', 'TimeoutStopSec=.5', '-p', 'KillMode=control-group',
            '/usr/bin/sleep', '20'], capture_output=True, text=True, timeout=3)
        self.addCleanup(owned.close)
        self.assertEqual(result.returncode, 0)
        owned.close()
        self.assertTrue(owned.closed)
        self.assertTrue(owned.closure()['creation_settled'])
        self.assertNotIn(id(owned), _pending_processes)


if __name__ == '__main__': unittest.main()

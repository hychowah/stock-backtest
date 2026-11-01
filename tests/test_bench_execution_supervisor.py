"""Externally supervised comparisons on generated captures only."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'website')]
import bench_execution_supervisor as supervisor
from bench_candidates_process import OwnedProcess
from bench_comparison import ComparisonError
import test_bench_execution as fixture_module


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ExecutionTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def supervisor(self):
        owner = self.fixture.owner(fixture_observation_root=None,
                                  coordinated_observation_root=self.fixture.fixture.source)
        return supervisor.ComparisonSupervisor(supervisor.specification(owner))

    def fixture_command(self, control, block_phase=None, marker=None):
        # Patches are confined to disposable children. Nothing shipped accepts
        # a permission marker, flag or environment override.
        code = '''import sys
sys.path[:0]=[sys.argv[1],sys.argv[3]]
from unittest.mock import patch
import bench_execution_controller as c
import bench_execution as e
from test_bench_execution import ExecutionTests
def command(owner,request):
 return ExecutionTests.fixture_command(None,owner,request)
phase,marker=sys.argv[4:6]
if phase:
 import time
 from pathlib import Path
 def block():
  Path(marker).touch();time.sleep(30)
 if phase=='attachment':
  original=e.inputs._manifest
  def manifest(*args,**kwargs):
   value=original(*args,**kwargs);block();return value
  e.inputs._manifest=manifest
 elif phase=='calculation':
  original=e.MeasurementExecution.compare
  def compare(owner):
   block();return original(owner)
  e.MeasurementExecution.compare=compare
 elif phase in ('publication','slow_publication'):
  original=e.MeasurementExecution._persist
  def persist(owner,status,error=None):
   if status=='complete':
    if phase=='publication':block()
    else:time.sleep(owner.protocol.value['costs']['finalization']+1.)
   return original(owner,status,error)
  e.MeasurementExecution._persist=persist
with patch.object(c.admission,'require_execution'), patch.object(e.MeasurementExecution,'_command',command):
 raise SystemExit(c.main())
'''
        return [sys.executable, '-I', '-B', '-c', code, str(ROOT / 'tools'), str(control),
                str(ROOT / 'tests'), block_phase or '', str(marker or '')]

    def test_default_supervisor_and_controller_admission_reject_before_effects(self):
        owner = self.supervisor()
        with patch.object(supervisor.tempfile, 'mkdtemp', side_effect=AssertionError('Effect')):
            with self.assertRaises(supervisor.admission.BenchmarkAdmissionError): owner.run()
        import bench_execution_controller as controller
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('Read')):
            with self.assertRaises(controller.admission.BenchmarkAdmissionError): controller.main()
        self.assertIsNone(owner.control)
        self.assertFalse(self.fixture.fixture.output.exists())

    def test_actual_reference_numba_controller_runs_and_closes_inside_domain(self):
        # Participating source ownership creates its normal coordination files.
        # Establish those disposable files before the immutable-byte snapshot.
        from backtest.runtime import cache_access as cache_access
        import runtime_access
        source = self.fixture.fixture.source
        with runtime_access.ownership(source, timeout=0):
            with cache_access.WorkspaceAccess(source / 'data/website-data-0.lock').observe(): pass
        original = self.fixture.fixture.immutable_bytes()
        owner = self.supervisor()
        with patch.object(supervisor.admission, 'require_execution'), \
                patch.object(owner, '_command', side_effect=self.fixture_command):
            owner.run()
        self.assertTrue(owner.closed)
        self.assertFalse(owner.control.exists())
        self.assertNotIn(id(owner), supervisor._pending_supervisors)
        self.assertEqual(owner.result['status'], 'fixture_pair_complete')
        self.assertTrue(owner.evidence['closure']['closed'])
        self.assertEqual(owner.evidence['capabilities']['containment']['status'], 'hard')
        self.assertEqual(original, self.fixture.fixture.immutable_bytes())
        files = list(self.fixture.fixture.output.glob('workspace-*/domain.json'))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_bytes())['protocol'], owner.result['protocol'])
        self.assertGreaterEqual(owner.result['costs']['attachment'], .001)
        self.assertGreater(owner.result['costs']['finalization'], 0)
        print(json.dumps(dict(check='supervised_financial_fixture', platform=sys.platform,
                              evidence=owner.evidence)), flush=True)

    def blocked(self, phase):
        owner = self.supervisor()
        marker = self.fixture.fixture.root / ('blocked-' + phase)
        code = ('import sys,time;from pathlib import Path;assert input()=="GO";'
                'Path(sys.argv[1]).touch();time.sleep(30)')
        command = [sys.executable, '-c', code, str(marker)]
        owner.cancel = lambda: marker.exists()
        return owner, command

    def test_blocked_attachment_calculation_and_publication_cancel_independently(self):
        # These phases deliberately make no owner checkpoints. The outside
        # supervisor must terminate the controller domain anyway.
        for phase in ('attachment', 'calculation', 'publication'):
            with self.subTest(phase=phase):
                owner = self.supervisor()
                marker = self.fixture.fixture.root / ('actual-blocked-' + phase)
                announced = []
                def cancel():
                    if marker.exists():
                        announced.append(time.monotonic())
                        return True
                    return False
                owner.cancel = cancel
                with patch.object(supervisor.admission, 'require_execution'), \
                        patch.object(owner, '_command', side_effect=lambda control:
                            self.fixture_command(control, phase, marker)):
                    with self.assertRaisesRegex(ComparisonError, 'cancelled'): owner.run()
                self.assertLess(time.monotonic() - announced[0], 8)
                self.assertTrue(owner.closed)
                self.assertTrue(owner.owned.descendants_empty)
                with self.assertRaisesRegex(ComparisonError, 'incomplete'): _ = owner.result

    def test_cleanup_retry_preserves_original_caller_failure_and_control_ownership(self):
        owner, command = self.blocked('caller')
        marker = self.fixture.fixture.root / 'blocked-caller'
        original = RuntimeError('Synthetic caller failure')
        def cancel():
            if marker.exists(): raise original
            return False
        owner.cancel = cancel
        with patch.object(supervisor.admission, 'require_execution'), \
                patch.object(owner, '_command', return_value=command), \
                patch.object(OwnedProcess, 'close', side_effect=TimeoutError('Synthetic close')):
            with self.assertRaises(RuntimeError) as caught: owner.run()
        self.assertIs(caught.exception, original)
        self.assertIs(original.comparison_supervisor, owner)
        self.assertTrue(owner.control.exists())
        self.assertIs(supervisor._pending_supervisors[id(owner)], owner)
        owner.close()
        self.assertFalse(owner.control.exists())
        self.assertIs(owner.terminal_error, original)
        with self.assertRaisesRegex(ComparisonError, 'incomplete'): _ = owner.result

    def test_transport_overflow_is_terminal_and_domain_is_reaped(self):
        owner = self.supervisor()
        code = 'import sys,time;assert input()=="GO";sys.stdout.write("x"*100000);sys.stdout.flush();time.sleep(20)'
        with patch.object(supervisor.admission, 'require_execution'), patch.object(owner, '_command',
                return_value=[sys.executable, '-c', code]):
            with self.assertRaisesRegex(ComparisonError, 'limit'): owner.run()
        self.assertTrue(owner.closed)
        self.assertLessEqual(owner.owned.events.qsize(), 128)

    def test_controller_failure_before_readiness_keeps_no_success(self):
        owner = self.supervisor()
        with patch.object(supervisor.admission, 'require_execution'), patch.object(owner, '_command',
                return_value=[sys.executable, '-c', 'import sys;assert input()=="GO";sys.exit(7)']):
            with self.assertRaisesRegex(ComparisonError, 'child_failed'): owner.run()
        self.assertTrue(owner.closed)
        with self.assertRaisesRegex(ComparisonError, 'incomplete'): _ = owner.result

    def test_final_domain_publication_failure_cannot_expose_success(self):
        owner = self.supervisor()
        replace = Path.replace
        def fail(path, target):
            if path.name == 'domain.building': raise OSError('Synthetic final publication')
            return replace(path, target)
        with patch.object(supervisor.admission, 'require_execution'), \
                patch.object(owner, '_command', side_effect=self.fixture_command), \
                patch.object(Path, 'replace', fail):
            with self.assertRaises(OSError): owner.run()
        self.assertTrue(owner.closed)
        with self.assertRaisesRegex(ComparisonError, 'incomplete'): _ = owner.result

    @unittest.skipUnless(os.name == 'nt', 'Native final accounting acceptance race')
    def test_zero_exit_and_queued_complete_cannot_bypass_final_cpu_exhaustion(self):
        from dataclasses import replace
        from bench_comparison import ComparisonProtocol
        import bench_execution as execution
        from test_bench_execution_user_cpu import burn
        bound = self.fixture.owner(fixture_observation_root=None,
                                   coordinated_observation_root=self.fixture.fixture.source)
        bound.envelope = replace(bound.envelope, user_cpu_seconds=.3)
        declaration = bound.protocol.value
        declaration.pop('version')
        declaration['environment'] = execution.environment(bound.envelope)
        bound.protocol = ComparisonProtocol.freeze(**declaration)
        owner = supervisor.ComparisonSupervisor(supervisor.specification(bound))
        result = dict(protocol=bound.protocol.identity, status='fixture_pair_complete', closed=True,
                      costs=dict.fromkeys(bound.protocol.value['costs'], 0.))
        terminal = dict(event='complete', result=result,
                        workspace=str(self.fixture.fixture.output / 'workspace-unused'))
        code = ('import json,sys,time,subprocess;assert input()=="GO";'
            'subprocess.Popen([sys.executable,"-B","-c",' + repr(burn(30.)) + '],'
            'creationflags=8,stdout=sys.stdout,stderr=sys.stderr);'
            'terminal=json.loads(' + repr(json.dumps(terminal)) + ');'
            'terminal["finalization_started"]=time.monotonic();'
            'print(json.dumps(terminal),flush=True)')
        # Hold resource observation until normal close, as a delayed supervisor
        # could. This bypasses neither the kernel threshold nor final accounting.
        def delayed_accounting(process):
            return process.failure
        with patch.object(supervisor.admission, 'require_execution'), \
                patch.object(owner, '_command', return_value=[sys.executable, '-B', '-c', code]), \
                patch.object(OwnedProcess, 'resource_failure', delayed_accounting):
            with self.assertRaisesRegex(ComparisonError, 'limit'): owner.run()
        self.assertEqual(owner.owned.process.returncode, 0)
        self.assertTrue(owner.closed)
        self.assertTrue(owner.owned.closure()['user_cpu']['exceeded'])
        self.assertLess(time.monotonic() - owner.started,
                        bound.protocol.value['costs']['finalization'])
        with self.assertRaisesRegex(ComparisonError, 'incomplete'): _ = owner.result
        self.assertFalse(list(self.fixture.fixture.output.glob('workspace-*/domain.json')))

    def test_successful_slow_controller_write_exhausts_finalization_before_whole(self):
        owner = self.supervisor()
        with patch.object(supervisor.admission, 'require_execution'), \
                patch.object(owner, '_command', side_effect=lambda control:
                    self.fixture_command(control, 'slow_publication')):
            with self.assertRaisesRegex(ComparisonError, 'limit'): owner.run()
        self.assertTrue(owner.closed)
        self.assertLess(time.monotonic() - owner.started, owner.limit.wall_seconds)
        with self.assertRaisesRegex(ComparisonError, 'incomplete'): _ = owner.result


if __name__ == '__main__': unittest.main()

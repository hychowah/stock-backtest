"""Native ancestor-job lifetime on disposable fixtures. Real admission closed."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from dataclasses import replace, asdict
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tools.experiments.bench_execution as execution
import tools.experiments.bench_execution_supervisor as supervisor
from tools.experiments.bench_execution_domain import LifetimeDomain, parse_lifetime, DomainLimits, NativeLifetimeLimits
from backtest.runtime.process_owner import OwnedProcess
from tools.experiments.bench_comparison import ComparisonError, ComparisonProtocol
import test_bench_execution_supervisor as fixtures


def declaration(memory=2304*1024**2,processes=16,seconds=180.):
    return dict(kind='windows-job',committed_bytes=memory,processes=processes,
                cpu_percent=25,user_cpu_seconds=seconds)


class DeclarationTests(unittest.TestCase):
    def test_explicit_native_semantics_identity_validation_and_platform_rejection(self):
        e=execution.ExecutionEnvelope(4096,4096,128*1024**2,10.,1,8.)
        valid=declaration();self.assertIsInstance(parse_lifetime(valid),NativeLifetimeLimits)
        self.assertNotEqual(execution.environment(e),execution.environment(replace(e,lifetime=valid)))
        for invalid in ({**valid,'tasks':32},{**valid,'kind':'auto'},
                        {**valid,'committed_bytes':True},{**valid,'processes':0},
                        {**valid,'user_cpu_seconds':float('inf')},
                        {k:v for k,v in valid.items() if k!='user_cpu_seconds'}):
            with self.assertRaisesRegex(ComparisonError,'unsupported'):replace(e,lifetime=invalid)
        if os.name!='nt':
            spec=dict(envelope=asdict(replace(e,lifetime=valid)))
            owner=supervisor.ComparisonSupervisor(spec)
            with patch.object(supervisor.admission,'require_execution'), \
                    patch.object(supervisor.tempfile,'mkdtemp',side_effect=AssertionError('effect')):
                with self.assertRaisesRegex(ComparisonError,'unsupported'):owner.run()
            owner.close();self.assertTrue(owner.closed)
        else:
            owner=supervisor.ComparisonSupervisor(dict(envelope=asdict(replace(e,lifetime=valid,
                                                        storage_bytes=8192,evidence_bytes=8192))))
            with patch.object(supervisor.admission,'require_execution'), \
                    patch.object(supervisor.tempfile,'mkdtemp',side_effect=AssertionError('effect')):
                with self.assertRaisesRegex(ComparisonError,'unsupported'):owner.run()
            owner.close();self.assertTrue(owner.closed)


@unittest.skipUnless(os.name=='nt','Native Windows ancestor Job Object lifetime')
class NativeLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.SupervisorTests('runTest');self.base.setUp()
        self.addCleanup(self.cleanup_fixture)

    def cleanup_fixture(self):
        root=self.base.fixture.fixture.root
        if any(s.lifetime is not None and not s.closed and
               Path(s.specification.get('output','/')).is_relative_to(root)
               for s in supervisor._pending_supervisors.values()):
            self.base.fixture.fixture.temporary._finalizer.detach()
            raise AssertionError('Pending native lifetime preserves fixture root.')
        self.base.doCleanups()

    def owner(self,**changes):
        bound=self.base.fixture.owner(fixture_observation_root=None,
                                      coordinated_observation_root=self.base.fixture.fixture.source)
        bound.envelope=replace(bound.envelope,lifetime=declaration(**changes),close_seconds=3.)
        value=bound.protocol.value;value.pop('version');value['environment']=execution.environment(bound.envelope)
        bound.protocol=ComparisonProtocol.freeze(**value)
        return supervisor.ComparisonSupervisor(supervisor.specification(bound))

    def command(self,request,mode='financial'):
        code='''import sys;from pathlib import Path;sys.path.insert(0,str(Path(sys.argv[1])/'tests'))
import sys;sys.path.insert(0,sys.argv[1])
import os,sys,json,time
from pathlib import Path
from unittest.mock import patch
import tools.experiments.bench_execution_supervisor as s
import tools.experiments.bench_execution_supervisor_worker as w
from test_bench_execution_supervisor import SupervisorTests
spec=json.loads(Path(sys.argv[2]).read_bytes());mode=sys.argv[4]
output=Path(spec['output'])
if mode!='financial':output.mkdir(exist_ok=True)
closed=s._ApplicationSupervisor._close_domain
seen=[False]
def close(owner):
 closed(owner)
 if not seen[0]:
  seen[0]=True
  if mode=='memory':
   print(json.dumps(dict(event='collection',stage='after_application_close')),flush=True)
   x=bytearray(256*1024**2)
  if mode=='blocked':
   (output/'partial-publication').write_bytes(b'verified-prefix')
   print(json.dumps(dict(event='collection',stage='blocked_publication')),flush=True)
   time.sleep(30)
s._ApplicationSupervisor._close_domain=close
if mode=='retry':
 remove=s.shutil.rmtree
 attempts=[0]
 def retry(path,*args,**kwargs):
  attempts[0]+=1
  if attempts[0]<=3:raise OSError('Synthetic control release')
  return remove(path,*args,**kwargs)
 s.shutil.rmtree=retry
if mode=='helper_death':
 start=s.start_controller
 def die(command,limits,**kwargs):
  owned=start(command,limits,**kwargs);owned.start()
  deadline=time.monotonic()+8
  while not (output/'application-ready').exists():
   if time.monotonic()>deadline:raise RuntimeError('Readiness missing')
   time.sleep(.02)
  os._exit(29)
 s.start_controller=die
def command(owner,request):
 if mode=='financial':return SupervisorTests.fixture_command(None,request)
 if mode=='helper_death':
  body="import os,sys,json,time,subprocess;from pathlib import Path;assert input()=='GO';child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'],creationflags=8,stdout=sys.stdout,stderr=sys.stderr);Path(sys.argv[1]).write_text(json.dumps(dict(pid=os.getpid(),child=child.pid)));time.sleep(30)"
  return [sys.executable,'-B','-c',body,str(output/'application-ready')]
 if mode=='process':
  body="""import sys,json,subprocess
from pathlib import Path
assert input()=='GO'
try:
 child=subprocess.Popen([sys.executable,'-B','-c','print(123)'],stdout=subprocess.PIPE,text=True)
 out=child.communicate(timeout=5)[0]
 bounded=child.returncode!=0 or out.strip()!='123'
 result=dict(bounded=bounded)
except OSError as e:result=dict(bounded=True,error_type=type(e).__name__,winerror=e.winerror)
Path(sys.argv[1]).write_text(json.dumps(result))
print(json.dumps(dict(event='failed',reason='child_failed')),flush=True)
"""
  return [sys.executable,'-B','-c',body,str(output/'process-denial.json')]
 workspace=output/('workspace-'+'a'*32)
 result=dict(protocol=spec['protocol_sha256'],status='fixture_pair_complete',closed=True,costs=dict.fromkeys(spec['protocol']['costs'],0.))
 terminal=dict(event='complete',workspace=str(workspace),result=result)
 body="import sys,json,time;from pathlib import Path;assert input()=='GO';value=json.loads(sys.argv[1]);Path(value['workspace']).mkdir(exist_ok=True);value['finalization_started']=time.monotonic();print(json.dumps(value),flush=True)"
 return [sys.executable,'-B','-c',body,json.dumps(terminal)]
with patch.object(w.admission,'require_execution'),patch.object(s._ApplicationSupervisor,'_command',command):
 raise SystemExit(w.main())
'''
        return [sys.executable,'-I','-B','-c',code,str(ROOT),str(request),str(ROOT/'tests'),mode]

    def run_owner(self,owner,mode='financial'):
        with patch.object(supervisor.admission,'require_execution'), \
                patch.object(owner,'_helper_command',side_effect=lambda request:self.command(request,mode)):
            return owner.run()

    def test_actual_reference_both_numba_variants_share_native_lifetime(self):
        from backtest.runtime import cache_access as cache_access; from website import runtime_access
        f=self.base.fixture.fixture
        with runtime_access.ownership(f.source,timeout=0):
            with cache_access.WorkspaceAccess(f.source/'data/website-data-0.lock').observe():pass
        before=f.immutable_bytes();owner=self.owner()
        self.run_owner(owner)
        self.assertTrue(owner.closed);self.assertTrue(owner.lifetime.closed)
        self.assertEqual(owner.result['status'],'fixture_pair_complete')
        self.assertEqual(f.immutable_bytes(),before)
        facts=owner.owned.closure()
        self.assertTrue(facts['native_configuration']['verified_before_resume'])
        self.assertFalse(facts['native_configuration']['inheritable'])
        self.assertEqual(facts['native_configuration']['committed_bytes'],2304*1024**2)
        self.assertGreater(facts['user_cpu']['accounting']['total'],4)
        self.assertFalse(facts['user_cpu']['exceeded'])
        self.assertTrue(list(f.output.glob('workspace-*/domain.json')))
        print(json.dumps(dict(check='native_lifetime_financial',evidence=owner.evidence)),flush=True)

    def test_memory_denial_during_finalization_after_application_closure(self):
        for memory,denied in ((512*1024**2,False),(128*1024**2,True)):
            owner=self.owner(memory=memory)
            if denied:
                with self.assertRaisesRegex(ComparisonError,'child_failed'):self.run_owner(owner,'memory')
                self.assertEqual(owner.remote_error_type,'MemoryError')
                with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result
            else:
                self.run_owner(owner,'memory')
                self.assertEqual(owner.result['status'],'fixture_pair_complete')
            self.assertEqual(owner.progress['stage'],'after_application_close')
            self.assertTrue(owner.closed)
            self.assertEqual(owner.owned.closure()['native_configuration']['committed_bytes'],memory)
            print(json.dumps(dict(check='native_finalization_memory_denial',denied=denied,
                                  closure=owner.owned.closure())),flush=True)

    def test_aggregate_process_limit_includes_nested_application(self):
        output=self.base.fixture.fixture.output
        for maximum,bounded in ((8,False),(4,True)):
            owner=self.owner(processes=maximum)
            with self.assertRaisesRegex(ComparisonError,'child_failed'):self.run_owner(owner,'process')
            facts=json.loads((output/'process-denial.json').read_text())
            self.assertIs(facts['bounded'],bounded)
            self.assertTrue(owner.closed)
            self.assertEqual(owner.owned.closure()['native_configuration']['processes'],maximum)
            print(json.dumps(dict(check='native_aggregate_process_denial',maximum=maximum,facts=facts,
                                  closure=owner.owned.closure())),flush=True)

    def test_failed_native_query_prevents_resume_and_allows_close(self):
        original=OwnedProcess._verify_native_limits;captured=[]
        def fail(owner):
            captured.append(owner)
            query=owner.kernel.QueryInformationJobObject
            owner.kernel.QueryInformationJobObject=lambda *args:False if args[1]==9 else query(*args)
            try:original(owner)
            finally:owner.kernel.QueryInformationJobObject=query
        owner=self.owner()
        with patch.object(OwnedProcess,'_verify_native_limits',fail):
            with self.assertRaises(OSError):self.run_owner(owner,'blocked')
        self.assertFalse(captured[0]._resumed)
        self.assertTrue(captured[0].closed)
        self.assertTrue(owner.closed)
        self.assertFalse(self.base.fixture.fixture.output.exists())

    def test_alive_helper_retains_controls_for_explicit_retry(self):
        owner=self.owner()
        # Trigger an ordinary child failure after closure, before control release.
        with self.assertRaisesRegex(ComparisonError,'child_failed') as caught:self.run_owner(owner,'retry')
        self.assertFalse(owner.closed);self.assertIsNone(owner.owned.process.poll())
        self.assertIs(caught.exception.comparison_supervisor,owner)
        before=owner.owned.closure()['native_configuration']
        owner.close();self.assertTrue(owner.closed)
        self.assertEqual(before,owner.owned.closure()['native_configuration'])
        self.assertIs(owner.terminal_error,caught.exception)
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_helper_death_cannot_orphan_nested_application(self):
        owner=self.owner()
        with self.assertRaisesRegex(ComparisonError,'child_failed'):self.run_owner(owner,'helper_death')
        self.assertEqual(owner.owned.process.returncode,29)
        self.assertTrue((self.base.fixture.fixture.output/'application-ready').exists())
        self.assertTrue(owner.closed);self.assertTrue(owner.owned.descendants_empty)
        self.assertGreaterEqual(owner.owned.closure()['user_cpu']['accounting']['total'],5)

    def test_blocked_publication_caller_error_and_partial_handle_retry(self):
        owner=self.owner();error=RuntimeError('Synthetic caller failure')
        def cancel():
            if owner.progress and owner.progress.get('stage')=='blocked_publication':raise error
            return False
        owner.cancel=cancel
        def fail(process):
            for stream in (process.process.stdin,process.process.stdout):
                if stream is not None and not stream.closed:stream.close()
            raise OSError('Synthetic retained job handle')
        with patch.object(OwnedProcess,'_close_handles',fail):
            with self.assertRaises(RuntimeError) as caught:self.run_owner(owner,'blocked')
        self.assertIs(caught.exception,error);self.assertIs(error.comparison_supervisor,owner)
        self.assertIsNotNone(owner.owned.job);self.assertTrue(owner.owned.eof)
        self.assertTrue(owner.control.exists())
        self.assertEqual((self.base.fixture.fixture.output/'partial-publication').read_bytes(),b'verified-prefix')
        owner.close();self.assertTrue(owner.closed)
        self.assertIsNone(owner.owned.job);self.assertIs(owner.terminal_error,error)
        facts=owner.owned.closure();facts['native_configuration']['processes']=1
        self.assertEqual(owner.owned.closure()['native_configuration']['processes'],16)
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_caller_death_closes_last_job_handle_and_all_observed_processes(self):
        f=self.base.fixture.fixture;record=f.root/'caller-record.json';barrier=f.root/'caller-die'
        helper="""import sys;sys.path.insert(0,sys.argv[1])
import sys,json,time,os
from tools.experiments.bench_execution_domain import start_controller,DomainLimits
from pathlib import Path
assert input()=='GO'
body="import os,sys,json,time;from pathlib import Path;assert input()=='GO';Path(sys.argv[1]).write_text(json.dumps(dict(application=os.getpid())));time.sleep(30)"
child=start_controller([sys.executable,'-B','-c',body,sys.argv[2]],DomainLimits(128*1024**2,32,25,30.,20.,processes=8,close_seconds=2.))
child.start()
while not Path(sys.argv[2]).exists():time.sleep(.02)
print(json.dumps(dict(event='ready',helper=os.getpid(),**json.loads(Path(sys.argv[2]).read_text()))),flush=True)
time.sleep(30)
"""
        caller="""import sys;sys.path.insert(0,sys.argv[1])
import sys,json,time,os
from pathlib import Path
from tools.experiments.bench_execution_domain import LifetimeDomain,parse_lifetime,DomainLimits
owner=LifetimeDomain(parse_lifetime(dict(kind='windows-job',committed_bytes=256*1024**2,processes=12,cpu_percent=25,user_cpu_seconds=20.)),DomainLimits(128*1024**2,32,25,30.,20.,close_seconds=2.))
owner.prepare();owned=owner.start([sys.executable,'-I','-B','-c',sys.argv[4],sys.argv[1],sys.argv[2]+'.application'])
owner.go=True;owned.start();deadline=time.monotonic()+10
while time.monotonic()<deadline:
 event=owned.event(.02)
 if event and event.get('event')=='ready':
  Path(sys.argv[2]).write_text(json.dumps(dict(helper=event['helper'],application=event['application'],configuration=owned.closure()['native_configuration'])))
  while not Path(sys.argv[3]).exists():time.sleep(.02)
  os._exit(29)
raise RuntimeError('Missing readiness')
"""
        process=subprocess.Popen([sys.executable,'-I','-B','-c',caller,str(ROOT),str(record),str(barrier),helper],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        from ctypes import wintypes as w
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
        kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];kernel.CloseHandle.argtypes=[w.HANDLE]
        handles=[]
        try:
            deadline=time.monotonic()+12
            while not record.exists():
                if process.poll() is not None or time.monotonic()>deadline:
                    self.fail('Disposable caller did not become ready')
                time.sleep(.02)
            facts=json.loads(record.read_text());self.assertFalse(facts['configuration']['inheritable'])
            for pid in (facts['helper'],facts['application']):
                handle=kernel.OpenProcess(0x100000|0x1000,False,pid)
                self.assertTrue(handle);handles.append(handle)
                self.assertEqual(kernel.WaitForSingleObject(handle,0),258)
            barrier.touch();process.wait(timeout=5)
            self.assertEqual(process.returncode,29)
            for handle in handles:self.assertEqual(kernel.WaitForSingleObject(handle,5000),0)
            print(json.dumps(dict(check='native_caller_death',facts=facts,observed_processes_exited=True)),flush=True)
        finally:
            barrier.touch()
            if process.poll() is None:process.kill()
            process.communicate(timeout=5)
            for handle in handles:kernel.CloseHandle(handle)

    def test_queued_success_cannot_bypass_final_ancestor_cpu_accounting(self):
        from test_bench_execution_user_cpu import burn
        owner=self.owner(seconds=.3)
        result=dict(protocol=owner.specification['protocol_sha256'],status='fixture_pair_complete',closed=True,
                    costs=dict.fromkeys(owner.specification['protocol']['costs'],0.))
        body=('import sys,json,time,subprocess;assert input()=="GO";'
              'subprocess.Popen([sys.executable,"-B","-c",'+repr(burn(30.))+'],creationflags=8,stdout=sys.stdout,stderr=sys.stderr);'
              'print(json.dumps(dict(event="complete",result=json.loads(sys.argv[1]),evidence={},finalization_started=time.monotonic())),flush=True)')
        command=[sys.executable,'-B','-c',body,json.dumps(result)]
        with patch.object(supervisor.admission,'require_execution'),patch.object(owner,'_helper_command',return_value=command), \
                patch.object(OwnedProcess,'resource_failure',lambda process:process.failure):
            with self.assertRaisesRegex(ComparisonError,'limit'):owner.run()
        self.assertEqual(owner.owned.process.returncode,0)
        self.assertTrue(owner.closed);self.assertTrue(owner.owned.closure()['user_cpu']['exceeded'])
        self.assertLess(time.monotonic()-owner._finalization_started,owner.specification['protocol']['costs']['finalization'])
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result


if __name__=='__main__':unittest.main()

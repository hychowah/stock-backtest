"""Private lifetime hierarchy, collection and death fixtures. No real assets."""
from dataclasses import replace, asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
import bench_execution as execution
import bench_execution_supervisor as supervisor
import bench_execution_supervisor_worker as worker
from bench_execution_domain import LifetimeLimits, LifetimeDomain, DomainLimits
from bench_comparison import ComparisonError, ComparisonProtocol
import test_bench_execution_supervisor as fixtures


class DeclarationTests(unittest.TestCase):
    def test_lifetime_is_explicit_bound_identity_and_native_fails_before_effects(self):
        base=execution.ExecutionEnvelope(4096,4096,128*1024**2,4.,1,8.)
        for declaration in ({},dict(memory_bytes=True,tasks=16,cpu_percent=10),
                            dict(memory_bytes=128*1024**2,tasks=0,cpu_percent=10)):
            with self.assertRaisesRegex(ComparisonError,'unsupported'):replace(base,lifetime=declaration)
        changed=replace(base,lifetime=asdict(LifetimeLimits(256*1024**2,32,10)))
        self.assertNotEqual(execution.environment(base),execution.environment(changed))
        owner=supervisor.ComparisonSupervisor(dict(envelope=asdict(changed)))
        with patch.object(supervisor.admission,'require_execution',side_effect=AssertionError('closed')):
            with self.assertRaises(AssertionError):owner.run()
        with patch.object(worker.admission,'require_execution'),patch('builtins.input',return_value='bad'), \
                patch.object(Path,'open',side_effect=AssertionError('read')):
            with self.assertRaisesRegex(ComparisonError,'protocol'):worker.main()
        if sys.platform!='linux':
            with patch.object(supervisor.admission,'require_execution'), \
                    patch.object(supervisor.tempfile,'mkdtemp',side_effect=AssertionError('effect')):
                with self.assertRaisesRegex(ComparisonError,'unsupported'):owner.run()
            self.assertIsNone(owner.control)
            owner.close();self.assertTrue(owner.closed)


@unittest.skipUnless(sys.platform=='linux','Private WSL lifetime hierarchy; native coverage uses test_bench_execution_native_lifetime')
class LifetimeTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.SupervisorTests('runTest');self.base.setUp()
        self.addCleanup(self.cleanup_fixture)

    def cleanup_fixture(self):
        if any(getattr(s,'lifetime',None) and not s.closed for s in supervisor._pending_supervisors.values()):
            self.base.fixture.fixture.temporary._finalizer.detach()
            raise AssertionError('Pending lifetime preserves fixture root.')
        self.base.doCleanups()

    def owner(self,memory=2304*1024**2,tasks=96,wall=None):
        bound=self.base.fixture.owner(fixture_observation_root=None,
                                      coordinated_observation_root=self.base.fixture.fixture.source)
        changes=dict(storage_bytes=32*1024**2,evidence_bytes=40*1024**2,
                     close_seconds=3.,lifetime=asdict(LifetimeLimits(memory,tasks,25)))
        if wall is not None:changes['wall_seconds']=wall
        bound.envelope=replace(bound.envelope,**changes)
        value=bound.protocol.value;value.pop('version');value['environment']=execution.environment(bound.envelope)
        bound.protocol=ComparisonProtocol.freeze(**value)
        return supervisor.ComparisonSupervisor(supervisor.specification(bound))

    def command(self,request,mode='financial'):
        code='''import sys,time,os,json
sys.path[:0]=[sys.argv[1],sys.argv[3]]
from pathlib import Path
from unittest.mock import patch
import bench_execution_supervisor_worker as w
import bench_execution_supervisor as s
import bench_execution_storage as st
from test_bench_execution_supervisor import SupervisorTests
mode=sys.argv[4]
original=st.ExperimentalStorage._copy_record
prepare=st.ExperimentalStorage.prepare
baseline=[0]
def prepared(owner):
 result=prepare(owner)
 group=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::')[1].lstrip('/')
 baseline[0]=int(dict(line.split() for line in (group.parent/'memory.stat').read_text().splitlines())['shmem'])
 return result
st.ExperimentalStorage.prepare=prepared
count=[0]
def copy(owner,path,fd,size,check):
 count[0]+=1
 if count[0]==1:
  group=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::')[1].lstrip('/')
  ancestor=group.parent
  facts=dict(event='collection',application_closed=True,baseline_shmem=baseline[0],configuration={n:(ancestor/n).read_text().strip() for n in ('memory.max','memory.swap.max','pids.max','cpu.max')},memory_current=int((ancestor/'memory.current').read_text()),shmem=int(dict(line.split() for line in (ancestor/'memory.stat').read_text().splitlines())['shmem']),helper_group=str(group),ancestor=str(ancestor),storage_bytes=os.fstatvfs(owner.pin).f_blocks*os.fstatvfs(owner.pin).f_frsize)
  print(json.dumps(facts),flush=True)
  if mode=='memory':x=bytearray(256*1024**2)
  if mode=='tasks':
   from threading import Thread,Event
   stop=Event()
   try:
    for i in range(100):Thread(target=stop.wait,args=(1,),daemon=True).start()
   finally:stop.set()
  if mode=='blocked':time.sleep(30)
  if mode=='death':
   original(owner,path,fd,size,check)
   os._exit(29)
  if mode=='ready':
   replace=Path.replace
   def die(source,target):
    if source==owner.pending:os._exit(29)
    return replace(source,target)
   Path.replace=die
 return original(owner,path,fd,size,check)
st.ExperimentalStorage._copy_record=copy
if mode=='retry':
 release=st.ExperimentalStorage._release
 attempts=[0]
 def retry(owner):
  attempts[0]+=1
  if attempts[0]<=2:raise OSError('Synthetic handle release')
  return release(owner)
 st.ExperimentalStorage._release=retry
def command(owner,request):
 if mode in ('financial','slow_helper'):return SupervisorTests.fixture_command(None,request)
 body="import os,sys,json;from pathlib import Path;assert input()=='GO';p=Path('/tmp/cb02-operation/payload');p.write_bytes(b'x'*(8*1024**2));print(json.dumps(dict(event='failed',reason='child_failed')),flush=True)"
 return [sys.executable,'-I','-B','-c',body]
if mode=='slow_helper':
 send=w.send
 def slow(**value):
  if value.get('event')=='complete':time.sleep(21.)
  return send(**value)
 w.send=slow
with patch.object(w.admission,'require_execution'),patch.object(s._ApplicationSupervisor,'_command',command):
 raise SystemExit(w.main())
'''
        return [sys.executable,'-I','-B','-c',code,str(ROOT/'tools'),str(request),str(ROOT/'tests'),mode]

    def run_owner(self,owner,mode='financial'):
        with patch.object(supervisor.admission,'require_execution'), \
                patch.object(owner,'_helper_command',side_effect=lambda request:self.command(request,mode)):
            return owner.run()

    def test_actual_reference_numba_and_pinned_storage_share_lifetime(self):
        import cache_access,runtime_access
        f=self.base.fixture.fixture
        with runtime_access.ownership(f.source,timeout=0):
            with cache_access.WorkspaceAccess(f.source/'data/website-data-0.lock').observe():pass
        before=f.immutable_bytes();owner=self.owner()
        self.run_owner(owner)
        self.assertEqual(owner.result['status'],'fixture_pair_complete')
        self.assertTrue(owner.lifetime.closed);self.assertTrue(owner.closed)
        self.assertEqual(f.immutable_bytes(),before)
        self.assertTrue(owner.evidence['lifetime_closure']['closed'])
        self.assertEqual(owner.evidence['lifetime']['configuration']['memory.max'],str(2304*1024**2))
        from bench_execution_storage import inspect_evidence
        evidence=inspect_evidence(next(f.output.glob('*.evidence')))
        self.assertTrue(any(r['path'].endswith('/domain.json') for r in evidence['records']))
        print(json.dumps(dict(check='lifetime_financial',evidence=owner.evidence)),flush=True)

    def test_successful_helper_tail_cannot_restart_finalization(self):
        import cache_access,runtime_access
        source=self.base.fixture.fixture.source
        with runtime_access.ownership(source,timeout=0):
            with cache_access.WorkspaceAccess(source/'data/website-data-0.lock').observe():pass
        owner=self.owner()
        with self.assertRaisesRegex(ComparisonError,'limit'):self.run_owner(owner,'slow_helper')
        self.assertTrue(owner.closed)
        self.assertLess(time.monotonic()-owner.started,owner.limit.wall_seconds)
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_pinned_pages_remain_charged_after_application_closure(self):
        owner=self.owner()
        with self.assertRaisesRegex(ComparisonError,'child_failed'):self.run_owner(owner,'pin')
        facts=owner.progress
        self.assertTrue(facts['application_closed'])
        self.assertGreaterEqual(facts['shmem']-facts['baseline_shmem'],8*1024**2)
        self.assertGreaterEqual(facts['memory_current'],facts['shmem'])
        self.assertEqual(Path(facts['helper_group']).parent,Path(facts['ancestor']))
        self.assertEqual(Path(facts['ancestor']).name,owner.lifetime.names['slice'])
        self.assertTrue(owner.closed)
        print(json.dumps(dict(check='pinned_page_charges',facts=facts)),flush=True)

    def test_alive_helper_preserves_storage_for_explicit_close_retry(self):
        owner=self.owner()
        with self.assertRaisesRegex(ComparisonError,'child_failed') as caught:self.run_owner(owner,'retry')
        self.assertIs(caught.exception.comparison_supervisor,owner)
        self.assertFalse(owner.closed)
        self.assertIsNone(owner.owned.process.poll())
        self.assertTrue(owner.control.exists())
        owner.close()
        self.assertTrue(owner.closed)
        self.assertIs(owner.terminal_error,caught.exception)
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_absent_slice_cannot_settle_unobserved_creation(self):
        limits=DomainLimits(128*1024**2,16,25,2.,8.,close_seconds=.2)
        owned=LifetimeDomain(LifetimeLimits(128*1024**2,16,25),limits)
        original=subprocess.run;requests=[]
        def fail(args,**kwargs):
            if args[0]=='busctl':
                requests.append(args)
                return subprocess.CompletedProcess(args,1,'','')
            return original(args,**kwargs)
        with patch('bench_execution_domain.subprocess.run',side_effect=fail):
            with self.assertRaises(OSError):owned.prepare()
        with self.assertRaises(TimeoutError):owned.close()
        self.assertFalse(owned.closed)
        # Publish its exact delayed creation; only manager-bound teardown of
        # this observed transient object can now settle the request.
        result=original(requests[0],capture_output=True,text=True,timeout=2.)
        self.assertEqual(result.returncode,0)
        owned.close();self.assertTrue(owned.closed)

    def test_collection_memory_and_tasks_exhaust_real_ancestor(self):
        for mode in ('memory','tasks'):
            with self.subTest(mode=mode):
                owner=self.owner(memory=128*1024**2,tasks=16)
                with self.assertRaisesRegex(ComparisonError,'limit'):self.run_owner(owner,mode)
                self.assertTrue(owner.closed)
                self.assertTrue(owner.lifetime.resource_failure())
                with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result
                print(json.dumps(dict(check='collection_'+mode,capability=owner.lifetime.capability())),flush=True)

    def test_killed_collector_retains_committed_prefix_and_ready_recovery(self):
        from bench_execution_storage import inspect_evidence,recover_publication
        f=self.base.fixture.fixture
        for mode in ('death','ready'):
            with self.subTest(mode=mode):
                previous=set(f.output.glob('*')) if f.output.exists() else set()
                owner=self.owner()
                with self.assertRaisesRegex(ComparisonError,'child_failed'):self.run_owner(owner,mode)
                self.assertTrue(owner.closed)
                pending=next(p for p in f.output.glob('*.pending') if p not in previous)
                record=inspect_evidence(pending)
                self.assertFalse(record['header']['accepted_result'])
                self.assertGreaterEqual(record['header']['entries'],1)
                if mode=='ready':
                    self.assertEqual(record['header']['state'],'ready')
                    self.assertTrue(recover_publication(pending).exists())
                else:self.assertEqual(record['header']['state'],'collecting')
                with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_manager_deadline_closes_application_after_caller_death(self):
        f=self.base.fixture.fixture
        record=f.root/'death-record.json'
        helper="""import sys,json,time
sys.path.insert(0,sys.argv[1])
from bench_execution_domain import start_controller,DomainLimits
names=json.loads(sys.argv[2])
assert input()=='GO'
owned=start_controller([sys.executable,'-c',"import time;assert input()=='GO';time.sleep(30)"],DomainLimits(64*1024**2,8,25,30.,8.,close_seconds=.3),hierarchy=names,role='application')
owned.start()
print(json.dumps(dict(event='ready',application_group=str(owned.cgroup))),flush=True)
time.sleep(30)
"""
        caller="""import sys,json,os,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from bench_execution_domain import LifetimeDomain,LifetimeLimits,DomainLimits
owner=LifetimeDomain(LifetimeLimits(128*1024**2,16,25),DomainLimits(64*1024**2,8,25,1.5,8.,close_seconds=.5))
# Identities survive the caller before its first manager request.
Path(sys.argv[2]).write_text(json.dumps(dict(names=owner.names)))
owner.prepare()
owned=owner.start([sys.executable,'-I','-B','-c',sys.argv[3],sys.argv[1],json.dumps(owner.names)])
owner.go=True;owned.start()
deadline=time.monotonic()+5
while time.monotonic()<deadline:
 event=owned.event(.02)
 if event and event.get('event')=='ready':
  owner.application_created()
  Path(sys.argv[2]).write_text(json.dumps(dict(names=owner.names,helper_group=str(owned.cgroup),application_group=event['application_group'],ancestor=str(owner.cgroup),configuration=owner.configuration)))
  os._exit(29)
raise RuntimeError('Readiness missing')
"""
        result=subprocess.run([sys.executable,'-I','-B','-c',caller,str(ROOT/'tools'),str(record),helper],
                              capture_output=True,text=True,timeout=8.)
        self.assertEqual(result.returncode,29,result.stderr)
        facts=json.loads(record.read_text());names=facts['names']
        self.assertEqual(Path(facts['application_group']).parent,Path(facts['ancestor']))
        self.assertEqual(Path(facts['helper_group']).parent,Path(facts['ancestor']))
        def state(unit):
            r=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState,ControlGroup,Job'],
                             capture_output=True,text=True,timeout=2.)
            return dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
        try:
            deadline=time.monotonic()+6.
            while True:
                states={key:state(names[key]) for key in ('helper','application')}
                path=Path(facts['ancestor'])
                empty=not path.exists() or 'populated 0' in (path/'cgroup.events').read_text().splitlines()
                if empty and all(s.get('ActiveState') in ('inactive','failed') for s in states.values()):break
                if time.monotonic()>deadline:self.fail('Manager deadline did not close hierarchy')
                time.sleep(.03)
            print(json.dumps(dict(check='caller_death_manager_closure',facts=facts,states=states,empty=empty)),flush=True)
        finally:
            stopped=subprocess.run(['systemctl','--user','stop',names['slice']],capture_output=True,timeout=2.)
            self.assertEqual(stopped.returncode,0)

    def test_blocked_collection_cancel_preserves_caller_error_and_retry(self):
        owner=self.owner();original=RuntimeError('Synthetic caller failure')
        observed=[]
        event=supervisor.ComparisonSupervisor._checkpoint
        # Inspect only owned protocol observations. No fixture path polling is
        # used to establish collection or infer process closure.
        def check():
            if owner.progress and 'ancestor' in owner.progress:
                observed.append(owner.progress);raise original
            return event(owner)
        with patch.object(owner,'_checkpoint',side_effect=check), \
                patch.object(LifetimeDomain,'close',side_effect=TimeoutError('Synthetic closure')):
            with self.assertRaises(RuntimeError) as caught:self.run_owner(owner,'blocked')
        self.assertIs(caught.exception,original)
        self.assertIs(original.comparison_supervisor,owner)
        self.assertTrue(owner.control.exists());self.assertFalse(owner.closed)
        owner.close()
        self.assertTrue(owner.closed);self.assertIs(owner.terminal_error,original)
        self.assertFalse(owner.control.exists())
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result


if __name__=='__main__':unittest.main()

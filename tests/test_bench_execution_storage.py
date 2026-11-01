"""Disposable allocated-block enforcement and retained evidence. No real inputs."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from dataclasses import asdict, replace
import errno
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tools.experiments.bench_execution as execution
import tools.experiments.bench_execution_storage as storage
import tools.experiments.bench_execution_supervisor as supervisor
from tools.experiments.bench_comparison import ComparisonError, ComparisonProtocol
import test_bench_execution_supervisor as fixtures


class StorageDeclarationTests(unittest.TestCase):
    def test_storage_bounds_are_explicit_and_bind_protocol_identity(self):
        for pair in ((None, 4096), (True, 4096), (4096, None), (1, 4096), (8193, 4096)):
            with self.assertRaises(ValueError): storage.validate_limits(*pair)
        storage.validate_limits(None, None)
        storage.validate_limits(8192, 4096)
        envelope = execution.ExecutionEnvelope(4096, 4096, 128*1024**2, 4., 1, 8.)
        changed = replace(envelope, storage_bytes=1024**2, evidence_bytes=1024**2)
        self.assertNotEqual(execution.environment(envelope), execution.environment(changed))
        if sys.platform != 'linux':
            with patch.object(Path, 'mkdir', side_effect=AssertionError('Effect')):
                with self.assertRaisesRegex(ComparisonError, 'unsupported'):
                    storage.ExperimentalStorage(8192, 8192, 'unused', 1.)
            owner=supervisor.ComparisonSupervisor(dict(envelope=asdict(changed),output='unused',capture='missing-capture',source='missing-source',observation_root='missing-observation'))
            with patch.object(supervisor.admission,'require_execution'), \
                    patch.object(supervisor.tempfile,'mkdtemp',side_effect=AssertionError('Effect')):
                with self.assertRaisesRegex(ComparisonError,'unsupported'):owner.run()
            self.assertIsNone(owner.control)

    def test_fixed_bootstrap_uses_package_root_in_source_and_staged_layouts(self):
        owner=object.__new__(storage.ExperimentalStorage)
        owner.capacity=8192;owner.address='fixture-address';owner.nonce=b'fixture-nonce'
        child=['fixture-python','fixture-child.py','unchanged-argument']
        for filename,expected in ((storage.__file__,ROOT),
                ('/workspace/tools/tools/experiments/bench_execution_storage.py',Path('/workspace/tools').resolve())):
            with self.subTest(filename=filename),patch.object(storage,'__file__',filename):
                command=owner.command(child,[])
                index=command.index('-c')
                self.assertIn('from tools.experiments.bench_execution_storage import bootstrap',command[index+1])
                self.assertEqual(command[index+2:], [str(expected),'fixture-address','fixture-nonce',*child])
                self.assertIn('--unshare-pid',command)
                self.assertIn('--die-with-parent',command)

    def test_actual_worker_handler_classifies_sqlite_full_and_extended_codes(self):
        import sqlite3,io
        from contextlib import redirect_stdout
        import tools.experiments.bench_execution_worker as worker
        def full(unused):
            db=sqlite3.connect(':memory:')
            try:
                db.execute('PRAGMA max_page_count=1')
                db.execute('CREATE TABLE overflow(value)')
            finally:db.close()
        output=io.StringIO()
        with patch.object(worker,'run',full),redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:worker.main()
        self.assertEqual(caught.exception.code,1)
        event=json.loads(output.getvalue())
        self.assertEqual(event['reason'],'limit');self.assertEqual(event['error_type'],'OperationalError')
        extended=sqlite3.OperationalError('Synthetic extended code')
        extended.sqlite_errorcode=sqlite3.SQLITE_FULL|(2<<8)
        self.assertEqual(storage.failure_reason(extended),'limit')
        unrelated=sqlite3.OperationalError('Synthetic unrelated SQLite error')
        unrelated.sqlite_errorcode=sqlite3.SQLITE_CORRUPT
        self.assertEqual(storage.failure_reason(unrelated),'child_failed')

    def test_readonly_coordination_never_creates_files_and_uses_same_locks(self):
        import tempfile
        from backtest.runtime import cache_access as cache_access
        from website import runtime_access
        with tempfile.TemporaryDirectory(prefix='cb02-readonly-lock-') as folder:
            root = Path(folder); path = root / 'data/website-data-0.lock'
            observer = cache_access.WorkspaceAccess(path, read_only=True)
            with self.assertRaises(FileNotFoundError):
                with runtime_access.ownership(root, timeout=0, read_only=True): pass
            self.assertFalse((root / 'data').exists())
            with runtime_access.ownership(root, timeout=0):
                with cache_access.WorkspaceAccess(path).observe(): pass
            before = {p.name:p.read_bytes() for p in path.parent.iterdir()}
            with runtime_access.ownership(root, timeout=0, read_only=True):
                with observer.observe() as check: check()
            self.assertEqual(before, {p.name:p.read_bytes() for p in path.parent.iterdir()})
            with self.assertRaises(ValueError):
                with observer.hold(): pass
            # flock/LockFileEx must conflict on the SAME source inode.
            with runtime_access.ownership(root, timeout=0, read_only=True):
                with self.assertRaises(RuntimeError):
                    with runtime_access.ownership(root, exclusive=True, timeout=0): pass
            live = cache_access.WorkspaceAccess(path)
            with live.hold():
                self.assertTrue(observer.live_pending())
                with self.assertRaises(ValueError):
                    with observer.observe(): pass
            self.assertFalse(observer.live_pending())


@unittest.skipUnless(sys.platform == 'linux', 'Private WSL tmpfs; native aggregate storage unsupported')
class StorageLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.SupervisorTests('runTest'); self.base.setUp()
        self.addCleanup(self.cleanup_fixture)

    def cleanup_fixture(self):
        root = self.base.fixture.fixture.root
        if any(s.storage is not None and s.storage.output.is_relative_to(root)
               for s in supervisor._pending_supervisors.values()):
            # Keep the TemporaryDirectory finalizer from deleting pending proof.
            self.base.fixture.fixture.temporary._finalizer.detach()
            raise AssertionError('Pending storage owner retains synthetic root.')
        self.base.doCleanups()

    def owner(self, capacity=32*1024**2, evidence=40*1024**2):
        bound = self.base.fixture.owner(fixture_observation_root=None,
            coordinated_observation_root=self.base.fixture.fixture.source)
        bound.envelope = replace(bound.envelope, storage_bytes=capacity,
                                  evidence_bytes=evidence, close_seconds=10.)
        declaration = bound.protocol.value; declaration.pop('version')
        declaration['environment'] = execution.environment(bound.envelope)
        bound.protocol = ComparisonProtocol.freeze(**declaration)
        return supervisor.ComparisonSupervisor(supervisor.specification(bound))

    def code(self, body):
        return [sys.executable, '-I', '-B', '-c', 'import os,sys,json,time;from pathlib import Path;'
                'assert input()=="GO";\n' + body]

    def run_failed(self, owner, command, reason='child_failed'):
        with patch.object(supervisor.admission, 'require_execution'), \
                patch.object(owner, '_command', return_value=command):
            with self.assertRaisesRegex(ComparisonError, reason): owner.run()

    def records(self, owner):
        return storage.inspect_evidence(owner.storage.target)

    def test_actual_reference_both_numba_guards_inside_one_storage_boundary(self):
        from backtest.runtime import cache_access as cache_access; from website import runtime_access
        f = self.base.fixture.fixture
        with runtime_access.ownership(f.source, timeout=0):
            with cache_access.WorkspaceAccess(f.source / 'data/website-data-0.lock').observe(): pass
        before = f.immutable_bytes()
        owner = self.owner()
        with patch.object(supervisor.admission, 'require_execution'), \
                patch.object(owner, '_command', side_effect=self.base.fixture_command):
            owner.run()
        self.assertTrue(owner.closed); self.assertTrue(owner.storage.closed)
        self.assertEqual(owner.result['status'], 'fixture_pair_complete')
        self.assertEqual(before, f.immutable_bytes())
        records = self.records(owner)
        paths = [r['path'] for r in records['records']]
        for step in ('control_before', 'numba_source', 'numba_compiled', 'control_after'):
            self.assertTrue(any(p.endswith('/'+step+'/result.json') for p in paths))
        self.assertTrue(any(p.endswith('/domain.json') for p in paths))
        self.assertFalse(records['header']['accepted_result'])
        self.assertEqual(owner.evidence['capabilities']['disk']['status'], 'hard')
        print(json.dumps(dict(check='storage_financial_fixture', evidence=owner.evidence,
            container=dict(bytes=owner.storage.target.stat().st_size,
                committed=records['header']['committed'], entries=len(paths)))), flush=True)

    def test_aggregate_detached_compiler_writers_exhaust_without_host_spill(self):
        owner = self.owner(capacity=1024**2, evidence=2*1024**2)
        code = '''import subprocess
root=Path('/tmp/cb02-operation')
for name in ('source','compiler','journals','temporary','results'):(root/name).mkdir(exist_ok=True)
child="from pathlib import Path;import errno,os; p=Path('/tmp/cb02-operation/compiler/child');f=p.open('wb');e=0\\ntry:f.write(b'x'*800000);f.flush()\\nexcept OSError as error:e=error.errno\\nf.close();print(e,flush=True)"
a=subprocess.Popen([sys.executable,'-B','-c',child],stdout=subprocess.PIPE,start_new_session=True)
(root/'journals'/'first').write_bytes(b'y'*800000)
status=a.communicate(timeout=5)[0].decode().strip();assert status==str(errno.ENOSPC),status
(root/'compiler'/'child').unlink()
assert os.stat('/dev/shm').st_dev==root.stat().st_dev
Path('/dev/shm/charged').write_bytes(b'shared')
for dest in ('/var/tmp/cb02-spill',str(Path.home().parent.parent/'ambient-spill')):
 try:Path(dest).write_bytes(b'bad')
 except OSError as e:assert e.errno in (errno.EROFS,errno.EACCES,errno.ENOENT),e
 else:raise AssertionError(dest)
assert len(list(Path('/proc').glob('[0-9]*')))<12
(root/'quota.json').write_text(json.dumps(dict(errno=int(status))))
(root/'results'/'exhausted').write_bytes(b'z'*(2*1024**2))
'''
        # HOME is private; probe ambient host home explicitly instead.
        code = code.replace("str(Path.home().parent.parent/'ambient-spill')", repr(str(Path.home()/'cb02-forbidden-storage-spill')))
        # Run the actual worker error handler. The final write itself exhausts
        # the filesystem; the test does not manufacture its terminal reason.
        wrapper=('import sys;sys.path.insert(0,sys.argv[1]);'
                 'import tools.experiments.bench_execution_worker as w;assert input()=="GO";'
                 'w.run=lambda unused:exec('+repr('import os,json,errno,time\nfrom pathlib import Path\n'+code)+');w.main()')
        self.run_failed(owner, [sys.executable,'-I','-B','-c',wrapper,str(ROOT)], 'limit')
        self.assertTrue(owner.owned.descendants_empty)
        self.assertTrue(owner.storage.closed)
        self.assertTrue(any(r['path']=='quota.json' for r in self.records(owner)['records']))
        self.assertEqual(owner.storage.configuration['allocated_capacity'],1024**2)

    def test_sparse_lengths_are_distinct_and_evidence_limit_retains_owner(self):
        owner = self.owner(capacity=1024**2, evidence=2*1024**2)
        code="p=Path('/tmp/cb02-operation/sparse');f=p.open('wb');f.truncate(8*1024**2);f.close();assert p.stat().st_blocks==0"
        self.run_failed(owner, self.code(code))
        self.assertFalse(owner.closed)
        self.assertIs(supervisor._pending_supervisors[id(owner)],owner)
        self.assertIsNotNone(owner.storage.pin)
        pending=storage.inspect_evidence(owner.storage.pending)
        self.assertEqual(pending['header']['entries'],0)
        # Explicit disposition of this synthetic unsupported logical payload.
        (owner.storage.root/'sparse').unlink()
        owner.close()
        self.assertTrue(owner.closed)
        with self.assertRaisesRegex(ComparisonError,'incomplete'): _=owner.result

    def test_interrupted_collection_keeps_verified_prefix_and_retries(self):
        owner = self.owner()
        original=storage.ExperimentalStorage._copy_record
        def interrupt(s,path,fd,size,check):
            if s.header['entries']>=1: raise OSError('Synthetic interrupted collection')
            return original(s,path,fd,size,check)
        with patch.object(storage.ExperimentalStorage,'_copy_record',interrupt):
            self.run_failed(owner,self.code("r=Path('/tmp/cb02-operation');(r/'a').write_bytes(b'first');(r/'b').write_bytes(b'second')"))
        self.assertFalse(owner.closed)
        pending=storage.inspect_evidence(owner.storage.pending)
        self.assertEqual([r['path'] for r in pending['records']],['a'])
        self.assertFalse(pending['comparison_resumable'])
        self.assertEqual(owner.storage.pending.stat().st_size,owner.storage.evidence_bytes)
        owner.close()
        self.assertEqual([r['path'] for r in self.records(owner)['records']],['a','b'])
        self.assertTrue(owner.closed)
        with self.assertRaisesRegex(ComparisonError,'incomplete'): _=owner.result

    def test_publication_and_pin_release_failures_retain_explicit_retry(self):
        for stage in ('rename','pin'):
            with self.subTest(stage=stage):
                owner=self.owner()
                replace_path=Path.replace; close_fd=os.close
                def fail_rename(path,target):
                    if path.suffix=='.pending':raise OSError('Synthetic rename failure')
                    return replace_path(path,target)
                def fail_pin(fd):
                    if owner.storage is not None and fd==owner.storage.pin:raise OSError('Synthetic pin close failure')
                    return close_fd(fd)
                with patch.object(Path,'replace',fail_rename) if stage=='rename' else patch.object(os,'close',fail_pin):
                    self.run_failed(owner,self.code("Path('/tmp/cb02-operation/kept').write_bytes(b'evidence')"))
                self.assertFalse(owner.closed)
                self.assertIsNotNone(owner.storage.pin)
                self.assertTrue(owner.storage.pending.exists() if stage=='rename' else owner.storage.target.exists())
                owner.close()
                self.assertTrue(owner.closed)
                self.assertEqual(self.records(owner)['records'][0]['path'],'kept')

    def test_blocked_detached_writer_cancellation_and_original_cause_survive_retry(self):
        owner=self.owner(); cause=RuntimeError('Synthetic caller failure')
        def cancel():
            if owner.storage and owner.storage.pin is not None and (owner.storage.root/'started').exists():raise cause
            return False
        owner.cancel=cancel
        command=self.code("import subprocess\nsubprocess.Popen([sys.executable,'-B','-c',\"from pathlib import Path;import time;Path('/tmp/cb02-operation/started').touch();time.sleep(30)\"],start_new_session=True);time.sleep(30)")
        with patch.object(supervisor.admission,'require_execution'),patch.object(owner,'_command',return_value=command), \
                patch.object(storage.ExperimentalStorage,'_release',side_effect=OSError('Synthetic release failure')):
            with self.assertRaises(RuntimeError) as caught: owner.run()
        self.assertIs(caught.exception,cause)
        self.assertIs(cause.comparison_supervisor,owner)
        self.assertTrue(owner.owned.closed);self.assertFalse(owner.closed)
        owner.close();self.assertTrue(owner.closed)
        self.assertIs(owner.terminal_error,cause)
        with self.assertRaisesRegex(ComparisonError,'incomplete'): _=owner.result

    def test_file_count_and_symlinks_are_separate_collection_limits(self):
        for kind in ('count', 'symlink'):
            with self.subTest(kind=kind):
                owner=self.owner(capacity=1024**2,evidence=2*1024**2)
                code=("r=Path('/tmp/cb02-operation/files');r.mkdir();"
                      "[(r/str(i)).touch() for i in range(4097)]" if kind=='count' else
                      "Path('/tmp/cb02-operation/link').symlink_to('/etc/passwd')")
                self.run_failed(owner,self.code(code))
                self.assertFalse(owner.closed)
                self.assertIsNotNone(owner.storage.pin)
                if kind=='count':
                    for path in (owner.storage.root/'files').iterdir():path.unlink()
                else:(owner.storage.root/'link').unlink()
                owner.close();self.assertTrue(owner.closed)

    def test_invalid_transferred_filesystem_is_never_collected_or_given_GO(self):
        owner=self.owner()
        def command(original,unused,readonly):
            # This bootstrap sends a synthetic ordinary-directory descriptor.
            # It is rejected before any application GO or file traversal.
            code=("import socket,array,os,sys;"
                  "s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);"
                  "s.connect('\\0'+sys.argv[1]);fd=os.open(sys.argv[3],os.O_RDONLY|os.O_DIRECTORY);"
                  "s.sendmsg([sys.argv[2].encode()],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))]);"
                  "assert s.recv(1)==b'G';raise AssertionError('Unexpected GO')")
            return [sys.executable,'-B','-c',code,original.address,original.nonce.decode(),
                    str(self.base.fixture.fixture.capture)]
        with patch.object(storage.ExperimentalStorage,'command',command):
            self.run_failed(owner,self.code('pass'),'mismatch')
        self.assertTrue(owner.closed)
        self.assertEqual(self.records(owner)['records'],[])
        self.assertFalse(self.records(owner)['header']['storage_received'])

    def test_collection_and_publication_time_still_consume_finalization(self):
        from backtest.runtime import cache_access as cache_access; from website import runtime_access
        f=self.base.fixture.fixture
        with runtime_access.ownership(f.source,timeout=0):
            with cache_access.WorkspaceAccess(f.source/'data/website-data-0.lock').observe():pass
        owner=self.owner()
        owner.specification['protocol']['costs']['finalization']=2.
        declaration=dict(owner.specification['protocol']);declaration.pop('version')
        protocol=ComparisonProtocol.freeze(**declaration)
        owner.specification.update(protocol=protocol.value,protocol_sha256=protocol.identity)
        finish=storage.ExperimentalStorage.finish
        def delayed(s,**kwargs):
            result=finish(s,**kwargs);time.sleep(3.);return result
        with patch.object(supervisor.admission,'require_execution'), \
                patch.object(owner,'_command',side_effect=self.base.fixture_command), \
                patch.object(storage.ExperimentalStorage,'finish',delayed):
            with self.assertRaisesRegex(ComparisonError,'limit'):owner.run()
        self.assertTrue(owner.closed)
        self.assertLess(time.monotonic()-owner.started,owner.limit.wall_seconds)
        self.assertTrue(owner.storage.target.exists())
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_readonly_namespace_preserves_direct_edit_detection_and_live_priority(self):
        from backtest.runtime import cache_access as cache_access; from website import runtime_access
        f=self.base.fixture.fixture
        with runtime_access.ownership(f.source,timeout=0):
            with cache_access.WorkspaceAccess(f.source/'data/website-data-0.lock').observe():pass
        for kind,expected in (('edit','stale'),('live','busy')):
            with self.subTest(kind=kind):
                owner=self.owner();arrived=[];held=[]
                def command(request):
                    command=self.base.fixture_command(request)
                    code=command[4]
                    injection="""original_compare=e.MeasurementExecution.compare
def paused(owner):
 from pathlib import Path
 import time
 root=Path('/tmp/cb02-operation');(root/'paused').touch()
 deadline=time.monotonic()+5.
 while not (root/'release').exists():
  if time.monotonic()>deadline:raise TimeoutError('Fixture barrier')
  time.sleep(.005)
 return original_compare(owner)
e.MeasurementExecution.compare=paused
"""
                    command[4]=code.replace("with patch.object(c.admission",injection+"with patch.object(c.admission")
                    return command
                def arrival():
                    if owner.storage and owner.storage.pin is not None and not arrived and (owner.storage.root/'paused').exists():
                        arrived.append(True)
                        if kind=='edit':(f.source/'raw/financial-inputs/income/new.json').write_text('[]')
                        else:
                            context=cache_access.WorkspaceAccess(f.source/'data/website-data-0.lock').hold()
                            context.__enter__();held.append(context)
                        (owner.storage.root/'release').touch()
                    return False
                owner.cancel=arrival
                try:
                    with patch.object(supervisor.admission,'require_execution'),patch.object(owner,'_command',side_effect=command):
                        with self.assertRaisesRegex(ComparisonError,expected):owner.run()
                    self.assertTrue(arrived);self.assertTrue(owner.closed)
                finally:
                    for context in held:context.__exit__(None,None,None)
                    extra=f.source/'raw/financial-inputs/income/new.json'
                    if extra.exists():extra.unlink()

    def test_failed_initial_reservation_retains_file_and_recovers_without_launch(self):
        owner=self.owner()
        with patch.object(supervisor.admission,'require_execution'), \
                patch.object(os,'posix_fallocate',side_effect=OSError(errno.ENOSPC,'Synthetic reservation')), \
                patch.object(supervisor,'start_controller',side_effect=AssertionError('Launch')):
            with self.assertRaisesRegex(ComparisonError,'limit') as caught:owner.run()
        self.assertFalse(owner.closed)
        self.assertIs(caught.exception.comparison_supervisor,owner)
        self.assertTrue(owner.storage.pending.exists())
        self.assertIsNotNone(owner.storage.writer)
        owner.close()
        self.assertTrue(owner.closed)
        self.assertEqual(self.records(owner)['records'],[])
        self.assertEqual(owner.storage.target.stat().st_size,owner.storage.evidence_bytes)
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_invalid_host_outputs_create_no_files_and_preserve_originals(self):
        f=self.base.fixture.fixture
        before=f.immutable_bytes()
        link=f.root/'output-link';link.symlink_to(f.capture,target_is_directory=True)
        bad=(f.capture, f.capture/'child', f.source/'child', f.source, f.root, link/'child')
        for output in bad:
            with self.subTest(output=output):
                owner=self.owner();owner.specification['output']=str(output)
                with patch.object(supervisor.admission,'require_execution'), \
                        patch.object(supervisor.tempfile,'mkdtemp',side_effect=AssertionError('Control effect')):
                    with self.assertRaisesRegex(ComparisonError,'unsupported'):owner.run()
                self.assertIsNone(owner.control)
                self.assertEqual(before,f.immutable_bytes())
        # A destination swapped to a symlink during retained cleanup also
        # rejects before touching either original input directory.
        owner=self.owner();release=storage.ExperimentalStorage._release
        with patch.object(storage.ExperimentalStorage,'_release',side_effect=OSError('Synthetic release')):
            self.run_failed(owner,self.code("Path('/tmp/cb02-operation/kept').write_bytes(b'kept')"))
        original=owner.storage.output;retained=original.with_name('retained-output')
        original.rename(retained);original.symlink_to(f.capture,target_is_directory=True)
        try:
            with self.assertRaisesRegex(ComparisonError,'unsupported'):owner.close()
            self.assertFalse(owner.closed);self.assertEqual(before,f.immutable_bytes())
        finally:original.unlink();retained.rename(original)
        owner.close();self.assertTrue(owner.closed)

    def test_sqlite_exhaustion_uses_actual_worker_handler_and_retains_database_evidence(self):
        owner=self.owner(capacity=1024**2,evidence=2*1024**2)
        body="""import sqlite3
db=sqlite3.connect('/tmp/cb02-operation/period.sqlite')
try:
 db.execute('PRAGMA max_page_count=2')
 db.execute('CREATE TABLE book(value BLOB)');db.commit()
 db.execute('INSERT INTO book VALUES(randomblob(16384))');db.commit()
finally:db.close()
"""
        wrapper=('import sys;sys.path.insert(0,sys.argv[1]);'
                 'import tools.experiments.bench_execution_worker as w;assert input()=="GO";'
                 'w.run=lambda unused:exec('+repr(body)+');w.main()')
        self.run_failed(owner,[sys.executable,'-I','-B','-c',wrapper,str(ROOT)],'limit')
        self.assertTrue(owner.closed);self.assertTrue(owner.owned.descendants_empty)
        verified=self.records(owner)
        self.assertEqual(verified['header']['terminal_reason'],'limit')
        self.assertTrue(any(r['path']=='period.sqlite' for r in verified['records']))
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_real_controller_quota_exhaustion_reports_limit(self):
        owner=self.owner(capacity=4096,evidence=2*1024**2)
        with patch.object(supervisor.admission,'require_execution'), \
                patch.object(owner,'_command',side_effect=self.base.fixture_command):
            with self.assertRaisesRegex(ComparisonError,'limit'):owner.run()
        self.assertTrue(owner.closed);self.assertEqual(owner.remote_error_type,'OSError')
        self.assertEqual(self.records(owner)['header']['terminal_reason'],'limit')
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_final_receipt_exhaustion_reports_limit_after_confirmed_domain_close(self):
        from backtest.runtime import cache_access as cache_access; from website import runtime_access
        f=self.base.fixture.fixture
        with runtime_access.ownership(f.source,timeout=0):
            with cache_access.WorkspaceAccess(f.source/'data/website-data-0.lock').observe():pass
        owner=self.owner();write=Path.write_bytes
        def exhausted(path,data):
            if path.name=='domain.building':raise OSError(errno.ENOSPC,'Synthetic final receipt quota')
            return write(path,data)
        with patch.object(supervisor.admission,'require_execution'), \
                patch.object(owner,'_command',side_effect=self.base.fixture_command), \
                patch.object(Path,'write_bytes',exhausted):
            with self.assertRaisesRegex(ComparisonError,'limit'):owner.run()
        self.assertTrue(owner.closed);self.assertTrue(owner.owned.closed)
        with self.assertRaisesRegex(ComparisonError,'incomplete'):_=owner.result

    def test_startup_failure_before_transfer_has_bounded_interrupted_evidence(self):
        owner=self.owner()
        with patch.object(storage.ExperimentalStorage,'command',return_value=[sys.executable,'-c','raise SystemExit(7)']):
            self.run_failed(owner,self.code('pass'))
        self.assertTrue(owner.closed)
        self.assertFalse(self.records(owner)['header']['storage_received'])
        self.assertEqual(self.records(owner)['records'],[])



@unittest.skipUnless(sys.platform == 'linux', 'POSIX bounded-container recovery fixture')
class ContainerRecoveryTests(unittest.TestCase):
    def test_invalid_checksums_schemas_and_record_bounds_never_publish(self):
        import tempfile,hashlib,struct
        def emit(path,header,metadata=None,data=b'',raw_metadata=None):
            with path.open('w+b') as stream:
                stream.truncate(header.get('capacity',8192))
                if metadata is not None or raw_metadata is not None:
                    raw=raw_metadata if raw_metadata is not None else execution.encoded(metadata)
                    stream.seek(storage.HEADER_BYTES);stream.write(struct.pack('!I',len(raw))+raw+data)
                value=execution.encoded(dict(value=header,sha256=hashlib.sha256(execution.encoded(header)).hexdigest()))
                stream.seek(0);stream.write(value.ljust(storage.HEADER_BYTES//2,b'\0'))
        base=dict(version=1,capacity=8192,committed=4096,entries=0,state='ready',
                  run_id='a'*32,accepted_result=False,generation=2,
                  terminal_reason=None,storage_received=False)
        invalid=[dict(capacity=8193),dict(committed=4096.0),dict(entries=False),
                 dict(generation=True),dict(generation='2'),dict(generation=0),
                 dict(state=[]),dict(state='complete'),dict(run_id=3),dict(version=True),
                 dict(storage_received=0),dict(terminal_reason=['limit']),dict(entries=-1),
                 dict(committed=8193),dict(capacity=False),dict(capacity=2**63)]
        with tempfile.TemporaryDirectory(prefix='cb02-bad-container-') as folder:
            path=Path(folder)/'bad.pending'
            for change in invalid:
                with self.subTest(header=change):
                    h=dict(base,**change)
                    # Huge declarations are encoded against a small actual file.
                    if not isinstance(h['capacity'],int) or h['capacity']>10000:
                        h['capacity']=8192 if 'capacity' not in change else h['capacity']
                    with path.open('wb') as f:f.truncate(8192)
                    value=execution.encoded(dict(value=h,sha256=hashlib.sha256(execution.encoded(h)).hexdigest()))
                    with path.open('r+b') as f:f.write(value.ljust(2048,b'\0'))
                    with self.assertRaisesRegex(ComparisonError,'mismatch'):storage.recover_publication(path)
                    self.assertTrue(path.exists());self.assertFalse(path.with_suffix('.evidence').exists())
            good=dict(path='record',bytes=1,sha256=hashlib.sha256(b'x').hexdigest())
            variants=[[],None,dict(good,path='/absolute'),dict(good,path='a/'*33+'b'),
                      dict(good,path='a/../b'),dict(good,bytes=1.0),dict(good,sha256='bad'),
                      dict(good,path='a\\b'),dict(good,path='\udfff')]
            for metadata in variants:
                with self.subTest(metadata=repr(metadata)):
                    raw=json.dumps(metadata).encode()
                    h=dict(base,committed=4096+4+len(raw)+1,entries=1)
                    emit(path,h,raw_metadata=raw,data=b'x')
                    with self.assertRaisesRegex(ComparisonError,'mismatch'):storage.recover_publication(path)
                    self.assertTrue(path.exists())
            raw=execution.encoded(good)
            # The committed boundary cuts through metadata or payload.
            for cut in (4098,4096+4+len(raw),4096+4+len(raw)+2):
                emit(path,dict(base,committed=cut,entries=1),good,b'x')
                with self.assertRaisesRegex(ComparisonError,'mismatch'):storage.recover_publication(path)
                self.assertTrue(path.exists())

    def test_process_death_preserves_committed_prefix_and_ready_rename(self):
        # This is a container-format fixture. The namespace tests above supply
        # actual tmpfs enforcement and domain ownership evidence separately.
        import tempfile, subprocess
        with tempfile.TemporaryDirectory(prefix='cb02-container-recovery-') as folder:
            code='''import sys;sys.path.insert(0,sys.argv[1])
import os,sys
from pathlib import Path
import tools.experiments.bench_execution_storage as s
root=Path(sys.argv[2]);(root/'record').write_bytes(b'durable')
owner=s.ExperimentalStorage(1048576,1048576,root/sys.argv[3],5.)
owner.prepare();fd=os.open(root/'record',os.O_RDONLY)
owner._copy_record('record',fd,7,lambda:None);os.close(fd)
if sys.argv[3]=='ready':
 owner.header.update(state='ready',terminal_reason='interrupted',storage_received=False);owner._save_header()
else:
 owner._write_at(b'uncommitted-tail',owner.header['committed'])
 # Simulate a torn NEXT alternating header. The committed slot survives.
 slot=((owner.header['generation']+1)%2)*(s.HEADER_BYTES//2)
 owner._write_at(b'{torn',slot);os.fsync(owner.writer)
os._exit(29)
'''
            for kind in ('interrupted','ready'):
                result=subprocess.run([sys.executable,'-B','-c',code,str(ROOT),folder,kind],timeout=10)
                self.assertEqual(result.returncode,29)
                pending=next((Path(folder)/kind).glob('*.pending'))
                verified=storage.inspect_evidence(pending)
                self.assertEqual([r['path'] for r in verified['records']],['record'])
                self.assertEqual(verified['header']['committed'],4096+4+len(execution.encoded(verified['records'][0]))+7)
                if kind=='ready':
                    published=storage.recover_publication(pending)
                    self.assertTrue(published.exists());self.assertFalse(pending.exists())
                    self.assertFalse(storage.inspect_evidence(published)['header']['accepted_result'])
                else:
                    with self.assertRaisesRegex(ComparisonError,'incomplete'):storage.recover_publication(pending)
                    self.assertEqual(verified['uncollected_storage'],'lost_if_original_owner_is_gone')


class CollectedDomainRaceTests(unittest.TestCase):
    def test_failed_stop_accepts_absence_only_after_verified_creation(self):
        from types import SimpleNamespace
        from tools.experiments.bench_execution_domain import _UserService
        for settled in (False,True):
            owner=object.__new__(_UserService)
            owner._creation_settled=settled;owner._stop_confirmed=False
            owner.unit='synthetic-only'
            with patch.object(owner,'_state',side_effect=[{'LoadState':'loaded'},{'LoadState':'not-found'}]), \
                    patch.object(owner,'_control',return_value=SimpleNamespace(returncode=1)):
                if settled:
                    owner._stop_tree(0);self.assertTrue(owner._stop_confirmed)
                else:
                    with self.assertRaises(OSError):owner._stop_tree(0)
                    self.assertFalse(owner._creation_settled);self.assertFalse(owner._stop_confirmed)


if __name__=='__main__':unittest.main()

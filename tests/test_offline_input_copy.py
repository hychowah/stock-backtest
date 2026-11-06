"""Exact-byte offline capture and Git-bound old/current ownership interoperability."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tools.ops.offline_input_copy as copier
FIXTURE = ROOT/'tests/fixtures/offline-copy-ownership'
PEER = r'''
import importlib.util,sys,time
from pathlib import Path
fixture, source_root, root, kind, action, ready, release = sys.argv[1:]
sys.path.insert(0,source_root)
from backtest import paths
sys.modules['paths']=paths  # The retained qualified peer predates the package.
name = 'runtime_access' if kind=='source' else 'cache_access'
path = Path(fixture)/('website' if kind=='source' else 'scripts')/(name+'.py')
spec=importlib.util.spec_from_file_location('old_owner',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
root=Path(root)
owner = (module.ownership(root,timeout=0) if kind=='source' else
         module.WorkspaceAccess(root/'data/website-data-0.lock').hold(timeout=0))
try:
    with owner:
        if action=='probe': print('acquired',flush=True)
        else:
            Path(ready).write_text('ready')
            deadline=time.monotonic()+10
            while not Path(release).exists():
                if time.monotonic()>deadline: raise TimeoutError()
                time.sleep(.01)
except (ValueError,RuntimeError):
    if action=='probe': print('blocked',flush=True)
    else: raise
'''


class OfflineInputCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base/'original'; self.source.mkdir()
        self.destination = self.base/'copy'
        for relative in copier.FILES:
            path = self.source/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'null\n\x00\xff')
        for relative in copier.DIRECTORIES:
            path = self.source/relative; (path/'nested').mkdir(parents=True)
            (path/'nested/empty').write_bytes(b'')
            (path/'asset').write_bytes(bytes(range(256))*5000)
        (self.source/'data').mkdir()
        (self.source/'data/website-source.lock').write_bytes(b'source-lock')
        (self.source/'data/website-data-0.lock').write_bytes(b'financial-lock')
        for relative, digest in copier.OWNERSHIP_SOURCES.items():
            value = (FIXTURE/relative).read_bytes()
            self.assertEqual(hashlib.sha256(value).hexdigest(), digest)
            path = self.source/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        self.deployment = self.source/'data/deployment.json'
        self.deployment.write_text(json.dumps(dict(commit=copier.REVISION, files=copier.OWNERSHIP_SOURCES)))

    def run_copy(self, **kwargs):
        return copier.copy_inputs(self.source, self.destination, **kwargs)

    def original(self):
        return {p.relative_to(self.source).as_posix():p.read_bytes()
                for p in self.source.rglob('*') if p.is_file()}

    def assert_incomplete(self, result, status='failed', reason=None):
        self.assertEqual(result['status'], status, result)
        if reason: self.assertEqual(result['reason'], reason, result)
        self.assertFalse((self.destination/'complete.json').exists())

    def peer_command(self, kind, action, ready='', release=''):
        return [sys.executable, '-I', '-B', '-X', 'utf8', '-c', PEER, str(FIXTURE),
                str(ROOT), str(self.source),
                kind, action, str(ready), str(release)]

    @contextmanager
    def peer(self, kind):
        ready=self.base/(kind+'-ready'); release=self.base/(kind+'-release')
        child=subprocess.Popen(self.peer_command(kind, 'hold', ready, release),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+5
            while not ready.exists():
                if child.poll() is not None or time.monotonic()>deadline:
                    raise AssertionError('Old peer failed to acquire ownership')
                time.sleep(.01)
            yield
        finally:
            release.write_text('release')
            try: out,err=child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); out,err=child.communicate(); raise
            self.assertEqual(child.returncode,0,(out,err))

    def probe(self, kind):
        result=subprocess.run(self.peer_command(kind,'probe'), capture_output=True, timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        return result.stdout.strip()

    def test_exact_bytes_manifest_exclusions_and_originals(self):
        # The frozen report and its history are records, not preparation inputs.
        for relative in ('raw/archive/old', 'data/research.sqlite', 'data/schedules.sqlite',
                         'data/saved-backtests.sqlite', 'data/backtest-queue.sqlite', 'results/summary-exits.txt',
                         'results/baseline-history/old', '.env', 'website/local/index.html'):
            path=self.source/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'excluded')
        before=self.original(); result=self.run_copy()
        self.assertEqual(result['status'],'complete',result)
        marker=json.loads((self.destination/'complete.json').read_bytes())
        packed=(self.destination/'manifest.json.gz').read_bytes()
        self.assertEqual(marker['manifest_sha256'],hashlib.sha256(packed).hexdigest())
        manifest=json.loads(gzip.decompress(packed))
        self.assertEqual(manifest['version'],2);self.assertNotIn('through',manifest)
        self.assertLessEqual(manifest['charged_bytes'],copier.MAX_BYTES)
        self.assertFalse(manifest['preparation']);self.assertFalse(manifest['financial_calculation'])
        expected=copier._inventory(self.source,lambda:None)
        self.assertEqual(set(manifest['files']),set(expected))
        actual={p.relative_to(self.destination).as_posix() for p in self.destination.rglob('*') if p.is_file()}
        self.assertEqual(actual,set(expected)|{'complete.json','manifest.json.gz'})
        for name, row in manifest['files'].items():
            self.assertEqual((self.destination/name).read_bytes(),before[name])
            self.assertEqual(hashlib.sha256(before[name]).hexdigest(),row['sha256'])
        self.assertEqual(self.original(),before)

    def test_existing_destination_and_overlap_preserved(self):
        self.destination.mkdir();(self.destination/'keep').write_bytes(b'keep')
        self.assert_incomplete(self.run_copy(),reason='destination_exists')
        self.assertEqual((self.destination/'keep').read_bytes(),b'keep')
        result=copier.copy_inputs(self.source,self.source/'nested')
        self.assertEqual(result['reason'],'overlapping_paths')

    def test_unknown_revision_and_ownership_source_defer(self):
        original=self.deployment.read_bytes()
        self.deployment.write_text(json.dumps(dict(commit='unknown')))
        self.assert_incomplete(self.run_copy(),'deferred','unqualified_revision')
        self.deployment.write_bytes(original)
        (self.source/'scripts/cache_access.py').write_bytes(b'changed')
        self.assert_incomplete(self.run_copy(),'deferred','unqualified_ownership_source')

    def test_pending_publications_and_sidecars_defer(self):
        for name in ('deployment.pending.json','research.sqlite.publication.json','research.sqlite-wal',
                     'research.sqlite-shm','research.sqlite-journal','schedules.sqlite-wal'):
            path=self.source/'data'/name;path.write_bytes(b'pending')
            self.assert_incomplete(self.run_copy(),'deferred')
            path.unlink()

    def test_missing_or_uninitialized_lock_not_created(self):
        lock=self.source/'data/website-data-0.lock';lock.write_bytes(b'')
        self.assert_incomplete(self.run_copy(),reason='uninitialized_lock')
        lock.unlink();self.assert_incomplete(self.run_copy())
        self.assertFalse(lock.exists())

    def test_source_link_rejected(self):
        target=self.source/'raw/px/link'
        try: target.symlink_to(self.source/'raw/universe.json')
        except OSError as error: self.skipTest('Native symlink creation unavailable: '+str(error.errno))
        self.assert_incomplete(self.run_copy(),reason='linked_path')

    def test_reparse_metadata_rejected(self):
        original=copier._plain
        class Linked:
            st_mode=0o100644;st_file_attributes=0x400
        with patch.object(copier.Path,'lstat',return_value=Linked()):
            with self.assertRaises(copier.CopyError): original(self.source/'raw/universe.json')

    @unittest.skipUnless(os.name!='nt','POSIX FIFO fixture')
    def test_special_file_rejected(self):
        os.mkfifo(self.source/'raw/px/fifo')
        self.assert_incomplete(self.run_copy(),reason='unsupported_file_type')

    def test_budget_errors_publish_no_marker(self):
        self.assert_incomplete(self.run_copy(max_bytes=1),reason='storage_limit')
        self.assert_incomplete(self.run_copy(max_bytes=copier.MAX_BYTES+1),reason='invalid_budget')

    def test_source_same_size_same_mtime_mutation_detected(self):
        original=copier._copy_file
        changed=False;mutation_lock=threading.Lock()
        def mutate(source,target,expected,check):
            nonlocal changed
            digest=original(source,target,expected,check)
            with mutation_lock:
                if not changed and expected['bytes']:
                    changed=True;content=source.read_bytes();source.write_bytes(bytes([content[0]^1])+content[1:])
                    os.utime(source,ns=(expected['mtime_ns'],expected['mtime_ns']))
            return digest
        with patch.object(copier,'_copy_file',side_effect=mutate):
            self.assert_incomplete(self.run_copy(),reason='source_changed')

    def test_added_and_removed_source_files_detected(self):
        original=copier._copy_file
        def add(source,target,expected,check):
            digest=original(source,target,expected,check)
            (self.source/'raw/px/new').write_bytes(b'new')
            return digest
        with patch.object(copier,'_copy_file',side_effect=add):
            self.assert_incomplete(self.run_copy(),reason='source_changed')
        second=self.base/'second'
        def remove(source,target,expected,check):
            digest=original(source,target,expected,check)
            if source.name=='asset': source.unlink()
            return digest
        with patch.object(copier,'_copy_file',side_effect=remove):
            result=copier.copy_inputs(self.source,second)
        self.assertEqual(result['reason'],'source_changed',result)
        self.assertFalse((second/'complete.json').exists())

    def test_destination_corruption_detected(self):
        original=copier._copy_file
        def corrupt(source,target,expected,check):
            digest=original(source,target,expected,check);target.write_bytes(b'corrupt');return digest
        with patch.object(copier,'_copy_file',side_effect=corrupt):
            self.assert_incomplete(self.run_copy(),reason='destination_mismatch')

    def test_same_size_same_mtime_destination_corruption_detected(self):
        original=copier._copy_file
        def corrupt(source,target,expected,check):
            digest=original(source,target,expected,check)
            content=target.read_bytes()
            if content:
                target.write_bytes(bytes([content[0]^1])+content[1:])
                os.utime(target,ns=(expected['mtime_ns'],expected['mtime_ns']))
            return digest
        with patch.object(copier,'_copy_file',side_effect=corrupt):
            self.assert_incomplete(self.run_copy(),reason='destination_mismatch')

    def test_cancellation_releases_owners_and_preserves_partial_retry(self):
        before=self.original()
        def cancel():
            if self.destination.exists():raise TimeoutError()
        self.assert_incomplete(self.run_copy(checkpoint=cancel))
        self.assertTrue((self.destination/'failure.json').exists())
        self.assertEqual(self.probe('source'),b'acquired')
        self.assertEqual(self.probe('cache'),b'acquired')
        retry=self.base/'retry'
        self.assertEqual(copier.copy_inputs(self.source,retry)['status'],'complete')
        self.assertTrue((self.destination/'failure.json').exists())
        self.assertEqual(self.original(),before)

    def test_write_and_publication_failure_no_complete_marker(self):
        with patch.object(copier,'_copy_file',side_effect=OSError(28,'fixture')):
            self.assert_incomplete(self.run_copy())
        self.destination=self.base/'publish-failure'
        original=copier.Path.replace
        def fail_marker(path,target):
            if path.name=='complete.pending':raise OSError(5,'fixture')
            return original(path,target)
        with patch.object(copier.Path,'replace',fail_marker):
            self.assert_incomplete(self.run_copy())
        self.assertTrue((self.destination/'manifest.json.gz').exists())

    def test_old_shared_source_blocks_copy_then_releases(self):
        before=self.original()
        with self.peer('source'):
            self.assert_incomplete(self.run_copy(),'deferred','source_busy_or_pending')
            self.assertFalse(self.destination.exists())
        self.assertEqual(self.run_copy()['status'],'complete')
        self.assertEqual(self.original(),before)

    def test_old_financial_owner_blocks_read_only_copy_then_releases(self):
        before=self.original()
        with self.peer('cache'):
            self.assert_incomplete(self.run_copy(),'deferred','cache_busy')
            self.assertFalse(self.destination.exists())
        self.assertEqual(self.run_copy()['status'],'complete')
        self.assertEqual(self.original(),before)

    def test_copy_excludes_old_shared_startup_and_financial_peer(self):
        seen=False;before=self.original()
        def check():
            nonlocal seen
            if self.destination.exists() and not seen:
                seen=True
                self.assertEqual(self.probe('source'),b'blocked')
                self.assertEqual(self.probe('cache'),b'blocked')
        self.assertEqual(self.run_copy(checkpoint=check)['status'],'complete')
        self.assertTrue(seen)
        self.assertEqual(self.probe('source'),b'acquired')
        self.assertEqual(self.probe('cache'),b'acquired')
        self.assertEqual(self.original(),before)

    def test_new_live_intent_defers_without_destination(self):
        with patch.object(copier.cache_access.WorkspaceAccess,'live_pending',return_value=True):
            self.assert_incomplete(self.run_copy(),'deferred','live_intent')
        self.assertFalse(self.destination.exists())

    def test_bounded_overlap_out_of_order_and_callback_thread(self):
        barrier=threading.Barrier(4,timeout=5);lock=threading.Lock()
        active=maximum=0;callbacks=[];results=[];caller=threading.get_ident()
        outstanding=maximum_outstanding=0
        class CountingExecutor(copier.ThreadPoolExecutor):
            def submit(executor,*args,**kwargs):
                nonlocal outstanding,maximum_outstanding
                outstanding+=1;maximum_outstanding=max(maximum_outstanding,outstanding)
                self.assertLessEqual(outstanding,4)
                return super().submit(*args,**kwargs)
        def accept(result):
            nonlocal outstanding
            outstanding-=1;results.append(result)
        def work(item,stop):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active)
            try:
                if item<4:barrier.wait()
                time.sleep((4-item%4)*.002);stop();return item
            finally:
                with lock:active-=1
        with patch.object(copier,'ThreadPoolExecutor',CountingExecutor):
            copier._file_pass(range(20),work,accept,lambda:callbacks.append(threading.get_ident()))
        self.assertEqual(maximum,4);self.assertEqual(active,0)
        self.assertEqual(maximum_outstanding,4);self.assertEqual(outstanding,0)
        self.assertEqual(sorted(results),list(range(20)))
        self.assertTrue(callbacks);self.assertEqual(set(callbacks),{caller})

    def test_worker_failure_stops_submission_and_joins_every_started_task(self):
        barrier=threading.Barrier(4,timeout=5);lock=threading.Lock();started=[];closed=[]
        def work(item,stop):
            with lock:started.append(item)
            try:
                barrier.wait()
                if item==0:raise OSError(5,'synthetic worker failure')
                while True:time.sleep(.001);stop()
            finally:
                with lock:closed.append(item)
        with self.assertRaises(OSError):
            copier._file_pass(range(20),work,lambda result:None,lambda:None)
        self.assertEqual(set(started),set(range(4)));self.assertEqual(set(closed),set(started))

    def test_active_cancellation_closes_handles_before_releasing_ownership(self):
        lock=threading.Lock();started=[];closed=[];probed=False
        def work(source,target,expected,stop):
            nonlocal probed
            with lock:started.append(target)
            try:
                with target.open('xb'):
                    while True:time.sleep(.001);stop()
            finally:
                with lock:
                    if not probed:
                        probed=True
                        self.assertEqual(self.probe('source'),b'blocked')
                        self.assertEqual(self.probe('cache'),b'blocked')
                    closed.append(target)
        def cancel():
            with lock:
                if len(started)==4:raise TimeoutError()
        with patch.object(copier,'_copy_file',side_effect=work):
            self.assert_incomplete(self.run_copy(checkpoint=cancel))
        self.assertEqual(len(started),4);self.assertEqual(set(closed),set(started));self.assertTrue(probed)
        for path in started:path.unlink() # Native Windows refuses this if a writer escaped.
        self.assertEqual(self.probe('source'),b'acquired');self.assertEqual(self.probe('cache'),b'acquired')

    def test_worker_read_and_final_verification_failures_are_incomplete(self):
        original=copier.Path.open
        def fail_read(path,*args,**kwargs):
            if str(path).startswith(str(self.source/'raw/px')) and args and args[0]=='rb':
                raise OSError(5,'synthetic read failure')
            return original(path,*args,**kwargs)
        with patch.object(copier.Path,'open',fail_read):self.assert_incomplete(self.run_copy())
        self.destination=self.base/'verification-failure';original_hash=copier._hash
        def fail_hash(path,stop):
            if str(path).startswith(str(self.destination/'raw/px')):
                raise OSError(5,'synthetic verification read failure')
            return original_hash(path,stop)
        with patch.object(copier,'_hash',side_effect=fail_hash):self.assert_incomplete(self.run_copy())
        self.assertEqual(self.probe('source'),b'acquired');self.assertEqual(self.probe('cache'),b'acquired')

    def test_four_simultaneous_larger_files_preserve_exact_bytes(self):
        content=bytes(range(256))*(2*copier.BUFFER//256)
        for n in range(4):(self.source/'raw/px'/('large%d'%n)).write_bytes(content)
        result=self.run_copy();self.assertEqual(result['status'],'complete',result)
        for n in range(4):self.assertEqual((self.destination/'raw/px'/('large%d'%n)).read_bytes(),content)

    def test_allocation_includes_nonresident_file_rounding(self):
        path=self.base/'allocation';unit=copier._allocation_unit(self.base)
        path.write_bytes(b'x'*(unit+1))
        allocated=copier._allocation(path)
        self.assertGreaterEqual(allocated,unit+1)
        self.assertEqual(allocated%unit,0)
        path.unlink() # Attribute handles must close even on native Windows.


if __name__=='__main__':
    unittest.main()

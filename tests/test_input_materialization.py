"""A mutable workspace has initial provenance, not an immutable capture marker."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_offline_input_copy as fixtures
copier=fixtures.copier


class MaterializationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OfflineInputCopyTests('test_exact_bytes_manifest_exclusions_and_originals')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        result=self.fixture.run_copy();self.assertEqual(result['status'],'complete',result)
        self.capture=self.fixture.destination;self.destination=self.fixture.base/'working'
        self.digest=result['manifest_sha256']

    def materialize(self,**kwargs):
        return copier.materialize_inputs(self.capture,self.destination,expected_manifest_sha256=self.digest,**kwargs)

    def failed(self,result):
        self.assertEqual(result['status'],'failed',result)
        self.assertFalse((self.destination/'input-provenance.json').exists())
        self.assertFalse((self.destination/'complete.json').exists())

    def rewrite_manifest(self,change):
        path=self.capture/'manifest.json.gz';data=json.loads(gzip.decompress(path.read_bytes()));change(data)
        packed=gzip.compress(json.dumps(data).encode(),mtime=0);path.write_bytes(packed)
        self.digest=hashlib.sha256(packed).hexdigest()
        (self.capture/'complete.json').write_text(json.dumps(dict(version=1,manifest_sha256=self.digest)))

    def test_independent_exact_payload_and_initial_provenance(self):
        before={p.relative_to(self.capture).as_posix():p.read_bytes() for p in self.capture.rglob('*') if p.is_file()}
        result=self.materialize();self.assertEqual(result['status'],'materialized',result)
        record=json.loads((self.destination/'input-provenance.json').read_bytes())
        self.assertEqual(record['capture_manifest_sha256'],self.digest);self.assertFalse(record['prepared_freshness'])
        expected=copier._inventory(self.capture,lambda:None)
        self.assertEqual(copier._inventory(self.destination,lambda:None),expected)
        for name in expected:
            self.assertEqual((self.destination/name).read_bytes(),before[name])
            self.assertNotEqual((self.destination/name).stat().st_ino,(self.capture/name).stat().st_ino)
        self.assertFalse((self.destination/'complete.json').exists())
        (self.destination/'raw/universe.json').write_bytes(b'ordinary later download')
        self.assertEqual({p.relative_to(self.capture).as_posix():p.read_bytes() for p in self.capture.rglob('*') if p.is_file()},before)

    def test_version_one_capture_with_the_report_is_refused(self):
        self.rewrite_manifest(lambda d:d.update(version=1,through='2026-10-21'))
        self.failed(self.materialize());self.assertFalse(self.destination.exists())

    def test_changed_manifest_and_missing_completion_fail_before_creation(self):
        (self.capture/'manifest.json.gz').write_bytes(b'changed')
        self.failed(self.materialize());self.assertFalse(self.destination.exists())

    def test_missing_completion_is_not_a_capture(self):
        (self.capture/'complete.json').unlink();self.failed(self.materialize());self.assertFalse(self.destination.exists())

    def test_unsafe_paths_and_case_collisions_fail_before_creation(self):
        self.rewrite_manifest(lambda d:d['files'].update({'raw/px/../outside':dict(bytes=0,mtime_ns=0,sha256='0'*64)}))
        self.failed(self.materialize());self.assertFalse(self.destination.exists())

    def test_file_directory_collision_is_rejected(self):
        self.rewrite_manifest(lambda d:d['files'].update({'raw/px/asset/child':dict(bytes=0,mtime_ns=0,sha256='0'*64)}))
        self.failed(self.materialize());self.assertFalse(self.destination.exists())

    def test_case_collision_is_rejected(self):
        self.rewrite_manifest(lambda d:d['files'].update({'raw/px/ASSET':dict(bytes=0,mtime_ns=0,sha256='0'*64)}))
        self.failed(self.materialize());self.assertFalse(self.destination.exists())

    def test_extra_or_missing_payload_file_is_rejected(self):
        path=self.capture/'raw/px/extra';path.write_bytes(b'extra');self.failed(self.materialize());path.unlink()
        (self.capture/'raw/px/nested/empty').unlink();self.failed(self.materialize())

    def test_same_size_same_time_corruption_is_rejected(self):
        path=self.capture/'raw/universe.json';stamp=path.stat().st_mtime_ns
        data=path.read_bytes();path.write_bytes(bytes([data[0]^1])+data[1:]);os.utime(path,ns=(stamp,stamp))
        self.failed(self.materialize())

    def test_existing_con_ticker_filename_is_preserved_verbatim(self):
        path=self.capture/'raw/px/CON.json';content=b'{"symbol":"CON","div":[]}'
        temporary=path.with_name('ticker.pending');temporary.write_bytes(content);temporary.replace(path)
        info=path.stat()
        def add(data):
            data['files']['raw/px/CON.json']=dict(bytes=len(content),mtime_ns=info.st_mtime_ns,sha256=hashlib.sha256(content).hexdigest())
            data['logical_bytes']+=len(content)
        self.rewrite_manifest(add)
        result=self.materialize();self.assertEqual(result['status'],'materialized',result)
        self.assertEqual((self.destination/'raw/px/CON.json').read_bytes(),content)

    def test_cancel_and_publication_failure_leave_no_provenance(self):
        def cancel():
            if self.destination.exists():raise TimeoutError()
        self.failed(self.materialize(checkpoint=cancel))
        self.destination=self.fixture.base/'publish-failure';original=copier.Path.replace
        def fail(path,target):
            if path.name=='input-provenance.pending':raise OSError(5,'fixture')
            return original(path,target)
        with patch.object(copier.Path,'replace',fail):self.failed(self.materialize())

    def test_reused_destination_is_preserved(self):
        self.destination.mkdir();path=self.destination/'keep';path.write_bytes(b'keep')
        self.failed(self.materialize());self.assertEqual(path.read_bytes(),b'keep')

    def test_malformed_lengths_and_duplicate_json_keys_are_rejected(self):
        self.rewrite_manifest(lambda d:d['files']['raw/universe.json'].update(bytes=True))
        self.failed(self.materialize());self.assertFalse(self.destination.exists())
        with self.assertRaises(copier.CopyError):json.loads('{"a":1,"a":2}',object_pairs_hook=copier._unique_object)

    @unittest.skipUnless(os.name!='nt','POSIX FIFO fixture')
    def test_special_manifest_is_rejected_without_opening_it(self):
        path=self.capture/'manifest.json.gz';path.unlink();os.mkfifo(path)
        self.failed(self.materialize());self.assertFalse(self.destination.exists())


if __name__=='__main__':unittest.main()

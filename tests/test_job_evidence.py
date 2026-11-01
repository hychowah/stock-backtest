"""Temporary Jobs evidence lifetimes, charges and failed cleanup; no user stores."""
from contextlib import ExitStack
import hashlib
import io
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website'),str(ROOT/'tests')]
import job_evidence
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest import result_evidence as result_evidence
from test_trial_checkpoints import completed


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)/'owned';self.owner=job_evidence.Workspace(self.root,max_bytes=2*1024**2)
        self.addCleanup(self.owner.close)

    def reserve(self,**kw):return self.owner.reserve(max_bytes=65536,planned=None,piece_bytes=65536,record_bytes=65536,**kw)

    def publish(self,entry):
        original=completed()
        with self.owner.destination(entry) as stream:
            writer=result_evidence.Writer(stream,trials=1,metadata={'label':'original 測試'},**entry['limits'])
            writer.start_trial(1)
            for period in original['periods']:writer.period(period)
            writer.end_trial({k:v for k,v in original.items() if k!='periods'});manifest=writer.finish({})
            stream.seek(0);data=stream.read()
        return self.owner.publish(entry,dict(transfer=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()),manifest=manifest))

    def test_accounting_staging_retention_expiry_and_concurrent_readers(self):
        entry=self.reserve();before=self.owner.measurements()
        self.assertEqual(before['staging_bytes'],2*65536+2*65536)
        descriptor=self.publish(entry);self.assertEqual(self.owner.measurements()['retained_bytes'],descriptor['bytes'])
        with self.owner.reader(entry) as first,self.owner.reader(entry) as second:
            self.assertEqual(first.metadata,second.metadata)
            self.assertEqual(self.owner.measurements()['active_readers'],2)
            self.owner.discard(entry)
            self.assertTrue((entry['path']/'completed.evidence').exists())
            self.assertEqual(len(list(first.trials())),1)
            self.assertGreater(self.owner.measurements()['retained_bytes'],0)
            with self.assertRaises(ValueError):
                with self.owner.reader(entry):pass
        self.assertEqual(self.owner.measurements()['reserved_bytes'],0)
        self.assertFalse(entry['path'].exists())

    def test_budget_exhaustion_preserves_completed_evidence(self):
        entry=self.reserve();descriptor=self.publish(entry)
        self.owner.max_bytes=descriptor['bytes']+1
        with self.assertRaisesRegex(ValueError,'exhausted'):self.reserve()
        with self.owner.reader(entry) as reader:self.assertEqual(reader.manifest['trials'],1)

    def test_partial_staging_and_failed_cleanup_remain_charged_then_retry(self):
        entry=self.reserve()
        with self.owner.destination(entry) as stream:stream.write(b'partial')
        original=Path.unlink
        def fail(path,*a,**kw):
            if path.name=='receiving.evidence':raise PermissionError('fictional native sharing lock')
            return original(path,*a,**kw)
        with patch.object(Path,'unlink',fail):
            self.owner.discard(entry)
            self.assertGreater(self.owner.measurements()['retained_bytes'],0)
            with self.assertRaisesRegex(OSError,'incomplete'):self.owner.close()
        self.owner.collect();self.assertEqual(self.owner.measurements()['reserved_bytes'],0)

    def test_close_waits_for_active_reader_and_immutable_binding_rejects_replacement(self):
        entry=self.reserve();self.publish(entry);entered=Event();done=Event()
        with self.owner.reader(entry) as reader:
            def close():entered.set();self.owner.close();done.set()
            thread=Thread(target=close);thread.start();self.assertTrue(entered.wait(1))
            time.sleep(.02);self.assertFalse(done.is_set());self.assertTrue(list(reader.trials()))
        thread.join(2);self.assertTrue(done.is_set())
        other=job_evidence.Workspace(self.root,max_bytes=1024**2);self.owner=other;self.addCleanup(other.close)
        entry=self.reserve();self.publish(entry)
        path=entry['path']/'completed.evidence';path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaises(ValueError):
            with self.owner.reader(entry):pass
        self.assertEqual(self.owner.measurements()['active_readers'],0)


if __name__=='__main__':unittest.main()

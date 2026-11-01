"""Recoverable queue-to-library handoff on private eager and v3 fixtures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
from copy import deepcopy
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'website'),str(ROOT/'tests')]
from backtest.application import queue as queue
from backtest.application import library as saved
from test_saved_backtests import snapshot
from test_durable_evidence import source,submission
from test_queue import request


class TransferTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.store=queue.Store(self.root/'queue.sqlite')
        self.library=saved.Store(self.root/'library.sqlite')
        self.consumer=queue.Queue(self.store,library=self.library)
        self.addCleanup(self.consumer.close)

    def eager(self):
        spec=request();self.store.enqueue(spec);self.store.claim()
        value=snapshot('custom');value['version']=2;value['presentation']={}
        self.store.finish(spec['id'],'complete',snapshot=value)
        return spec,value

    def evidence(self):
        reader,metadata,original=source('random');spec=submission(metadata)
        self.store.enqueue(spec);self.store.claim()
        self.store.progress(spec['id'],'configuration',reader.metadata['configuration'])
        self.store.finish_evidence(spec['id'],metadata,reader)
        return spec,reader,metadata,original

    def sql(self,path,statement):
        with closing(sqlite3.connect(path)) as db:return db.execute(statement).fetchall()

    def test_eager_transfer_is_independent_archived_and_retries_do_not_execute(self):
        spec,value=self.eager();self.consumer.reconcile_completed()
        archived=self.store.get(spec['id']);saved_id=archived['transfer']['saved_id']
        self.assertEqual(archived['state'],'archived');self.assertNotIn('snapshot',archived)
        self.assertEqual(self.library.get(saved_id)['snapshot'],value)
        self.assertEqual(self.store.listing()['records'],[])
        self.assertEqual(self.store.listing()['library_revision'],1)
        self.assertEqual(self.store.enqueue(spec)['state'],'archived')
        self.assertTrue(self.store.accepted(spec['id']));self.assertIsNone(self.store.claim())
        self.store.finish(spec['id'],'complete',snapshot=deepcopy(value))
        different=deepcopy(value);different['result']['cagr']=.123
        with self.assertRaises(queue.Conflict):self.store.finish(spec['id'],'complete',snapshot=different)
        self.assertEqual(self.sql(self.store.path,'SELECT snapshot FROM jobs'),[(None,)])
        self.consumer.reconcile_completed();self.assertEqual(len(self.library.list()),1)

    def test_library_receipt_precedes_capacity_and_preserves_rename_and_deletion(self):
        value=snapshot('custom');identifier='a'*32
        with patch.object(saved,'LIMIT',1):
            imported=self.library.accept_queue_result(identifier,'First',lambda:nullcontext(value))
            saved_id=imported['saved_id'];self.library.rename(saved_id,'Renamed')
            receipt=saved.Store(self.library.path).accept_queue_result(identifier,'Old name',lambda:nullcontext(value))
            self.assertEqual(receipt['record']['name'],'Renamed');self.assertEqual(receipt['saved_id'],saved_id)
            self.library.delete(saved_id)
            self.library.save('Another record',value)
            receipt=self.library.accept_queue_result(identifier,'Old name',lambda:self.fail('A receipt must not open the source'))
            self.assertTrue(receipt['deleted']);self.assertEqual(receipt['saved_id'],saved_id)
            self.assertEqual(len(self.library.list()),1)

    def test_concurrent_imports_commit_one_record_and_receipt(self):
        value=snapshot('custom')
        def accept(_):return saved.Store(self.library.path).accept_queue_result('b'*32,'First',lambda:nullcontext(value))['saved_id']
        with ThreadPoolExecutor(max_workers=8) as workers:identifiers=list(workers.map(accept,range(16)))
        self.assertEqual(len(set(identifiers)),1);self.assertEqual(len(self.library.list()),1)
        self.assertEqual(len(self.sql(self.library.path,'SELECT * FROM queue_imports')),1)

    def test_failed_library_receipt_rolls_back_both_publication_formats(self):
        for evidence in (False,True):
            with self.subTest(evidence=evidence):
                if evidence:spec,reader,metadata,_=self.evidence()
                else:spec,_=self.eager()
                before_receipts=self.sql(self.library.path,'SELECT * FROM queue_imports') if self.library.path.exists() else []
                db=self.library.connect()
                try:
                    db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON queue_imports BEGIN SELECT RAISE(ABORT,'interrupted'); END")
                finally:db.close()
                self.consumer.reconcile_completed()
                record=self.store.get(spec['id']) if not evidence else self.store.listing()['records'][0]
                self.assertEqual(record['state'],'complete');self.assertEqual(record['transfer']['error'],'retry')
                self.assertEqual(self.library.list(),[])
                self.assertEqual(self.sql(self.library.path,'SELECT * FROM evidence_chunks'),[])
                self.assertEqual(self.sql(self.library.path,'SELECT * FROM queue_imports'),before_receipts)
                db=self.library.connect()
                try:db.execute('DROP TRIGGER fail_import')
                finally:db.close()
                self.consumer.reconcile_completed()
                self.assertEqual(self.store.get(spec['id'])['state'],'archived')
                self.library.delete(self.library.list()[0]['id'])

    def test_interruption_after_library_commit_preserves_renamed_or_deleted_result(self):
        for deleted in (False,True):
            with self.subTest(deleted=deleted):
                spec,_=self.eager()
                with patch.object(self.store,'archive_completed',side_effect=OSError('interrupted acknowledgment')):
                    self.consumer.reconcile_completed()
                self.assertEqual(self.store.get(spec['id'])['state'],'complete')
                saved_id=self.library.list()[0]['id']
                if deleted:self.library.delete(saved_id)
                else:self.library.rename(saved_id,'Renamed after commit')
                # Restart clears any interrupted reservation and uses its receipt.
                self.store.recover();self.consumer.reconcile_completed()
                self.assertEqual(self.store.get(spec['id'])['state'],'archived')
                if deleted:self.assertEqual(self.library.list(),[])
                else:
                    self.assertEqual(self.library.list()[0]['name'],'Renamed after commit')
                    self.assertEqual(self.library.list()[0]['id'],saved_id)
                    self.library.delete(saved_id)

    def test_full_library_keeps_complete_source_then_recovers_without_calculation(self):
        spec,value=self.eager()
        with patch.object(saved,'LIMIT',1):
            occupant=self.library.save('Occupant',value)
            with patch.object(self.store,'completed_source',side_effect=AssertionError('Full admission must not open the source')) as opened:
                self.consumer.reconcile_completed();opened.assert_not_called()
            record=self.store.get(spec['id']);self.assertEqual(record['state'],'complete')
            self.assertEqual(record['transfer']['error'],'full');self.assertEqual(record['snapshot'],value)
            self.assertEqual(self.sql(self.library.path,'SELECT * FROM queue_imports'),[])
            self.library.delete(occupant['id']);self.consumer.reconcile_completed()
            self.assertEqual(self.store.get(spec['id'])['state'],'archived')
            self.assertEqual(self.library.get(self.library.list()[0]['id'])['snapshot'],value)

    def test_full_library_and_existing_receipt_skip_evidence_detachment(self):
        spec,_,_,_=self.evidence()
        with patch.object(saved,'LIMIT',1):
            occupant=self.library.save('Occupant',snapshot('custom'))
            with patch.object(self.store,'completed_source',side_effect=AssertionError('Unavailable admission must not open the source')) as opened, patch.object(queue.durable_evidence,'detach') as detached:
                for _ in range(3):self.consumer.reconcile_completed()
                opened.assert_not_called();detached.assert_not_called()
            pending=self.store.listing()['records'][0]
            self.assertEqual(pending['state'],'complete');self.assertEqual(pending['transfer']['state'],'pending')
            self.assertEqual(pending['transfer']['error'],'full')
            self.library.delete(occupant['id'])
            with patch.object(self.store,'archive_completed',side_effect=OSError('Interrupted archive')):
                self.consumer.reconcile_completed()
            self.store.recover()
            with patch.object(self.store,'completed_source',side_effect=AssertionError('Receipt recovery must not open the source')) as opened, patch.object(queue.durable_evidence,'detach') as detached:
                self.consumer.reconcile_completed()
                opened.assert_not_called();detached.assert_not_called()
            self.assertEqual(self.store.get(spec['id'])['state'],'archived')
            self.assertEqual(len(self.library.list()),1)

    def test_final_admission_rechecks_capacity_after_lazy_source_open(self):
        value=snapshot('custom')
        def open_source():
            self.library.save('Concurrent admission',value)
            return nullcontext(value)
        with patch.object(saved,'LIMIT',1), self.assertRaises(saved.Full):
            self.library.accept_queue_result('c'*32,'Waiting queue result',open_source)
        self.assertEqual(len(self.library.list()),1)
        self.assertEqual(self.sql(self.library.path,'SELECT * FROM queue_imports'),[])

    def test_deletion_wins_before_reservation_and_conflicts_during_copy(self):
        spec,_=self.eager();record=self.store.get(spec['id'])
        self.store.change(spec['id'],'delete',{'revision':record['revision']})
        self.consumer.reconcile_completed();self.assertEqual(self.library.list(),[])
        spec,_=self.eager();self.store.reserve_completed(spec['id'])
        record=self.store.get(spec['id'])
        with self.assertRaisesRegex(queue.Conflict,'moving'):
            self.store.change(spec['id'],'delete',{'revision':record['revision']})
        self.store.recover()
        self.store.change(spec['id'],'delete',{'revision':record['revision']})
        self.consumer.reconcile_completed();self.assertEqual(self.library.list(),[])

    def test_archived_rows_free_capacity_and_keep_exact_submission_receipts(self):
        with patch.object(queue,'LIMIT',1):
            spec,_=self.eager();self.consumer.reconcile_completed()
            self.assertEqual(self.store.enqueue(spec)['state'],'archived')
            other=self.store.enqueue(request('New work'));self.assertEqual(other['state'],'queued')
            with self.assertRaises(queue.Conflict):self.store.enqueue(request('Too many visible'))
            self.assertEqual(len(self.store.listing()['records']),1)

    def test_v3_transfer_keeps_all_bytes_and_active_reader_after_archive(self):
        spec,reader,metadata,original=self.evidence()
        with self.store.open_evidence(spec['id']) as active:
            self.consumer.reconcile_completed()
            archived=self.store.get(spec['id']);saved_id=archived['transfer']['saved_id']
            self.assertEqual(self.sql(self.store.path,'SELECT * FROM evidence_chunks'),[])
            with self.library.open_evidence(saved_id) as saved_source:
                with saved_source.open_reader() as copied,active.open_reader() as opened:
                    self.assertEqual(copied.stream.read(),opened.stream.read())
                    self.assertEqual(saved_source.metadata,metadata)
        self.assertEqual(self.store.finish_evidence(spec['id'],metadata,reader)['state'],'archived')
        changed=deepcopy(metadata);changed['presentation']['different']=True
        with self.assertRaises(queue.Conflict):self.store.finish_evidence(spec['id'],changed,reader)

    def test_paused_unready_consumer_recovers_old_completions_without_financial_access(self):
        spec,_=self.eager();self.store.pause(True)
        self.store.reserve_completed(spec['id'])  # A predecessor died before library publication.
        self.consumer.ready=lambda:False
        with patch.object(queue.Original,'calculate',side_effect=AssertionError('Transfer must not calculate')):
            self.consumer.start();deadline=time.monotonic()+5
            while time.monotonic()<deadline and self.store.get(spec['id'])['state']!='archived':time.sleep(.01)
            self.assertEqual(self.store.get(spec['id'])['state'],'archived')
        self.assertTrue(self.store.listing()['paused']);self.assertEqual(len(self.library.list()),1)


if __name__=='__main__':unittest.main()

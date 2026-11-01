"""Bounded byte protocol and exact private plan references; fictional bytes only."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts')]
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.engines.numerical import transfer as transfer


class TransferTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        self.data=bytes(range(256))*1100

    def copy(self,mutate=lambda e:e,stream=None):
        destination=stream if stream is not None else io.BytesIO()
        receiver=transfer.Receiver(destination,self.root,max_bytes=len(self.data)+1)
        events=[]
        def exchange(event,operation,sequence):
            events.append(deepcopy(event));self.assertEqual(receiver.accept(mutate(event)),(operation,sequence))
        transfer.send(io.BytesIO(self.data),self.root,exchange,max_bytes=len(self.data)+1)
        receiver.finish();return destination,events

    def test_complete_bytes_single_slot_and_strict_completion(self):
        destination,events=self.copy();self.assertEqual(destination.getvalue(),self.data)
        pieces=[e for e in events if e['event']=='transfer_piece']
        self.assertEqual([e['sequence'] for e in pieces],list(range(len(pieces))))
        self.assertLessEqual(max(e['bytes'] for e in pieces),65536)
        self.assertEqual(len(list(self.root.glob('transfer.bin'))),1)
        self.assertEqual(events[-1]['sha256'],hashlib.sha256(self.data).hexdigest())
        receiver=transfer.Receiver(io.BytesIO(),self.root,max_bytes=len(self.data))
        with self.assertRaisesRegex(ValueError,'before completion'):receiver.finish()

    def test_acknowledgements_reject_stale_duplicate_reordered_and_unsolicited(self):
        for value in (dict(command='transfer_ack',operation='other',sequence=0),
                      dict(command='transfer_ack',operation='original',sequence=1),
                      dict(command='transfer_ack',operation='original',sequence=False)):
            ack=transfer.Acknowledgements();ack.arm('original',0)
            self.assertFalse(ack.accept(value))
            with self.assertRaises(ValueError):ack.wait(.001)
        ack=transfer.Acknowledgements();ack.arm('original',0)
        value=dict(command='transfer_ack',operation='original',sequence=0)
        self.assertFalse(ack.wait(.001));self.assertTrue(ack.accept(value));self.assertTrue(ack.wait(.001))
        self.assertFalse(ack.accept(value))
        with self.assertRaises(ValueError):ack.check()
        ack=transfer.Acknowledgements();self.assertFalse(ack.accept(value))
        with self.assertRaises(ValueError):ack.arm('original',0)

    def test_missing_duplicate_reordered_identity_offset_and_corrupt_pieces(self):
        for field,value in [('sequence',1),('sequence',-1),('operation','0'*32),('offset',1),
                            ('bytes',65537),('sha256','0'*64)]:
            with self.subTest(field=field,value=value):
                def mutate(event):
                    if event['event']=='transfer_piece':event[field]=value
                    return event
                with self.assertRaises(ValueError):self.copy(mutate)
        receiver=transfer.Receiver(io.BytesIO(),self.root,max_bytes=len(self.data))
        events=[]
        def duplicate(event,op,seq):
            receiver.accept(event);events.append(event)
            if event['event']=='transfer_piece':receiver.accept(event)
        with self.assertRaisesRegex(ValueError,'sequence'):transfer.send(io.BytesIO(self.data),self.root,duplicate,max_bytes=len(self.data))
        def truncated(event):
            if event['event']=='transfer_piece':(self.root/'transfer.bin').write_bytes(b'x')
            return event
        with self.assertRaisesRegex(ValueError,'content'):self.copy(truncated)
        def missing(event):
            if event['event']=='transfer_piece':(self.root/'transfer.bin').unlink()
            return event
        with self.assertRaises(FileNotFoundError):self.copy(missing)

    def test_forged_completion_missing_end_and_receiver_failure(self):
        for field,value in [('bytes',1),('sequence',0),('sha256','0'*64)]:
            def mutate(event):
                if event['event']=='transfer_end':event[field]=value
                return event
            with self.assertRaises(ValueError):self.copy(mutate)
        class Broken(io.BytesIO):
            def write(self,part):raise LookupError('original receiver failure')
        with self.assertRaisesRegex(LookupError,'original receiver'):self.copy(stream=Broken())
        class Short(io.BytesIO):
            def write(self,part):return 0
        with self.assertRaisesRegex(OSError,'incomplete'):self.copy(stream=Short())

    def test_receiver_checks_actual_saved_content_and_preserves_complete_extensions(self):
        class Altered(io.BytesIO):
            def write(self,part):return super().write(bytes([part[0]^1])+part[1:])
        with self.assertRaisesRegex(ValueError,'content differs'):self.copy(stream=Altered())
        sys.path.insert(0,str(ROOT/'tests'))
        from test_result_evidence import collect,fixture
        from backtest import result_evidence as result_evidence; from backtest import portfolio_results
        pairs,select=fixture();original=portfolio_results.evaluate(pairs,select);original.update(months=1,options={},seconds=.1)
        original['diagnostics']={'unicode':'測試 🐈','null':None,'ordered':[True,1,1.0,-0.0]}
        original['periods'][0]['holdings'][0]['extension']={'original':[None,'a','b']}
        data=io.BytesIO();writer=result_evidence.Writer(data,trials=1,metadata={'original_label':'測試'},max_bytes=1024**2,piece_bytes=31)
        writer.start_trial(1)
        for period in original['periods']:writer.period(period)
        writer.end_trial({k:v for k,v in original.items() if k!='periods'});writer.finish({})
        self.data=data.getvalue();destination,_=self.copy()
        reader=result_evidence.Reader(destination,max_bytes=1024**2,piece_bytes=31)
        self.assertEqual(collect(reader),[original]);self.assertEqual(reader.metadata,{'original_label':'測試'})

    def test_bounded_plan_content_replacement_escape_nonfinite_and_duplicate_keys(self):
        original={'samples':[['2010-01-04']*3000]*30,'extension':None}
        reference=transfer.stage_plan(self.root,original)
        self.assertGreater(reference['bytes'],1024**2)
        self.assertEqual(transfer.read_plan(self.root,reference),original)
        self.assertEqual(transfer.plan_identity(dict(reversed(list(original.items())))),reference['sha256'])
        path=self.root/'recorded-plan.json';raw=path.read_bytes()
        for changed in (raw[:-1],raw+b'x',raw.replace(b'2010',b'2011')):
            path.write_bytes(changed)
            with self.assertRaises(ValueError):transfer.read_plan(self.root,reference)
        path.unlink();path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'replaced'):transfer.read_plan(self.root,reference)
        reference=transfer.stage_plan(self.root,original)
        for extra in ({'path':'../outside'},{'version':2},{'bytes':transfer.MAX_PLAN_BYTES+1}):
            with self.assertRaises(ValueError):transfer.read_plan(self.root,dict(reference,**extra))
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
            path.write_bytes(raw)
            import os
            ref=dict(version=1,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),file_identity=transfer._fingerprint(path.stat()))
            with self.assertRaises(ValueError):transfer.read_plan(self.root,ref)
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaisesRegex(ValueError,'escapes'):transfer.read_plan(self.root,reference)
        with self.assertRaisesRegex(ValueError,'byte bound'):transfer.stage_plan(self.root,{'x':'x'*(transfer.MAX_PLAN_BYTES+1)})
        self.assertFalse((self.root/'recorded-plan.pending').exists())


if __name__=='__main__':unittest.main()

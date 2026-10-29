"""Bounded detached evidence on caller-owned fictional files; no runtime route."""
from copy import deepcopy
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import result_evidence as evidence
import portfolio_results
from test_portfolio_results import holding


LIMIT = 8*1024**2
METADATA = dict(settings=dict(mode='random',rank_from=51,rank_to=100,seed=42),
    catalog=dict(metrics={'old':'Original label 測試'},filters={}),
    presentation=dict(periodLabel='Original weekly label'),missing=None)


def fixture():
    days = [date(2020,1,2),date(2020,2,3),date(2020,3,2),date(2020,4,2)]
    pairs = list(zip(days,days[1:]))
    def select(entry, exit_day):
        rows = []
        if entry != days[1]:
            for rank,ret in ((51,-.2),(52,.4),(53,-0.0)):
                row = holding('F'+str(rank),rank,ret,entry=str(entry),exit=str(exit_day))
                row['extension'] = dict(unicode='測試 🐈',nested=[None,False,0,1.,-0.0],
                    omitted_is_distinct={'present':None},original_diagnostic=1.2345678901234567)
                rows.append(row)
        return dict(entry=str(entry),exit=str(exit_day),holdings=rows,spy=.01)
    return pairs,select


def write(stream, *, trials=2, piece_bytes=127, record_bytes=evidence.MAX_RECORD_BYTES,
          max_bytes=LIMIT, checkpoint=None):
    writer = evidence.Writer(stream,trials=trials,metadata=deepcopy(METADATA),
        piece_bytes=piece_bytes,record_bytes=record_bytes,max_bytes=max_bytes,checkpoint=checkpoint)
    expected = []
    for number in range(1,trials+1):
        pairs,select = fixture()
        writer.start_trial(number)
        summary = portfolio_results.evaluate_into(pairs,select,writer.period,common_start=date(2019,12,30))
        summary.update(options=dict(pool='cached',rank_from=51,rank_to=100),seconds=number/10,
            months=1,diagnostic=dict(original=True,nullable=None))
        writer.end_trial(summary)
        collected = portfolio_results.evaluate(pairs,select,common_start=date(2019,12,30))
        collected.update({key:value for key,value in summary.items() if key not in collected})
        expected.append(collected)
    writer.finish(dict(configuration={'seed':42},completed=trials,seconds=.123))
    return writer,expected


def collect(reader):
    """Test-only eager reconstruction to compare every original field and type."""
    trials=[];periods=None;period=None
    for record in reader.records():
        kind = record['type']
        if kind == 'trial': periods=[]
        elif kind == 'period': period=dict(record['value'],holdings=[])
        elif kind == 'holding': period['holdings'].append(record['value'])
        elif kind == 'end_period': periods.append(period)
        elif kind == 'end_trial': trials.append(dict(periods=periods,**record['summary']))
    return trials


def frames(data):
    result=[];position=0
    while position < len(data):
        size,last = struct.unpack('!IB',data[position:position+5])
        end=position+5+size+32
        result.append((last,data[position+5:position+5+size],data[position:end]))
        position=end
    return result


def repack(records):
    """Build checksum-valid malformed structure independently of Writer."""
    result=bytearray();digest=hashlib.sha256()
    for record in records:
        if record.get('type') == 'complete':
            record=deepcopy(record);record['sha256']=digest.hexdigest()
        data=json.dumps(record,allow_nan=False,separators=(',',':')).encode('utf8')
        if record.get('type') != 'complete': digest.update(hashlib.sha256(data).digest())
        result.extend(struct.pack('!IB',len(data),1));result.extend(data)
        result.extend(hashlib.sha256(b'\x01'+data).digest())
    return bytes(result)


class EvidenceTests(unittest.TestCase):
    def test_complete_round_trip_types_nulls_extensions_order_and_file_lifetime(self):
        with tempfile.TemporaryDirectory(prefix='evidence-fixture-') as directory:
            path=Path(directory)/'owned.evidence'
            with path.open('w+b') as stream:
                writer,expected=write(stream)
                self.assertFalse(stream.closed)
                self.assertFalse(writer.failed)
                self.assertEqual(writer.bytes_written,stream.tell())
                self.assertLessEqual(writer.peak_piece_bytes,127)
            # No financial attachment, generation, database or writer is needed.
            with path.open('rb') as stream:
                reader=evidence.Reader(stream,max_bytes=LIMIT)
                self.assertEqual(reader.metadata,METADATA)
                restored=collect(reader)
                self.assertEqual(restored,expected)
                self.assertEqual(reader.manifest['summary'],dict(configuration={'seed':42},completed=2,seconds=.123))
                self.assertEqual((reader.manifest['trials'],reader.manifest['periods'],reader.manifest['holdings']),(2,6,12))
                self.assertEqual(json.dumps(restored,sort_keys=True),json.dumps(expected,sort_keys=True))
                self.assertFalse(stream.closed)
                # Returned metadata cannot change the reader's verified identity.
                reader.metadata['settings'].clear()
                reader.manifest['summary'].clear()
                self.assertEqual(reader.metadata,METADATA)
                self.assertEqual(collect(reader),expected)

    def test_periods_and_scalars_span_many_pieces_without_whole_period_record(self):
        stream=io.BytesIO()
        writer,expected=write(stream,piece_bytes=31,record_bytes=1536,trials=1)
        reader=evidence.Reader(stream,max_bytes=LIMIT)
        self.assertGreater(len(frames(stream.getvalue())),100)
        self.assertLessEqual(writer.peak_piece_bytes,31)
        self.assertGreater(len(json.dumps(expected[0]['periods'][0]).encode()),writer.record_bytes)
        self.assertLess(writer.peak_record_bytes,len(json.dumps(expected[0]['periods'][0]).encode()))
        self.assertEqual(collect(reader),expected)

    def test_cancellation_and_sink_failure_never_produce_completion(self):
        for failure in (RuntimeError('fictional stop'),OSError('fictional full file')):
            stream=io.BytesIO();calls=0
            def checkpoint():
                nonlocal calls
                calls+=1
                if calls==12:raise failure
            with self.assertRaises(type(failure)) as raised:
                write(stream,checkpoint=checkpoint)
            self.assertIs(raised.exception,failure)
            with self.assertRaisesRegex(ValueError,'before completion'):
                evidence.Reader(stream,max_bytes=LIMIT)

    def test_failed_writer_is_poisoned_and_old_bytes_are_not_replaced(self):
        stream=io.BytesIO();writer=evidence.Writer(stream,trials=1,metadata={},max_bytes=LIMIT)
        with self.assertRaises(ValueError):writer.start_trial(2)
        self.assertTrue(writer.failed)
        for action in (lambda:writer.start_trial(1),lambda:writer.finish({})):
            with self.assertRaisesRegex(ValueError,'failed or complete'):action()
        original=b'preserve old evidence'
        old=io.BytesIO(original)
        with self.assertRaisesRegex(ValueError,'must be empty'):
            evidence.Writer(old,trials=1,metadata={},max_bytes=LIMIT)
        self.assertEqual(old.getvalue(),original)

    def test_writer_and_reader_enforce_byte_limits(self):
        stream=io.BytesIO();writer,expected=write(stream,trials=1)
        data=stream.getvalue()
        with self.assertRaisesRegex(ValueError,'total byte bound'):
            evidence.Reader(io.BytesIO(data),max_bytes=len(data)-1)
        with self.assertRaisesRegex(ValueError,'piece bound'):
            evidence.Reader(io.BytesIO(data),max_bytes=LIMIT,piece_bytes=126)
        with self.assertRaisesRegex(ValueError,'record byte bound'):
            evidence.Reader(io.BytesIO(data),max_bytes=LIMIT,record_bytes=300)
        for kwargs,message in ((dict(max_bytes=128),'total byte bound'),
                (dict(record_bytes=128),'record byte bound')):
            out=io.BytesIO()
            with self.assertRaisesRegex(ValueError,message):write(out,**kwargs)
            self.assertLessEqual(out.tell(),kwargs.get('max_bytes',LIMIT))
            with self.assertRaises(ValueError):evidence.Reader(out,max_bytes=LIMIT)
        for kwargs in (dict(max_bytes=True),dict(piece_bytes=0),dict(record_bytes=evidence.MAX_RECORD_BYTES+1)):
            with self.assertRaisesRegex(ValueError,'Invalid evidence byte limits'):
                evidence.Writer(io.BytesIO(),trials=1,metadata={},**dict({'max_bytes':LIMIT},**kwargs))

    def test_missing_reordered_duplicate_and_trailing_pieces_fail(self):
        stream=io.BytesIO();write(stream,trials=1)
        chunks=[raw for last,data,raw in frames(stream.getvalue())]
        cases=[b''.join(chunks[:-1]),b''.join(chunks[:3]+chunks[4:]),
               b''.join(chunks[:3]+[chunks[4],chunks[3]]+chunks[5:]),
               b''.join(chunks[:3]+[chunks[3]]+chunks[3:]),stream.getvalue()+b'x',
               stream.getvalue()[:-1],b'x',b'']
        for index,data in enumerate(cases):
            with self.subTest(index=index),self.assertRaises(ValueError):
                evidence.Reader(io.BytesIO(data),max_bytes=LIMIT)

    def test_corruption_unknown_versions_and_order_fail_even_with_valid_frame_hashes(self):
        stream=io.BytesIO();write(stream,trials=1)
        reader=evidence.Reader(stream,max_bytes=LIMIT)
        original=list(reader.records())
        mutants=[lambda r:r[0].update(type=[]),lambda r:r[0].update(format_version=2),lambda r:r[0].update(result_contract=2),
            lambda r:r[0].update(trials=True),lambda r:r[1].update(number=2),
            lambda r:r[2].update(number=2),lambda r:r[2]['value'].update(names=4),
            lambda r:r[2]['value'].update(is_final_period=True),
            lambda r:r[-2].update(periods=4),lambda r:r[-1].update(holdings=100),
            lambda r:r[-1].update(records=1),lambda r:r[-2]['summary'].update(end='2020-04-03'),
            lambda r:r[-2]['summary'].update(periods=[]),lambda r:r[3]['value'].pop('return_value')]
        for mutate in mutants:
            records=deepcopy(original);mutate(records)
            with self.subTest(mutation=mutants.index(mutate)),self.assertRaises(ValueError):
                evidence.Reader(io.BytesIO(repack(records)),max_bytes=LIMIT)
        # A checksum mismatch fails before JSON decode.
        bad=bytearray(stream.getvalue());bad[7]^=1
        with self.assertRaisesRegex(ValueError,'checksum'):
            evidence.Reader(io.BytesIO(bad),max_bytes=LIMIT)
        # Per-piece hashes alone cannot bind a removed/reordered whole record.
        records=deepcopy(original);records[3]['value']['name']='changed'
        bad=repack(records)
        final=frames(bad)[-1][2]
        old_final=frames(repack(original))[-1][2]
        with self.assertRaisesRegex(ValueError,'manifest differs'):
            evidence.Reader(io.BytesIO(bad[:-len(final)]+old_final),max_bytes=LIMIT)

    def test_non_json_keys_nonfinite_values_depth_and_duplicate_keys_fail(self):
        for value in ({1:'bad'},{'bad':float('nan')},{'bad':float('inf')},{'bad':(1,2)}, {'bad':set()}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                evidence.Writer(io.BytesIO(),trials=1,metadata=value,max_bytes=LIMIT)
        nested=[];nested.append(nested)
        with self.assertRaisesRegex(ValueError,'nesting bound'):
            evidence.Writer(io.BytesIO(),trials=1,metadata={'bad':nested},max_bytes=LIMIT)
        raw=b'{"type":"header","type":"trial"}'
        data=struct.pack('!IB',len(raw),1)+raw+hashlib.sha256(b'\x01'+raw).digest()
        with self.assertRaisesRegex(ValueError,'Invalid evidence JSON'):
            evidence.Reader(io.BytesIO(data),max_bytes=LIMIT)

    def test_reader_cancellation_and_changed_content_are_detected(self):
        stream=io.BytesIO();write(stream,trials=1)
        stop=Mock(side_effect=RuntimeError('fictional reader stop'))
        with self.assertRaises(RuntimeError):evidence.Reader(stream,max_bytes=LIMIT,checkpoint=stop)
        reader=evidence.Reader(stream,max_bytes=LIMIT)
        records=list(reader.records());records[0]['metadata']['settings']['seed']=43
        stream.seek(0);stream.truncate();stream.write(repack(records))
        with self.assertRaisesRegex(ValueError,'changed after validation'):list(reader.records())

    def test_short_writes_and_incomplete_trial_are_not_publishable(self):
        class Short(io.BytesIO):
            def write(self,value):return super().write(value[:-1])
        with self.assertRaises(OSError):evidence.Writer(Short(),trials=1,metadata={},max_bytes=LIMIT)
        stream=io.BytesIO();writer=evidence.Writer(stream,trials=1,metadata={},max_bytes=LIMIT)
        writer.start_trial(1)
        with self.assertRaisesRegex(ValueError,'manifest differs'):writer.finish({})
        with self.assertRaises(ValueError):evidence.Reader(stream,max_bytes=LIMIT)


if __name__ == '__main__': unittest.main()

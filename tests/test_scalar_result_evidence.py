"""Scalar codec2 completion, detached bounded reads, exports and durable copies."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from contextlib import closing
from copy import deepcopy
from datetime import date
import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from backtest import result_evidence, scalar_result_evidence, portfolio_results
from backtest.application import scalar_execution, scalar_runs, durable_evidence, evidence_views, result_exports, library
from backtest.application import strategy_requests as s
from test_scalar_execution import Fixture


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture(8);self.addCleanup(self.fixture.db.close)
        self.capture=self.fixture.capture()
    def produce(self,mode='custom',**limits):
        stream=io.BytesIO()
        options=dict(strategy=self.capture.to_dict(),start='2015-01-02',end='2015-01-05',months=12)
        if mode=='latest':options=dict(strategy=self.capture.to_dict())
        metadata=dict(mode=mode,options=options,configuration=None)
        writer=scalar_result_evidence.Writer(stream,trials=0 if mode=='latest' else 1,metadata=metadata,max_bytes=16*1024**2,**limits)
        with self.fixture.view() as view:
            summary=scalar_runs.execute(self.fixture.db,self.fixture.db,mode,options,writer,view,None)
        manifest=writer.finish(summary)
        return stream,manifest
    def test_fixed_complete_roundtrip_without_pair_requirement(self):
        stream,manifest=self.produce()
        reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        self.assertEqual(reader.format_version,2)
        self.assertEqual(reader.manifest,manifest)
        holdings=list(evidence_views.holdings(reader,1,1))
        self.assertEqual(len(holdings),5)
        self.assertEqual(sum(h['weight'] for h in holdings),1.)
        self.assertTrue(all('metric_yield' not in h for h in holdings))
        self.assertEqual(evidence_views.trial(reader,1)['summary']['growth'],1+sum(h['return_value'] for h in holdings)/5)
    def test_latest_screen_has_zero_trials_and_no_future_fields(self):
        stream,manifest=self.produce('latest')
        reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        self.assertEqual((manifest['trials'],manifest['periods']),(0,0))
        rows=evidence_views.read(reader,dict(operation='screen'))['rows']
        self.assertEqual(len(rows),5)
        self.assertFalse(any(key in row for row in rows for key in ('return_value','weight','contribution_pp','exit')))
        with self.assertRaises(ValueError):evidence_views.trial(reader,1)
    def test_detached_explanation_pages_cover_complete_blocks(self):
        stream,_=self.produce()
        reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        scopes=evidence_views.read(reader,dict(operation='scopes'))
        blocks=evidence_views.read(reader,dict(operation='explanations'))
        self.assertEqual(scopes['rows'][0]['population'],'complete-prepared-scope')
        self.assertTrue(any('block' in row for row in blocks['rows']))
        encoded=stream.getvalue()
        self.fixture.db.close()
        self.fixture.db=__import__('sqlite3').connect(':memory:')
        with patch.object(s,'builtin_catalog',side_effect=AssertionError('No current catalog')):
            detached=result_evidence.open_reader(io.BytesIO(encoded),max_bytes=16*1024**2)
            self.assertEqual(list(detached.verified_records()),list(reader.verified_records()))
    def test_complete_export_is_original_self_contained_framed_bytes(self):
        stream,_=self.produce();data=stream.getvalue()
        reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        prepared=result_exports.prepare(reader,'evidence')
        self.assertEqual(prepared.content_type,'application/octet-stream')
        self.assertEqual(b''.join(prepared.chunks()),data)
        self.assertEqual(prepared.content_length,len(data))
        exported=result_evidence.open_reader(io.BytesIO(data),max_bytes=16*1024**2)
        self.assertEqual(exported.metadata['options']['strategy'],self.capture.to_dict())
        csv=b''.join(result_exports.prepare(reader,'holdings').chunks()).decode()
        self.assertIn('ranking_value',csv);self.assertIn('scalar_evidence',csv)
        self.assertNotIn('metric_multiple',csv)
    def test_screen_csv_is_complete_and_does_not_add_returns(self):
        stream,_=self.produce('latest');reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        csv=b''.join(result_exports.prepare(reader,'screen').chunks()).decode()
        self.assertEqual(len(csv.splitlines()),6)
        self.assertNotIn('return_value',csv)
        with self.assertRaises(ValueError):result_exports.prepare(reader,'returns')
    def test_durable_artifact4_survives_removal_of_variable_store_and_generation(self):
        stream,_=self.produce();reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        metadata=dict(version=4,kind='custom',settings=dict(mode='custom',**reader.metadata['options']),
            result=reader.manifest['summary'],catalog=dict(metrics={},filters={}),presentation=dict(kind='scalar'))
        with tempfile.TemporaryDirectory() as folder:
            store=library.Store(Path(folder)/'saved.sqlite')
            record=store.save_evidence('Original scalar',metadata,reader)
            with store.open_evidence(record['id']) as opened:
                self.assertEqual(opened.metadata,metadata)
                with opened.open_reader() as other:
                    self.assertEqual(other.format_version,2)
                    self.assertEqual(list(other.verified_records()),list(reader.verified_records()))
            with self.assertRaises(durable_evidence.RequiresReader):store.get(record['id'])
    def test_latest_remains_unsavable(self):
        stream,_=self.produce('latest');reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        metadata=dict(version=4,kind='latest',settings=dict(mode='latest',**reader.metadata['options']),
            result=reader.manifest['summary'],catalog=dict(metrics={},filters={}),presentation={})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'saved.sqlite'
            with self.assertRaises(ValueError):library.Store(path).save_evidence('Latest',metadata,reader)
            self.assertFalse(path.exists())
    def test_artifact_codec_pairs_are_explicit(self):
        stream,_=self.produce();reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        metadata=dict(version=3,kind='custom',settings=dict(mode='custom',**reader.metadata['options']),result=reader.manifest['summary'],catalog=dict(metrics={},filters={}),presentation={})
        with self.assertRaises(ValueError):durable_evidence.validate_metadata(metadata,reader)
        with self.assertRaises(ValueError):result_evidence.Reader(stream,max_bytes=16*1024**2)
    def test_selected_rows_require_complete_scope_and_explanation_references(self):
        stream,_=self.produce();reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        rows=list(evidence_views.holdings(reader,1,1))
        writer=scalar_result_evidence.Writer(io.BytesIO(),trials=1,metadata=reader.metadata,max_bytes=16*1024**2)
        writer.start_trial(1)
        with self.assertRaises(ValueError):
            writer.period(dict(entry='2015-01-02',exit='2015-01-05',holdings=rows,names=len(rows),portfolio=.1,spy=.1,is_final_period=True))

    def test_damage_truncation_and_trailing_bytes_rejected(self):
        stream,_=self.produce();data=stream.getvalue()
        for malformed in (data[:-1],data+b'x',data[:20]+bytes([data[20]^1])+data[21:]):
            with self.assertRaises(ValueError):result_evidence.open_reader(io.BytesIO(malformed),max_bytes=16*1024**2)
    def test_total_and_record_exhaustion_never_publish_manifest(self):
        for max_bytes,record_bytes in [(100,8*1024**2),(16*1024**2,100)]:
            with self.assertRaises(ValueError):
                scalar_result_evidence.Writer(io.BytesIO(),trials=1,metadata=dict(mode='custom',options=dict(strategy=self.capture.to_dict())),max_bytes=max_bytes,record_bytes=record_bytes)
    def test_independent_reopened_positions_and_release_of_stream(self):
        stream,_=self.produce();reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        other=reader.reopen(io.BytesIO(stream.getvalue()))
        self.assertIsInstance(other,scalar_result_evidence.Reader)
        first=reader.verified_records();second=other.verified_records()
        self.assertEqual(next(first),next(second));self.assertEqual(next(first),next(second))
    def test_scalar_contract_reuses_exact_original_reduction(self):
        stream,_=self.produce();reader=result_evidence.open_reader(stream,max_bytes=16*1024**2)
        holdings=list(evidence_views.holdings(reader,1,1))
        def book(a,b):return dict(entry=str(a),exit=str(b),spy=.1,holdings=holdings)
        generic=portfolio_results.evaluate([(date(2015,1,2),date(2015,1,5))],book,contract=2)
        for h in holdings:h.update(metric_yield=.3,metric_multiple=3.)
        original=portfolio_results.evaluate([(date(2015,1,2),date(2015,1,5))],book)
        for key in ('growth','cagr','spy_growth','spy_cagr'):self.assertEqual(generic[key],original[key])


if __name__=='__main__':unittest.main()

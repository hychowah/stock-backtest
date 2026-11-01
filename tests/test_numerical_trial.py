"""Complete recorded-trial and artifact checks on private fictional inputs."""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from copy import deepcopy
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests'),str(ROOT/'tools')]
import backtest_control
from backtest import calendar_requests as numerical_calendar
import numerical_random
import numerical_trial
from backtest import portfolio_results as portfolio_results
import result_evidence
import trial_checkpoints
import test_bounded_trials as bounded
import test_numerical_trials as trials
import test_result_evidence as codec
import test_trial_checkpoints as fixtures
from numerical_portfolio import compare_results

LIMITS=dict(max_bytes=32*1024**2,piece_bytes=127,record_bytes=16384)


def writer_view(stream,result,number=37,limits=None):
    writer=result_evidence.SingleTrialWriter(stream,number=number,**(limits or LIMITS))
    for period in result['periods']:writer.period(period)
    return writer,writer.finish({k:v for k,v in result.items() if k!='periods'})


class SingleTrialCodecTests(unittest.TestCase):
    def test_actual_number_37_bounds_extensions_and_unchanged_batch_order(self):
        result=fixtures.completed();result['extension']={'測試':[None,-0.0,True]}
        stream=io.BytesIO();writer,view=writer_view(stream,result)
        self.assertEqual(view.number,37);self.assertEqual(view.start,0)
        self.assertEqual(dict(periods=list(view.periods()),**view.summary),result)
        self.assertEqual(writer.bytes_written,len(stream.getvalue()))
        self.assertLessEqual(writer.peak_piece_bytes,LIMITS['piece_bytes'])
        self.assertLessEqual(writer.peak_record_bytes,LIMITS['record_bytes'])
        self.assertGreater(len(json.dumps(result['periods'][0])),LIMITS['piece_bytes'])
        with self.assertRaises(ValueError):writer.finish(view.summary)
        with self.assertRaises(ValueError):writer.period(result['periods'][0])
        output=result_evidence.Writer(io.BytesIO(),trials=1,metadata={},max_bytes=10000)
        with self.assertRaisesRegex(ValueError,'contiguous'):output.start_trial(37)
        self.assertTrue(output.failed)
        for limits in (dict(LIMITS,max_bytes=64),dict(LIMITS,record_bytes=200)):
            with self.assertRaises(ValueError):writer_view(io.BytesIO(),result,limits=limits)
        for field in ('piece_bytes','record_bytes'):
            with self.assertRaises(ValueError):
                result_evidence.TrialView(stream,start=0,end=view.end,sha256=view.sha256,number=37,
                    **{field:1})

    def test_incomplete_failed_and_later_writes_cannot_change_sealed_view(self):
        first=io.BytesIO();writer,view=writer_view(first,fixtures.completed())
        original=list(view.periods())
        writer_view(io.BytesIO(),fixtures.completed(),38)
        self.assertEqual(list(view.periods()),original)
        for raw in (first.getvalue()[:-1],first.getvalue()[:30]+b'x'+first.getvalue()[31:]):
            with self.assertRaises(ValueError):
                result_evidence.TrialView(io.BytesIO(raw),start=0,end=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),number=37,
                    piece_bytes=LIMITS['piece_bytes'],record_bytes=LIMITS['record_bytes'])
        stream=io.BytesIO();output=result_evidence.SingleTrialWriter(stream,number=37,**LIMITS)
        with self.assertRaises(ValueError):output.finish({})
        self.assertTrue(output.failed)
        with self.assertRaises(ValueError):output.period(fixtures.completed()['periods'][0])

    def test_large_complete_period_has_bounded_records_and_measured_bytes(self):
        pairs=[(date(2015,1,2),date(2016,1,4))]
        rows=[codec.holding('F'+str(n),n,.01,entry='2015-01-02',exit='2016-01-04',
            extension={'unicode':'測試 🐈','original':[None,-0.0,False]}) for n in range(1,1001)]
        result=portfolio_results.evaluate(pairs,lambda a,b:dict(entry=str(a),exit=str(b),holdings=rows,spy=.2),
            common_start=date(2015,1,1))
        result.update(months=12,options={},seconds=.1,extension={'original':'kept'})
        stream=io.BytesIO();writer,view=writer_view(stream,result)
        self.assertEqual(dict(periods=list(view.periods()),**view.summary),result)
        self.assertGreater(len(json.dumps(result['periods'][0])),LIMITS['record_bytes'])
        self.assertLessEqual(writer.peak_piece_bytes,LIMITS['piece_bytes'])
        self.assertLessEqual(writer.peak_record_bytes,LIMITS['record_bytes'])
        print(json.dumps(dict(check='single-trial-artifact-bytes',holdings=1000,
            encoded_bytes=writer.bytes_written,peak_piece_bytes=writer.peak_piece_bytes,
            peak_record_bytes=writer.peak_record_bytes,limits=LIMITS,
            scope='encoded evidence; current complete period remains in memory; no process-memory claim')),flush=True)


class TrialEvaluatorTests(unittest.TestCase):
    setUp=trials.NumericalTrialsTests.setUp
    evaluator=trials.NumericalTrialsTests.evaluator

    def config(self,portfolio,*,unit='week',trials=1,**options):
        return numerical_calendar.plan(portfolio._calendar().sessions,dict(calendar=dict(version=1,
            start='2015-01-05',end='2015-02-27',interval=dict(unit=unit,count=1)),trials=trials,
            seed=42,min_cap=0.,min_ev=0.,rank_to=3,**options))

    def operation(self,portfolio,config,number=1):
        binding=numerical_random.checkpoint_binding(portfolio,config)
        return binding,numerical_trial.specification(binding,number),numerical_trial.TrialEvaluator(
            portfolio,calculation_identity=numerical_trial.calculation_identity(binding))

    def artifact(self,operation,spec,stream=None,limits=None):
        stream=stream if stream is not None else io.BytesIO();limits=limits or LIMITS
        descriptor=operation.produce(spec,stream,limits=limits)
        opened=numerical_trial.open_artifact(stream,descriptor,expected_spec=spec,limits=limits,
            checkpoint=backtest_control.checkpoint)
        return descriptor,opened,stream

    def test_original_eager_incremental_artifact_complete_settings_matrix(self):
        inputs,provider,portfolio,store=self.evaluator('source')
        cases=0;maximum_absolute=maximum_relative=0.;statuses=set();empty=0
        conditions=[[]]+[[dict(field=field,op='gt',value=-1e20)] for field in sorted(portfolio.s.metrics.FILTERS)]
        # Cross every supported field with both pools/orders/metrics/calendars.
        for pool in ('legacy','cached'):
            for order in ('filter_first','rank_first'):
                for metric in portfolio.s.metrics.METRICS:
                    for unit in ('week','month'):
                        config=self.config(portfolio,unit=unit,pool=pool,selection_order=order,metric=metric)
                        for filters in conditions:
                            config['options']['filters']=filters
                            binding,spec,operation=self.operation(portfolio,config)
                            request=dict(**spec['request'],**spec['options'])
                            reference=portfolio.s.backtest_calendar(self.db,**request)
                            eager=portfolio.backtest_calendar(**request)['result']
                            periods=[];summary=operation.evaluate_into(spec,periods.append)
                            incremental=dict(periods=periods,**summary)
                            with patch.object(portfolio,'backtest_calendar',side_effect=AssertionError('No eager producer')), \
                                 patch.object(portfolio_results,'evaluate',side_effect=AssertionError('No collecting reducer')):
                                descriptor,artifact,stream=self.artifact(operation,spec)
                            replay=[];artifact.copy_into(replay.append)
                            for actual in (eager,incremental,dict(periods=replay,**artifact.summary)):
                                agreement=compare_results(reference,actual)
                                self.assertTrue(agreement['exact'],(pool,order,metric,unit,filters,agreement))
                                maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                                maximum_relative=max(maximum_relative,agreement['maximum_relative'])
                            statuses.update(h['status'] for p in replay for h in p['holdings'])
                            empty+=sum(p['names']==0 for p in replay);cases+=1
        self.assertGreater(empty,0)
        # Retain an explicit year-end stopped-price case, beyond this short matrix.
        config=bounded.robustness.plan(self.db,start='2015-01-05',end='2016-12-30',trials=1,seed=42,
                                      rank_to=50,min_cap=0.,min_ev=0.)
        _,spec,operation=self.operation(portfolio,config)
        _,artifact,_=self.artifact(operation,spec)
        periods=list(artifact.periods())
        reference=portfolio.s.backtest_dates(self.db,**spec['request'],**spec['options'])
        self.assertTrue(compare_results(reference,dict(periods=periods,**artifact.summary))['exact'])
        statuses.update(h['status'] for p in periods for h in p['holdings'])
        self.assertIn('Last available price',statuses)
        print(json.dumps(dict(check='recorded-trial-settings',cases=cases,fields=len(conditions)-1,
            maximum_absolute=maximum_absolute,maximum_relative=maximum_relative,tolerance=1e-12,
            empty_periods=empty,statuses=sorted(statuses))),flush=True)

    def test_actual_trial_37_duplicate_identity_checkpoint_replay_and_native_file_release(self):
        inputs,provider,portfolio,store=self.evaluator('source')
        config=self.config(portfolio,trials=37);config['samples']=[config['samples'][0][:] for _ in range(37)]
        binding,spec,operation=self.operation(portfolio,config,37)
        other=numerical_trial.specification(binding,1)
        self.assertNotEqual(spec['sha256'],other['sha256'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'trial.evidence'
            with path.open('w+b') as stream:
                descriptor,artifact,_=self.artifact(operation,spec,stream)
                self.assertEqual(artifact.view.number,37)
                experiment=store.open(binding)
                self.assertTrue(experiment.save_from(37,artifact.view)['retained'])
                periods=[];summary=experiment.replay_into(37,periods.append)
                self.assertEqual(dict(periods=periods,**summary),experiment.load(37))
                self.assertIsNone(experiment.load(1))
                before=list(artifact.periods())
                self.artifact(operation,other)
                self.assertEqual(list(artifact.periods()),before)
                self.assertFalse(stream.closed)
            renamed=path.with_suffix('.closed');path.rename(renamed);renamed.unlink()
        self.assertFalse(portfolio.db.in_transaction)
        self.assertIn('scripts/numerical_trial.py',numerical_random.source_identity())
        self.assertIn('scripts/result_evidence.py',numerical_random.source_identity())

    def test_specification_task_swaps_and_validation_before_provider(self):
        inputs,provider,portfolio,store=self.evaluator('source')
        config=self.config(portfolio,trials=2);binding,spec,operation=self.operation(portfolio,config)
        descriptor,artifact,stream=self.artifact(operation,spec)
        with self.assertRaises(ValueError):numerical_trial.open_artifact(stream,descriptor,
            expected_spec=numerical_trial.specification(binding,2),limits=LIMITS,checkpoint=None)
        variants=[]
        for key,value in (('number',2),('calculation_identity','0'*64),('sha256','0'*64),
                          ('window_end','2015-02-26'),('extra',True)):
            changed=deepcopy(spec);changed[key]=value;variants.append(changed)
        for key,value in (('dates',['2015-01-03']),('calendar',dict(spec['request']['calendar'],end='2015-02-26'))):
            changed=deepcopy(spec);changed['request'][key]=value;variants.append(changed)
        changed=deepcopy(spec);changed['options']['rank_to']=1;variants.append(changed)
        with patch.object(provider,'begin',side_effect=AssertionError('Validate before provider')):
            for changed in variants:
                with self.assertRaises(ValueError):operation.evaluate_into(changed,lambda p:None)
                with self.assertRaises(ValueError):numerical_trial.open_artifact(stream,descriptor,
                    expected_spec=changed,limits=LIMITS,checkpoint=None)
            changed=deepcopy(spec);changed['options']['unknown']=True
            changed['sha256']=trial_checkpoints.digest(trial_checkpoints.canonical({k:v for k,v in changed.items() if k!='sha256'}))
            with self.assertRaisesRegex(ValueError,'screening'):operation.evaluate_into(changed,lambda p:None)
            other=numerical_trial.TrialEvaluator(portfolio,calculation_identity='0'*64)
            with self.assertRaisesRegex(ValueError,'identity'):other.evaluate_into(spec,lambda p:None)
            with self.assertRaisesRegex(ValueError,'sink'):operation.evaluate_into(spec,None)
        detached=numerical_trial.specification(binding,1);detached['request']['dates'].clear()
        self.assertEqual(binding['configuration']['samples'],config['samples'])

    def test_artifact_keeps_original_period_holding_and_summary_extensions(self):
        inputs,provider,portfolio,store=self.evaluator('source')
        _,spec,operation=self.operation(portfolio,self.config(portfolio))
        original=portfolio.backtest_calendar_into
        extension={'unicode':'測試 🐈','numbers':[-0.0,1.,True],'null':None}
        def producer(emit,**request):
            def decorated(period):
                period['extension']=deepcopy(extension)
                for holding in period['holdings']:holding['extension']=deepcopy(extension)
                emit(period)
            envelope=original(decorated,**request)
            envelope['result']['extension']=deepcopy(extension)
            return envelope
        with patch.object(portfolio,'backtest_calendar_into',side_effect=producer):
            descriptor,artifact,stream=self.artifact(operation,spec)
        periods=list(artifact.periods());self.assertEqual(artifact.summary['extension'],extension)
        self.assertTrue(periods and any(p['holdings'] for p in periods))
        for period in periods:
            self.assertEqual(period['extension'],extension)
            for holding in period['holdings']:self.assertEqual(holding['extension'],extension)
        raw=stream.getvalue();stream.seek(len(raw)//2);stream.write(b'x')
        with self.assertRaises(ValueError):list(artifact.periods())

    def test_artifact_tampering_limits_forged_finances_incomplete_and_trailing_bytes(self):
        inputs,provider,portfolio,store=self.evaluator('source')
        _,spec,operation=self.operation(portfolio,self.config(portfolio))
        descriptor,artifact,stream=self.artifact(operation,spec);raw=stream.getvalue()
        for changed in (raw[:-1],raw+b'x',raw[:50]+bytes([raw[50]^1])+raw[51:]):
            with self.assertRaises(ValueError):numerical_trial.open_artifact(io.BytesIO(changed),descriptor,
                expected_spec=spec,limits=LIMITS,checkpoint=None)
        for key,value in (('number',2),('specification','0'*64),('calculation_identity','0'*64),
                          ('sha256','0'*64),('start',1),('end',len(raw)-1),('limits',dict(LIMITS,max_bytes=1))):
            changed=dict(descriptor);changed[key]=value
            with self.assertRaises(ValueError):numerical_trial.open_artifact(stream,changed,
                expected_spec=spec,limits=LIMITS,checkpoint=None)
        for key,value in (('max_bytes',1),('piece_bytes',1),('record_bytes',1)):
            limits=dict(LIMITS,**{key:value});changed=dict(descriptor,limits=limits)
            with self.assertRaises(ValueError):numerical_trial.open_artifact(stream,changed,
                expected_spec=spec,limits=limits,checkpoint=None)
        periods=list(artifact.periods());summary=artifact.summary
        for field,value in (('growth',12.),('spy_growth',12.),('options',{})):
            changed=dict(summary,**{field:value});output=io.BytesIO()
            _,view=writer_view(output,dict(periods=periods,**changed),number=1)
            forged=dict(descriptor,start=view.start,end=view.end,sha256=view.sha256)
            with self.assertRaises(ValueError):numerical_trial.open_artifact(output,forged,
                expected_spec=spec,limits=LIMITS,checkpoint=None)
        records=list(artifact.view.records());records[-1]['summary']['end']='2015-02-26'
        raw=codec.repack(records);forged=dict(descriptor,end=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ValueError):numerical_trial.open_artifact(io.BytesIO(raw),forged,
            expected_spec=spec,limits=LIMITS,checkpoint=None)
        raw=codec.repack(list(artifact.view.records())[:-1]);forged=dict(descriptor,end=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ValueError):numerical_trial.open_artifact(io.BytesIO(raw),forged,
            expected_spec=spec,limits=LIMITS,checkpoint=None)

    def test_cancellation_sink_provider_write_failure_and_eager_budget(self):
        inputs,provider,portfolio,store=self.evaluator('source')
        config=self.config(portfolio);binding,spec,operation=self.operation(portfolio,config)
        experiment=store.open(binding)
        for target,name,error in ((provider,'evaluate',RuntimeError('fictional provider')),
                                  (backtest_control,'checkpoint',backtest_control.Cancelled())):
            with patch.object(target,name,side_effect=error):
                with self.assertRaises(type(error)):operation.produce(spec,io.BytesIO(),limits=LIMITS)
            self.assertFalse(portfolio.db.in_transaction)
        with self.assertRaisesRegex(OSError,'sink'):
            operation.evaluate_into(spec,lambda p:(_ for _ in ()).throw(OSError('fictional sink')))
        self.assertFalse(portfolio.db.in_transaction)
        class BrokenStream(io.BytesIO):
            def write(self,data):raise OSError('fictional write')
        with self.assertRaisesRegex(OSError,'write'):operation.produce(spec,BrokenStream(),limits=LIMITS)
        class CancelledStream(io.BytesIO):
            calls=0
            def write(self,data):
                self.calls+=1
                if self.calls>20:raise backtest_control.Cancelled()
                return super().write(data)
        stream=CancelledStream()
        with self.assertRaises(backtest_control.Cancelled):operation.produce(spec,stream,limits=LIMITS)
        self.assertGreater(len(stream.getvalue()),0);self.assertFalse(portfolio.db.in_transaction)
        for limits in (dict(LIMITS,max_bytes=64),dict(LIMITS,record_bytes=200)):
            with self.assertRaises(ValueError):operation.produce(spec,io.BytesIO(),limits=limits)
        portfolio.result_workspace_bytes=50000
        with patch.object(provider,'begin',side_effect=AssertionError('Admission before provider')):
            with self.assertRaisesRegex(ValueError,'workspace'):numerical_random.run(portfolio,config,experiment)
        # A streaming trial keeps its existing one-period accounting.
        self.artifact(operation,spec)
        portfolio.result_workspace_bytes=10**7
        original_collector=portfolio.result_collector
        def after_admission(*args):
            result=original_collector(*args);portfolio.result_workspace_bytes=1;return result
        with patch.object(portfolio,'result_collector',side_effect=after_admission):
            with self.assertRaisesRegex(ValueError,'workspace'):numerical_random.run(portfolio,config,experiment)
        # Parent completion commits before eager output; failed collection preserves it.
        self.assertIsNotNone(experiment.load(1));self.assertFalse(portfolio.db.in_transaction)


if __name__=='__main__':unittest.main()

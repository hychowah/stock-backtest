"""Bounded production/replay on owned fictional inputs; no application routing."""
from copy import deepcopy
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests'),str(ROOT/'tools')]
import backtest_control
import numerical_calendar
import numerical_random
import portfolio_results
import result_evidence
import trial_checkpoints
import robustness
import test_numerical_trials as trials
import test_result_evidence as codec
import test_trial_checkpoints as fixtures
from numerical_portfolio import compare_results

LIMIT=32*1024**2


def writer(stream,trials=1,**kwargs):
    return result_evidence.Writer(stream,trials=trials,metadata={'original':None},max_bytes=LIMIT,**kwargs)


def seal(stream,result,number=1,trials=1):
    output=writer(stream,trials)
    for n in range(1,number+1):
        output.start_trial(n)
        for period in result['periods']:output.period(period)
        view=output.end_trial({k:v for k,v in result.items() if k!='periods'})
    return output,view


def collected(stream):
    return codec.collect(result_evidence.Reader(stream,max_bytes=LIMIT))


class EvidenceViewTests(unittest.TestCase):
    def test_writer_remains_usable_with_write_only_binary_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'write-only.evidence'
            with path.open('wb') as stream:
                output,view=seal(stream,fixtures.completed())
                self.assertEqual(view.summary['seconds'],.1)
                output.finish({})
            with path.open('rb') as stream:self.assertEqual(collected(stream),[fixtures.completed()])

    def test_trial_is_sealed_before_batch_append_and_preserves_all_extensions(self):
        stream=io.BytesIO();output=writer(stream,2,piece_bytes=31,record_bytes=1536)
        expected=[]
        for n in (1,2):
            pairs,select=codec.fixture();output.start_trial(n)
            summary=portfolio_results.evaluate_into(pairs,select,output.period,common_start=date(2019,12,30))
            summary.update(months=1,options={},seconds=.123,diagnostic={'測試':[None,-0.0,True]})
            view=output.end_trial(summary)
            self.assertEqual(view.summary,summary)
            self.assertEqual(view.number,n)
            periods=list(view.periods());expected.append(dict(periods=periods,**summary))
            self.assertGreater(sum(len(json.dumps(p)) for p in periods),1536)
            if n==1:first=view
        self.assertEqual(list(first.periods()),expected[0]['periods'])
        output.finish({});self.assertEqual(collected(stream),expected)
        reader=result_evidence.Reader(stream,max_bytes=LIMIT)
        self.assertEqual([v.number for v in reader.trials()],[1,2])
        stream.seek(first.start+7);stream.write(b'X')
        with self.assertRaisesRegex(ValueError,'changed'):list(first.periods())

    def test_financial_validator_rejects_forged_complete_evidence(self):
        result=fixtures.completed();summary={k:v for k,v in result.items() if k!='periods'}
        pairs=[(date(2015,1,2),date(2016,1,4))]
        for mutate in (lambda s,p:s.update(spy_growth=2.),lambda s,p:p[0].update(portfolio=0.),
                       lambda s,p:p[0].update(names=True),lambda s,p:s.update(cash_days=True)):
            changed=deepcopy(summary);periods=deepcopy(result['periods']);mutate(changed,periods)
            with self.assertRaises(ValueError):portfolio_results.validate_completed_into(changed,iter(periods),pairs)
        for extra in (None,result['periods'][0]):
            with self.assertRaises(ValueError):portfolio_results.validate_completed_into(summary,iter(result['periods']+[extra]),pairs)


class StreamCheckpointTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'checkpoints.sqlite'
        self.store=trial_checkpoints.Store(self.path);self.addCleanup(self.store.close)
        self.exp=self.store.open(fixtures.binding())

    def view(self,result=None,number=1):
        stream=io.BytesIO();return seal(stream,result or fixtures.completed(),number,2)[1]

    def test_v1_upgrade_byte_preservation_bounded_replay_and_cross_format_idempotence(self):
        result=fixtures.completed();result['diagnostic']={'測試':'escaped \\" quote','number':-0.0,'nested':[None,False]}
        self.exp.save(1,result)
        before=self.store.db.execute('SELECT * FROM trials').fetchall()
        self.store.db.execute('PRAGMA user_version=1');self.store.close()
        self.store=trial_checkpoints.Store(self.path);self.addCleanup(self.store.close);self.exp=self.store.open(fixtures.binding())
        self.assertEqual(self.store.db.execute('SELECT * FROM trials').fetchall(),before)
        self.assertEqual(self.store.db.execute('PRAGMA user_version').fetchone()[0],2)
        with patch.object(self.exp,'load',side_effect=AssertionError('No eager load')):
            periods=[];summary=self.exp.replay_into(1,periods.append)
            self.assertEqual(dict(periods=periods,**summary),result)
            retry=deepcopy(result);retry['seconds']=12.
            self.assertTrue(self.exp.save_from(1,self.view(retry))['retained'])
            self.assertTrue(self.exp.save_from(2,self.view(result,2))['retained'])
        self.assertEqual(self.store.db.execute('SELECT typeof(payload) FROM trials ORDER BY number').fetchall(),[('text',),('blob',)])
        self.assertEqual(self.exp.load(2),result)
        self.exp.save(2,retry)
        self.assertEqual(self.exp.load(2)['seconds'],result['seconds'])
        bad=deepcopy(result);bad['diagnostic']['number']=0
        with self.assertRaisesRegex(ValueError,'Conflicting'):self.exp.save_from(1,self.view(bad))
        self.assertEqual(self.exp.load(1),result)

    def test_legacy_canonical_Unicode_large_period_and_invalid_spellings(self):
        result=fixtures.completed();period=result['periods'][0]
        rows=[codec.holding('F'+str(n),n,.01,entry=period['entry'],exit=period['exit'],
                extension={'unicode':'測試 🐈','null':None,'fragmented':'\\ \" 測試 '*10000 if n==1 else '',
                           'numbers':[-0.0,1e-9,-1e12,True]}) for n in range(1,80)]
        result=portfolio_results.evaluate([(date(2015,1,2),date(2016,1,4))],
            lambda a,b:dict(entry=str(a),exit=str(b),holdings=rows,spy=.2),common_start=date(2015,1,1))
        result.update(options={},seconds=.1,months=12)
        self.exp.save(1,result)
        with patch.object(self.exp,'load',side_effect=AssertionError('No eager legacy read')):
            periods=[];summary=self.exp.replay_into(1,periods.append)
        self.assertEqual(dict(periods=periods,**summary),result)
        for payload in (json.dumps(result),trial_checkpoints.canonical(result)+' ',
                        trial_checkpoints.canonical(result).replace('"cash_days":1','"cash_days":1,"cash_days":1')):
            self.store.db.execute('UPDATE trials SET payload=?,sha256=?,bytes=?',
                (payload,trial_checkpoints.digest(payload),len(payload.encode())))
            with self.assertRaises(ValueError):self.exp.replay_into(1,lambda p:None)

    def test_corrupt_missing_truncated_reordered_and_binding_mismatch_fail_closed(self):
        self.exp.save_from(1,self.view())
        row=self.store.db.execute('SELECT payload,sha256,bytes FROM trials').fetchone();raw=row[0]
        for changed in (raw[:-1],raw+b'x',raw[:20]+bytes([raw[20]^1])+raw[21:]):
            self.store.db.execute('UPDATE trials SET payload=?,sha256=?,bytes=?',
                (changed,hashlib.sha256(changed).hexdigest(),len(changed)))
            with self.assertRaises(ValueError):self.exp.replay_into(1,lambda p:None)
        self.store.db.execute('UPDATE trials SET payload=?,sha256=?,bytes=?',row)
        self.assertIsNone(self.exp.replay_into(2,lambda p:None))
        for field,value in [('generation','different'),('implementation',{'source':'changed'}),
                            ('configuration',dict(fixtures.binding()['configuration'],seed=43))]:
            self.assertIsNone(self.store.open(fixtures.binding(**{field:value})).replay_into(1,lambda p:None))
        with self.assertRaisesRegex(ValueError,'number'):self.exp.save_from(1,self.view(number=2))
        changed=fixtures.completed();changed['options']={'rank_to':3}
        with self.assertRaisesRegex(ValueError,'plan'):self.exp.save_from(1,self.view(changed))
        changed=fixtures.completed();changed['growth']=1.
        with self.assertRaises(ValueError):self.exp.save_from(1,self.view(changed))

    def test_reordered_sealed_records_and_cancelled_eviction_keep_existing_work(self):
        view=self.view();records=list(view.records());records[1],records[2]=records[2],records[1]
        raw=codec.repack(records)
        with self.assertRaises(ValueError):
            result_evidence.TrialView(io.BytesIO(raw),start=0,end=len(raw),sha256=hashlib.sha256(raw).hexdigest(),number=1)
        self.exp.save_from(1,self.view())
        self.store.max_experiments=1
        other=self.store.open(fixtures.binding(generation='replacement'))
        def cancel_eviction():
            if self.store.db.in_transaction and self.store.db.execute(
                    'SELECT 1 FROM experiments WHERE identity=?',(self.exp.identity,)).fetchone() is None:
                raise backtest_control.Cancelled()
        with patch.object(backtest_control,'checkpoint',side_effect=cancel_eviction):
            with self.assertRaises(backtest_control.Cancelled):other.save_from(1,self.view())
        self.assertEqual(self.exp.load(1),fixtures.completed());self.assertIsNone(other.load(1))
        self.assertTrue(other.save_from(1,self.view())['retained']);self.assertIsNone(self.exp.load(1))

    def test_cancel_during_copy_atomic_visibility_retention_and_closure(self):
        reader=sqlite3.connect(self.path);self.addCleanup(reader.close)
        view=self.view();observed=[]
        def stop():
            pending=self.store.db.execute("SELECT COUNT(*) FROM trials WHERE sha256='pending'").fetchone()[0]
            if pending:
                self.assertEqual(reader.execute('SELECT COUNT(*) FROM trials').fetchone()[0],0)
                observed.append(True);raise backtest_control.Cancelled()
        with patch.object(backtest_control,'checkpoint',side_effect=stop):
            with self.assertRaises(backtest_control.Cancelled):self.exp.save_from(1,view)
        self.assertTrue(observed);self.assertFalse(self.store.db.in_transaction)
        self.assertIsNone(self.exp.load(1));self.exp.save_from(1,view)
        self.store.max_payload_bytes=self.store.measurements()['payload_bytes']
        self.assertFalse(self.exp.save_from(2,self.view(number=2))['retained'])
        self.assertIsNone(self.exp.load(2));self.assertEqual(self.exp.load(1),fixtures.completed())
        self.store.close();self.assertTrue(self.store.closed)
        with trial_checkpoints.Store(self.path) as reopened:
            self.assertEqual(reopened.open(fixtures.binding()).load(1),fixtures.completed())

    def test_process_exit_before_during_after_stream_commit(self):
        code='''import sys,os,json,io
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'scripts'),str(root/'tests'),str(root/'website')]
import runtime_access
with runtime_access.ownership(root):
 import trial_checkpoints as t
 import result_evidence as e
 path=Path(sys.argv[2]);stage=sys.argv[3];store=t.Store(path)
 exp=store.open(json.loads(sys.argv[4]));result=json.loads(sys.argv[5]);stream=io.BytesIO()
 writer=e.Writer(stream,trials=1,metadata={},max_bytes=1048576);writer.start_trial(1)
 for p in result.pop('periods'):writer.period(p)
 view=writer.end_trial(result)
 def stop():
  pending=store.db.execute("SELECT COUNT(*) FROM trials WHERE sha256='pending'").fetchone()[0]
  if (stage=='before' and not store.db.in_transaction) or (stage=='during' and pending):
   Path(str(path)+'.status').write_text(json.dumps(store.measurements()));os._exit(73)
 t.backtest_control.checkpoint=stop
 exp.save_from(1,view)
 Path(str(path)+'.status').write_text(json.dumps(store.measurements()));os._exit(73)
'''
        observations=[]
        for stage in ('before','during','after'):
            path=self.path.parent/(stage+'.sqlite')
            proc=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT),str(path),stage,
                json.dumps(fixtures.binding()),json.dumps(fixtures.completed())],capture_output=True,timeout=30)
            self.assertEqual(proc.returncode,73,proc.stderr.decode(errors='replace'))
            measured=json.loads(Path(str(path)+'.status').read_text());observations.append(dict(stage=stage,**measured))
            with trial_checkpoints.Store(path) as store:
                self.assertEqual(store.open(fixtures.binding()).load(1),fixtures.completed() if stage=='after' else None)
            if stage=='during':self.assertGreater(measured['journal_bytes'],0)
        print(json.dumps(dict(check='bounded-process-interruption',observations=observations)),flush=True)


class BoundedNumericalTests(unittest.TestCase):
    setUp=trials.NumericalTrialsTests.setUp
    evaluator=trials.NumericalTrialsTests.evaluator

    def config(self,portfolio,**options):
        return numerical_calendar.plan(portfolio._calendar().sessions,dict(calendar=dict(version=1,
            start='2015-01-02',end='2015-02-27',interval=dict(unit='week',count=1)),trials=3,seed=42,
            min_cap=0.,min_ev=0.,**options))

    def run_stream(self,portfolio,config,experiment,progress=None):
        stream=io.BytesIO();output=writer(stream,config['requested'])
        envelope=numerical_random.run_into(portfolio,config,experiment,output,progress)
        return envelope,stream

    def test_complete_eager_streamed_fresh_recovery_matrix_no_collecting_calls(self):
        inputs,provider,portfolio,store=self.evaluator('source');cases=0;maximum_absolute=maximum_relative=0.
        for pool in ('legacy','cached'):
            for ranks in ((1,3),(51,100)):
                for filters in ([],[dict(field='pe',op='lt',value=20.)]):
                    config=self.config(portfolio,pool=pool,rank_from=ranks[0],rank_to=ranks[1],filters=filters)
                    experiment=store.open(numerical_random.checkpoint_binding(portfolio,config))
                    expected=[]
                    eager=numerical_random.run(portfolio,config,experiment,capture=lambda n,r:expected.append(r))['result']
                    store.db.execute('DELETE FROM experiments')
                    with patch.object(experiment,'load',side_effect=AssertionError('No eager checkpoint load')), \
                         patch.object(portfolio,'backtest_calendar',side_effect=AssertionError('No eager producer')), \
                         patch.object(portfolio_results,'evaluate',side_effect=AssertionError('No collecting reducer')):
                        actual,stream=self.run_stream(portfolio,config,experiment)
                    self.assertEqual(actual['result']['distributions'],eager['distributions'])
                    self.assertEqual(actual['result']['execution']['calculated_trials'],3)
                    for left,right in zip(expected,collected(stream),strict=True):
                        agreement=compare_results(left,right);self.assertTrue(agreement['exact'],agreement)
                        maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                        maximum_relative=max(maximum_relative,agreement['maximum_relative'])
                    with patch.object(provider,'begin',side_effect=AssertionError('No replay provider')), \
                         patch.object(provider,'evaluate',side_effect=AssertionError('No replay provider')), \
                         patch('numerical_portfolio.stage_book',side_effect=AssertionError('No replay staging')), \
                         patch.object(experiment,'load',side_effect=AssertionError('No collecting replay')):
                        replay,recovered=self.run_stream(portfolio,config,experiment)
                    self.assertEqual(replay['result']['trials'],actual['result']['trials'])
                    self.assertEqual(replay['result']['execution']['recovered_trials'],3)
                    self.assertEqual(collected(stream),collected(recovered));cases+=1
        self.assertLessEqual(portfolio.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],1)
        print(json.dumps(dict(check='bounded-numerical-matrix',cases=cases,trials=cases*3,
            maximum_absolute=maximum_absolute,maximum_relative=maximum_relative,tolerance=1e-12)),flush=True)

    def test_legacy_dates_producer_and_actual_attachment_freshness(self):
        inputs,provider,portfolio,store=self.evaluator('source')
        config=robustness.plan(portfolio.db,start='2015-01-02',end='2016-12-30',trials=2,seed=42,rank_to=3)
        exp=store.open(numerical_random.checkpoint_binding(portfolio,config))
        result,stream=self.run_stream(portfolio,config,exp)
        self.assertEqual(result['result']['completed'],2)
        captures=[];numerical_random.run(portfolio,config,exp,capture=lambda n,r:captures.append(r))
        self.assertEqual(captures,collected(stream))
        import test_numerical_generation as generations
        from numerical_numba import NumbaExecutor
        from numerical_portfolio import NumericalPortfolio
        fixture=generations.GenerationTests('test_export_values_order_missingness_and_mutable_books_reuse')
        fixture.setUp();self.addCleanup(fixture.doCleanups);fixture.prepare();attached=fixture.attach()
        self.addCleanup(attached.close)
        native_provider=NumbaExecutor(attached,limits=dict(threads=2,request_plan=True,candidate_assembly='source'))
        self.addCleanup(native_provider.close)
        owned=NumericalPortfolio(attached,native_provider);self.addCleanup(owned.close)
        plan=self.config(owned,rank_to=3);experiment=store.open(numerical_random.checkpoint_binding(owned,plan))
        self.run_stream(owned,plan,experiment)
        fixture.binding['prices']={'fictional_revision':1}
        with patch.object(experiment,'replay_into',side_effect=AssertionError('Validate actual inputs first')):
            with self.assertRaisesRegex(ValueError,'stale'):self.run_stream(owned,plan,experiment)
        fixture.binding['prices']={}

    def test_duplicate_legacy_mixed_recovery_capture_retention_and_callback_failure(self):
        inputs,provider,portfolio,store=self.evaluator('source');config=self.config(portfolio,pool='cached',rank_to=3)
        config['samples']=[config['samples'][0][:] for _ in range(3)]
        experiment=store.open(numerical_random.checkpoint_binding(portfolio,config))
        original=portfolio.backtest_calendar(dates=config['samples'][0],**numerical_calendar.request_fields(config),**config['options'])['result']
        experiment.save(1,original)
        def progress(event):
            if event['completed']==2:
                self.assertIsNotNone(experiment.load(2));raise RuntimeError('fictional progress failure')
        stream=io.BytesIO();output=writer(stream,3)
        with self.assertRaisesRegex(RuntimeError,'progress'):numerical_random.run_into(portfolio,config,experiment,output,progress)
        self.assertTrue(output.failed)
        with self.assertRaises(ValueError):result_evidence.Reader(stream,max_bytes=LIMIT)
        self.assertIsNone(experiment.load(3))
        actual,stream=self.run_stream(portfolio,config,experiment)
        self.assertEqual(actual['result']['execution']['recovered_trials'],2)
        self.assertEqual(actual['result']['unique_schedules'],1)
        self.assertEqual(collected(stream)[0],original)
        captures=[];numerical_random.run(portfolio,config,experiment,capture=lambda n,r:captures.append(r))
        self.assertEqual(captures,collected(stream))
        # Derived retention exhaustion cannot remove existing completed work.
        store.db.execute('DELETE FROM trials WHERE number=3');store.max_payload_bytes=0
        actual,stream=self.run_stream(portfolio,config,experiment)
        self.assertEqual(actual['result']['execution']['unretained_trials'],1)
        self.assertIsNotNone(experiment.load(1));self.assertIsNotNone(experiment.load(2));self.assertIsNone(experiment.load(3))
        self.assertEqual(len(collected(stream)),3)

    def test_binding_revalidation_cancel_sink_failure_and_eager_admission(self):
        inputs,provider,portfolio,store=self.evaluator('source');config=self.config(portfolio,rank_to=3)
        experiment=store.open(numerical_random.checkpoint_binding(portfolio,config))
        with patch.object(provider,'evaluate',side_effect=AssertionError('Validate sink before provider')):
            with self.assertRaisesRegex(ValueError,'sink'):portfolio.backtest_calendar_into(None,**numerical_calendar.request_fields(config),**config['options'])
            with self.assertRaisesRegex(ValueError,'sink'):portfolio.backtest_dates_into(None,dates=['2015-01-02'],start='2015-01-02',end='2015-02-27')
        for field in ('signature',):
            with patch.object(inputs,field,'changed'),patch.object(experiment,'replay_into',side_effect=AssertionError('Validate before reuse')):
                with self.assertRaisesRegex(ValueError,'binding'):self.run_stream(portfolio,config,experiment)
        with patch.object(backtest_control,'checkpoint',side_effect=backtest_control.Cancelled):
            with self.assertRaises(backtest_control.Cancelled):self.run_stream(portfolio,config,experiment)
        stream=io.BytesIO();output=writer(stream,3)
        with patch.object(output,'period',side_effect=OSError('fictional sink full')):
            with self.assertRaises(OSError):numerical_random.run_into(portfolio,config,experiment,output)
        self.assertFalse(portfolio.db.in_transaction);self.assertTrue(output.failed);self.assertIsNone(experiment.load(1))
        portfolio.result_workspace_bytes=50000
        with self.assertRaisesRegex(ValueError,'workspace'):portfolio.backtest_calendar(
            dates=config['samples'][0],**numerical_calendar.request_fields(config),**config['options'])
        actual,_=self.run_stream(portfolio,config,experiment)
        self.assertEqual(actual['result']['completed'],3)
        store.close();portfolio.close();provider.close();inputs.close()
        self.assertTrue(store.closed and portfolio.closed and inputs.closed)


if __name__=='__main__':unittest.main()

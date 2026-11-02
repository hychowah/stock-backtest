"""Private scalar trial evidence, numerical scopes and complete recovery."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from contextlib import ExitStack, closing
from copy import deepcopy
from datetime import date
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backtest import calendar_requests, portfolio_results, scalar_result_evidence, result_evidence
from backtest.application import scalar_execution, strategy_requests, evidence_views
from backtest.engines.numerical import trial, checkpoints, formulas
from backtest.runtime import backtest_control
from test_scalar_execution import Fixture

LIMITS=dict(max_bytes=32*1024**2,piece_bytes=65536,record_bytes=8*1024**2)


class ScalarTrialTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture(12);self.addCleanup(self.fixture.db.close)
        self.capture=self.fixture.capture()
        self.options=dict(strategy=self.capture.to_dict())
        self.plan=calendar_requests.plan([date(2015,1,2),date(2015,1,5)],dict(
            self.options,start='2015-01-02',end='2015-01-05',months=12,trials=2,seed=42))
        self.binding=dict(generation='fixture',policy='fixture',schema='fixture',result_contract=2,
            implementation=dict(fixture=True),execution=dict(scalar=dict(capture=self.capture.to_dict())),
            configuration=self.plan)

    def produce(self,number=1,*,limits=None,change=None):
        spec=trial.specification(self.binding,number)
        metadata=dict(mode='random',options=spec['options'],specification=spec['sha256'])
        stream=io.BytesIO();writer=scalar_result_evidence.SingleTrialWriter(stream,number=number,metadata=metadata,**(limits or LIMITS))
        with self.fixture.view() as view,formulas.Evaluator() as arithmetic:
            def evidence(record):
                if change is not None:record=change(deepcopy(record))
                writer.evidence(record)
            executor=scalar_execution.Executor(self.capture,view,evidence,evaluate=arithmetic.evaluate,
                scope_prefix='trial:'+str(number)+':',aggregate_trials=2)
            pairs=[(date(2015,1,2),date(2015,1,5))]
            summary=portfolio_results.evaluate_into(pairs,lambda a,b:dict(entry=str(a),exit=str(b),spy=.1,
                holdings=executor.select(self.fixture.db,1,a,b)),writer.period,contract=2,common_start=date(2015,1,2))
        summary.update(months=12,options=spec['options'],seconds=.01)
        sealed=writer.finish(summary)
        descriptor=dict(version=2,number=number,calculation_identity=spec['calculation_identity'],
            specification=spec['sha256'],start=0,end=sealed.end,sha256=sealed.sha256,limits=limits or LIMITS)
        artifact=trial.open_artifact(stream,descriptor,expected_spec=spec,limits=limits or LIMITS,checkpoint=lambda:None)
        return stream,sealed,artifact,spec,descriptor

    def test_complete_scalar_trial_roundtrip_retains_all_explanations(self):
        stream,view,artifact,spec,descriptor=self.produce()
        records=list(view.records())
        self.assertEqual(spec['version'],2);self.assertEqual(spec['requested'],2)
        self.assertTrue(any(r['type']=='evaluation' for r in records))
        self.assertEqual(len(list(view.periods())),1)
        self.assertEqual(artifact.summary['growth'],1+.009)
        self.assertEqual([r['value']['id'] for r in records if r['type']=='scope'],['trial:1:scope:1'])
        self.assertEqual(len(stream.getvalue()),descriptor['end'])

    def test_two_trial_replay_keeps_distinct_scope_links_and_record_contents(self):
        output=io.BytesIO();writer=scalar_result_evidence.Writer(output,trials=2,
            metadata=dict(mode='random',options=self.options),**LIMITS)
        expected=[]
        for number in (1,2):
            _,view,artifact,_,_=self.produce(number)
            expected.extend(r for r in view.records() if r['type'] in scalar_result_evidence.EXTRA)
            writer.start_trial(number);summary=artifact.replay_into(writer);writer.end_trial(summary)
        writer.finish(dict(done=True))
        reader=result_evidence.open_reader(output,**LIMITS)
        actual=[r for r in reader.records() if r['type'] in scalar_result_evidence.EXTRA]
        self.assertEqual(actual,expected)
        self.assertEqual({r['value']['id'] for r in actual if r['type']=='scope'},
            {'trial:1:scope:1','trial:2:scope:1'})

    def test_checkpoint_retains_original_records_without_catalog_or_inputs(self):
        _,view,_,_,_=self.produce()
        with tempfile.TemporaryDirectory() as root,checkpoints.Store(Path(root)/'checkpoints.sqlite') as store:
            experiment=store.open(self.binding)
            self.assertTrue(experiment.save_from(1,view)['retained'])
            output=io.BytesIO();writer=scalar_result_evidence.Writer(output,trials=1,
                metadata=dict(mode='random',options=self.options),**LIMITS)
            writer.start_trial(1)
            with (patch.object(strategy_requests,'builtin_catalog',side_effect=AssertionError('No live catalog')),
                  patch.object(formulas.Evaluator,'evaluate',side_effect=AssertionError('No calculation'))):
                summary=experiment.replay_evidence(1,writer)
            writer.end_trial(summary);writer.finish(summary)
            self.assertFalse(store.db.in_transaction)
            copied=[r for r in result_evidence.open_reader(output,**LIMITS).records() if r['type'] in scalar_result_evidence.EXTRA]
            self.assertEqual(copied,[r for r in view.records() if r['type'] in scalar_result_evidence.EXTRA])
            with self.assertRaisesRegex(ValueError,'complete evidence'):experiment.load(1)

    def test_checkpoint_corrupted_explanation_fails_even_when_financial_rows_unchanged(self):
        _,view,_,_,_=self.produce()
        with tempfile.TemporaryDirectory() as root,checkpoints.Store(Path(root)/'checkpoints.sqlite') as store:
            experiment=store.open(self.binding);experiment.save_from(1,view)
            raw=store.db.execute('SELECT payload FROM trials').fetchone()[0]
            position=raw.index(b'formula-evaluation')
            corrupted=raw[:position]+b'X'+raw[position+1:]
            store.db.execute('UPDATE trials SET payload=?',(corrupted,))
            with self.assertRaisesRegex(ValueError,'Corrupt'):experiment.replay_into(1,lambda period:None)
            self.assertFalse(store.db.in_transaction)

    def test_duplicate_save_compares_explanations_not_only_periods(self):
        _,first,_,_,_=self.produce()
        def alter(record):
            if record['type']=='scope':record['value']['extension']='different original trace'
            return record
        _,second,_,_,_=self.produce(change=alter)
        self.assertEqual(list(first.periods()),list(second.periods()))
        with tempfile.TemporaryDirectory() as root,checkpoints.Store(Path(root)/'checkpoints.sqlite') as store:
            experiment=store.open(self.binding);experiment.save_from(1,first)
            with self.assertRaisesRegex(ValueError,'Conflicting'):experiment.save_from(1,second)
            self.assertFalse(store.db.in_transaction)

    def test_presentation_capture_is_separate_from_unchanged_recorded_plan(self):
        original=deepcopy(self.plan)
        changed=deepcopy(self.binding);changed['execution']['scalar']['capture']['variables']['presentation'][0]['name']='New exact name'
        self.assertNotEqual(checkpoints.digest(checkpoints.binding_json(changed)),checkpoints.digest(checkpoints.binding_json(self.binding)))
        spec=trial.specification(changed,1)
        self.assertEqual(spec['options']['strategy']['variables']['presentation'][0]['name'],'New exact name')
        self.assertEqual(changed['configuration'],original)

    def test_scalar_view_rejects_truncation_and_invalid_task_identity(self):
        stream,view,_,spec,descriptor=self.produce()
        for raw in (stream.getvalue()[:-1],stream.getvalue()[:25]+b'X'+stream.getvalue()[26:]):
            with self.assertRaises(ValueError):
                trial.open_artifact(io.BytesIO(raw),descriptor,expected_spec=spec,limits=LIMITS,checkpoint=lambda:None)
        forged=deepcopy(spec);forged['requested']=101
        forged['sha256']=checkpoints.digest(checkpoints.canonical({k:v for k,v in forged.items() if k!='sha256'}))
        with self.assertRaises(ValueError):trial._specification(forged)

    def test_exhausted_evidence_reservation_never_seals_a_trial(self):
        for limits in (dict(LIMITS,max_bytes=64),dict(LIMITS,record_bytes=128)):
            with self.assertRaises(ValueError):self.produce(limits=limits)

    def test_scalar_failure_projection_is_checked_and_complete(self):
        from backtest.variables.definitions import FormulaError
        error=FormulaError(errors=[dict(code='UNIT_MISMATCH',path='/left',message='Use matching units.'),
            dict(code='FUTURE_DATE',path='/right/date',message='Use an earlier date.')])
        details=strategy_requests.failure_details(error)
        restored=strategy_requests.restore_failure(details)
        self.assertEqual(strategy_requests.failure_details(restored),details)
        bad=deepcopy(details);bad['code']='FUTURE_DATE'
        with self.assertRaises(ValueError):strategy_requests.restore_failure(bad)



class ActualScopeTests(unittest.TestCase):
    def setUp(self):
        from numerical_scalar_fixture import Inputs
        from test_variable_definitions import entry,definition
        from test_strategy_requests import intent,formula
        self.fixture=Inputs();self.addCleanup(self.fixture.close)
        raw=entry(definition(dict(op='parameter',id='annual.revenue'),'USD','usd'),'draft:revenue')
        value=intent(formula(raw));value['pool']='cached'
        self.capture=strategy_requests.capture_strategy(value,submitted=[raw])
        self.inputs=self.fixture.store.open_current();self.addCleanup(self.inputs.close)

    def test_generation_owned_prepared_reader_closes_before_attachment(self):
        with self.inputs.prepared_scopes() as reader:
            db=reader.db
            self.assertEqual(db.execute('SELECT count(*) FROM latest_snapshots').fetchone()[0],2)
            reader.validate()
        self.assertFalse(self.inputs._prepared_readers)
        with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')

    def test_prepared_reader_rejects_changed_metadata_and_reports(self):
        with self.inputs.prepared_scopes() as reader:
            with closing(sqlite3.connect(self.fixture.fixture.source)) as db:
                db.execute("UPDATE metadata SET value='{}' WHERE key='inputs'");db.commit()
            with self.assertRaises(ValueError):reader.validate()
        self.assertFalse(self.inputs._prepared_readers)

    def test_constructor_validation_and_failed_close_retain_borrower_for_retry(self):
        from backtest.inputs import research
        from backtest.engines.numerical import generation
        connection=research.connect(full_prices=True)
        class FailedClose:
            def __init__(self):self.attempts=0
            def __getattr__(self,name):return getattr(connection,name)
            def close(self):
                self.attempts+=1
                if self.attempts==1:raise OSError('Private injected close failure')
                connection.close()
        wrapped=FailedClose()
        with (patch.object(self.inputs,'validate',return_value=None),
              patch.object(research,'connect',return_value=wrapped),
              patch.object(generation.PreparedScopeReader,'_file',side_effect=ValueError('Private validation failure'))):
            with self.assertRaises(OSError):self.inputs.prepared_scopes()
        self.assertEqual(len(self.inputs._prepared_readers),1)
        self.assertIs(self.inputs._prepared_readers[0].db,wrapped)
        self.assertFalse(self.inputs.closed)
        self.inputs.close()
        self.assertTrue(self.inputs.closed)
        self.assertEqual(wrapped.attempts,2)
        self.assertFalse(self.inputs._prepared_readers)
        with self.assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')

    def test_genuine_numerical_custom_scope_matches_reference_selection_and_returns(self):
        from backtest.engines.numerical import scalar
        from backtest.application import scalar_runs
        from backtest.inputs import daily,sqlite_observations
        options=dict(strategy=self.capture.to_dict(),start='2015-01-02',end='2015-10-20',months=3)
        actual=io.BytesIO();writer=scalar_result_evidence.Writer(actual,trials=1,metadata=dict(mode='custom',options=options),**LIMITS)
        with scalar.Resources(self.inputs,dict(threads=1,request_plan=True,candidate_assembly='compiled',workspace_bytes=64*1024**2,matrix_cache_bytes=16*1024**2)) as resources:
            writer.start_trial(1);summary=resources.evaluate_periods(options,writer);writer.end_trial(summary)
            self.assertGreater(resources.provider.stats['books'],0)
            self.assertEqual(resources.evaluator.stats['kernel_compilations'],1)
        writer.finish(summary)
        expected=io.BytesIO();original=scalar_result_evidence.Writer(expected,trials=1,metadata=dict(mode='custom',options=options),**LIMITS)
        with closing(daily.connect()) as db,sqlite_observations.prepared_view(db,lambda:None) as view:
            before=scalar_runs.execute(db,None,'custom',options,original,view,None)
        original.finish(before)
        left=result_evidence.open_reader(expected,**LIMITS);right=result_evidence.open_reader(actual,**LIMITS)
        self.assertEqual(left.manifest['summary']['growth'],right.manifest['summary']['growth'])
        for n in range(1,4):
            x=list(evidence_views.holdings(left,1,n));y=list(evidence_views.holdings(right,1,n))
            self.assertEqual([{k:v for k,v in h.items() if k!='scalar_evidence'} for h in x],
                [{k:v for k,v in h.items() if k!='scalar_evidence'} for h in y])

    def test_prepared_latest_january_use_authoritative_population_without_book_provider(self):
        from backtest.engines.numerical import scalar
        for mode,extra in [('latest',{}),('january',dict(first=2015,last=2015))]:
            options=dict(strategy=self.capture.to_dict(),**extra)
            stream=io.BytesIO();writer=scalar_result_evidence.Writer(stream,trials=0 if mode=='latest' else 1,metadata=dict(mode=mode,options=options),**LIMITS)
            with scalar.Resources(self.inputs,dict(threads=1,workspace_bytes=64*1024**2)) as resources:
                with patch.object(resources,'books',side_effect=AssertionError('No reconstructed prepared book')):
                    summary=resources.prepared(mode,options,writer)
                self.assertIsNone(resources.provider)
            writer.finish(summary)
            decoded=result_evidence.open_reader(stream,**LIMITS)
            self.assertEqual(decoded.manifest['holdings'],1)
            if mode=='latest':
                self.assertEqual(summary['asof'],'2015-10-20')
                self.assertEqual(decoded.manifest['periods'],0)
            else:self.assertEqual(summary['growth'],1.1)

    def test_resource_split_preserves_declared_total_and_warms_before_observation(self):
        from backtest.engines.numerical import scalar
        allocation=scalar.resources(dict(workspace_bytes=64*1024**2,matrix_cache_bytes=16*1024**2))
        self.assertEqual(allocation['book']['workspace_bytes']+allocation['formula']+allocation['metadata'],64*1024**2)
        with patch.object(self.inputs,'observations',side_effect=AssertionError('No observations')):
            with self.assertRaises(AssertionError):scalar.Resources(self.inputs,dict(workspace_bytes=64*1024**2),warm=True)
        self.inputs.validate()

    def test_all_captured_builtin_descriptors_declare_actual_lanes_and_match_original(self):
        from backtest.engines.numerical import scalar
        from backtest.application import scalar_runs
        from backtest.inputs import daily,sqlite_observations
        from test_strategy_requests import builtin,intent
        def run(capture,resources=None):
            options=dict(strategy=capture.to_dict(),start='2015-01-02',end='2015-04-02',months=3)
            output=io.BytesIO();writer=scalar_result_evidence.Writer(output,trials=1,metadata=dict(mode='custom',options=options),**LIMITS)
            if resources is not None:
                writer.start_trial(1);summary=resources.evaluate_periods(options,writer);writer.end_trial(summary)
            else:
                with closing(daily.connect()) as db,sqlite_observations.prepared_view(db,lambda:None) as view:
                    summary=scalar_runs.execute(db,None,'custom',options,writer,view,None)
            writer.finish(summary)
            return result_evidence.open_reader(output,**LIMITS)
        with scalar.Resources(self.inputs,dict(threads=1,workspace_bytes=64*1024**2)) as resources:
            for descriptor in strategy_requests.builtin_catalog():
                value=intent(builtin(descriptor['id']));value['pool']='cached'
                capture=strategy_requests.capture_strategy(value)
                left,right=run(capture),run(capture,resources)
                normalize=lambda reader:[{k:v for k,v in lane.items() if k!='scope'}
                    for record in reader.records() if record['type']=='lanes' for lane in record['value']['lanes']]
                self.assertEqual(normalize(left),normalize(right),descriptor['id'])
                strip=lambda reader:[{k:v for k,v in row.items() if k!='scalar_evidence'}
                    for row in evidence_views.holdings(reader,1,1)]
                self.assertEqual(strip(left),strip(right),descriptor['id'])
                self.assertEqual(left.manifest['summary']['growth'],right.manifest['summary']['growth'])
            self.assertEqual(resources.evaluator.stats['kernel_compilations'],0)



class SessionRecoveryTests(unittest.TestCase):
    setUp=ActualScopeTests.setUp

    def session(self):
        from backtest.engines.numerical.session import Session
        value=Session(dict(generation_path=str(self.fixture.store.path),
            checkpoint_path=str(self.fixture.root/'scalar-checkpoints.sqlite'),
            source_root=str(Path(__file__).resolve().parents[1]),scratch=str(self.fixture.root/'scalar-session'),
            execution=dict(workers=1,threads_per_worker=1,lane_budget=1)))
        self.addCleanup(value.close)
        return value

    def options(self,**extra):
        return dict(strategy=self.capture.to_dict(),start='2015-01-02',end='2015-10-20',months=3,**extra)

    def result(self,value,mode='custom',options=None,planned=None,progress=None):
        output=io.BytesIO();plans=[]
        result=value.calculate_into(mode,options or self.options(),output,progress,plans.append,
            planned=planned,**LIMITS)
        return result_evidence.open_reader(output,**LIMITS),plans,result

    def local(self,value,plan,options=None):
        from backtest.engines.numerical import random
        binding=value._binding(plan,scalar_capture=(options or self.options())['strategy'])
        return random._LocalExecution(value.workspace,binding)

    def test_candidate_session_fixed_and_prepared_modes_use_codec2(self):
        value=self.session()
        for mode,options in [('custom',self.options()),('latest',dict(strategy=self.capture.to_dict())),
                ('january',dict(strategy=self.capture.to_dict(),first=2015,last=2015))]:
            reader,_,_=self.result(value,mode,options)
            self.assertEqual(reader.format_version,2)
            self.assertEqual(reader.metadata['producer']['engine'],'experimental')
            self.assertEqual(reader.metadata['options']['engine'],'experimental')
            self.assertIsNone(value.scalar_resources)
        value.close();self.assertTrue(value.closed)

    def test_fresh_and_complete_hit_recover_full_evidence_before_constructors(self):
        from backtest.engines.numerical import scalar
        value=self.session();options=self.options(trials=2,seed=42);plan=value.plan(options)
        with patch.object(value,'pool',side_effect=lambda **kw:self.local(value,plan)):
            first,_,fresh=self.result(value,'random',options,plan)
        self.assertEqual(fresh['contract_version'],2)
        original=[r for r in first.records() if r['type'] in scalar_result_evidence.EXTRA]
        value.close();reopened=self.session()
        with (patch.object(reopened,'pool',side_effect=AssertionError('No workers')),
              patch.object(scalar,'Resources',side_effect=AssertionError('No provider or formula constructors'))):
            second,_,recovered=self.result(reopened,'random',options,plan)
        self.assertEqual(recovered['contract_version'],2)
        self.assertEqual([r for r in second.records() if r['type'] in scalar_result_evidence.EXTRA],original)
        self.assertEqual(second.manifest['summary']['execution']['calculated_trials'],0)
        self.assertEqual(second.manifest['summary']['execution']['recovered_trials'],2)
        self.assertEqual(second.manifest['summary']['execution']['workers'],0)
        self.assertEqual(reopened.stats['provider_constructions'],0)

    def test_interrupted_trial_commit_recovers_original_records_and_only_missing_work(self):
        value=self.session();options=self.options(trials=3,seed=17);plan=value.plan(options)
        def stop(event):
            if event and event.get('calculated_trials')==1:raise backtest_control.Cancelled()
        with patch.object(value,'pool',side_effect=lambda **kw:self.local(value,plan)):
            with self.assertRaises(backtest_control.Cancelled):self.result(value,'random',options,plan,stop)
        experiment=value.checkpoints.open(value._binding(plan,scalar_capture=options['strategy']))
        with experiment._trial(1) as view:
            original=[r for r in view.records() if r['type'] in scalar_result_evidence.EXTRA]
        self.assertFalse(value.checkpoints.db.in_transaction)
        with patch.object(value,'pool',side_effect=lambda **kw:self.local(value,plan)):
            reader,_,_=self.result(value,'random',options,plan)
        self.assertEqual(reader.manifest['summary']['execution']['calculated_trials'],2)
        self.assertEqual(reader.manifest['summary']['execution']['recovered_trials'],1)
        first=[]
        for record in reader.records():
            if record['type']=='end_trial':break
            if record['type'] in scalar_result_evidence.EXTRA:first.append(record)
        self.assertEqual(first,original)

    def test_later_trial_seven_recovers_exact_qualified_explanations(self):
        from backtest.engines.numerical import scalar
        value=self.session();options=self.options(trials=8,seed=11);plan=value.plan(options)
        binding=value._binding(plan,scalar_capture=options['strategy']);spec=trial.specification(binding,7)
        stream=io.BytesIO()
        with scalar.Resources(value.inputs,value.execution_policy.provider_limits) as resources:
            descriptor=scalar.TrialEvaluator(resources,calculation_identity=spec['calculation_identity']).produce(spec,stream,limits=LIMITS)
        artifact=trial.open_artifact(stream,descriptor,expected_spec=spec,limits=LIMITS,checkpoint=lambda:None)
        original=list(artifact.view.records());value.checkpoints.open(binding).save_from(7,artifact.view)
        with patch.object(value,'pool',side_effect=lambda **kw:self.local(value,plan)):
            reader,_,_=self.result(value,'random',options,plan)
        selected=[];active=None
        for record in reader.records():
            if record['type']=='trial':active=record['number']
            if active==7:selected.append(record)
            if active==7 and record['type']=='end_trial':break
        self.assertEqual(selected,original)
        scopes={r['value']['id'] for r in selected if r['type']=='scope'}
        self.assertTrue(scopes);self.assertTrue(all(v.startswith('trial:7:') for v in scopes))
        for record in selected:
            if record['type']=='holding':
                self.assertIn(record['value']['scalar_evidence']['scope'],scopes)
        self.assertEqual(reader.manifest['summary']['execution']['recovered_trials'],1)


class LargeScopeTests(unittest.TestCase):
    def setUp(self):
        from backtest.inputs import daily,observation_inputs
        from backtest.engines.numerical import generation
        from backtest.runtime import cache_access
        self.context=ExitStack();self.addCleanup(self.context.close)
        folder=self.context.enter_context(tempfile.TemporaryDirectory());self.root=Path(folder)
        self.fixture=Fixture(300);self.addCleanup(self.fixture.db.close)
        self.path=self.root/'daily.sqlite'
        with closing(sqlite3.connect(self.path)) as db:
            self.fixture.db.backup(db)
            # Both engines must compute the real book from private source rows.
            for table in ('period_pools','snapshots','screening_metrics','filter_values','periods'):
                db.execute('DELETE FROM '+table)
            db.commit()
            projection=observation_inputs.require(db,verify_content=True)
        program=generation.PolicyProgram()
        binding=dict(temporal_version=generation.TEMPORAL_VERSION,factor_version=generation.FACTOR_VERSION,
            field_schema=program.field_schema,daily=dict(inputs=dict(historical_through='2015-01-05')),
            prices={},report='synthetic',policy=program.signature,sources=generation._source_binding(program),
            observations=projection)
        def connect():
            db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row;return db
        self.connect=connect
        self.context.enter_context(patch.object(daily,'connect',side_effect=connect))
        self.store=generation.GenerationStore(self.root/'generation',cache_access.WorkspaceAccess(self.root/'cache.lock'))
        self.context.enter_context(patch.object(self.store,'_binding',side_effect=lambda:(binding,program)))
        self.store.prepare();self.inputs=self.store.open_current();self.context.callback(self.inputs.close)

    def run_scope(self,capture,resources=None):
        from backtest.engines.numerical import scalar
        from backtest.inputs import sqlite_observations
        from backtest.application import scalar_runs
        options=dict(strategy=capture.to_dict(),start='2015-01-02',end='2015-01-05',months=12)
        output=io.BytesIO();writer=scalar_result_evidence.Writer(output,trials=1,metadata=dict(mode='custom',options=options),**LIMITS)
        if resources is not None:
            writer.start_trial(1);summary=resources.evaluate_periods(options,writer);writer.end_trial(summary)
        else:
            with closing(self.connect()) as db,sqlite_observations.prepared_view(db,lambda:None) as view:
                summary=scalar_runs.execute(db,None,'custom',options,writer,view,None)
        writer.finish(summary)
        return result_evidence.open_reader(output,**LIMITS)

    def test_genuine_complete_book_chunks_mixed_lanes_orders_directions_ties_and_empty_scopes(self):
        from backtest.engines.numerical import scalar
        from test_strategy_requests import condition,builtin,formula
        from test_variable_definitions import entry,definition,constant
        raw=entry(definition(dict(op='parameter',id='annual.revenue'),'USD','usd'),'draft:ranking')
        mixed=[condition(builtin('filter:market_cap'),'149000000','USD'),
            condition(formula(raw),'275','USD')]
        with scalar.Resources(self.inputs,dict(threads=1,workspace_bytes=64*1024**2)) as resources:
            for pool in ('cached','legacy'):
                for order in ('filter_first','rank_first'):
                    for direction in ('highest','lowest'):
                        capture=self.fixture.capture(pool=pool,order=order,direction=direction,conditions=mixed)
                        left=self.run_scope(capture);right=self.run_scope(capture,resources)
                        x=list(evidence_views.holdings(left,1,1));y=list(evidence_views.holdings(right,1,1))
                        strip=lambda rows:[{k:v for k,v in row.items() if k!='scalar_evidence'} for row in rows]
                        self.assertEqual(strip(x),strip(y),(pool,order,direction))
                        self.assertEqual(left.manifest['summary']['growth'],right.manifest['summary']['growth'])
                        self.assertEqual(left.manifest['summary']['cagr'],right.manifest['summary']['cagr'])
                        blocks=[r['value']['block'] for r in right.records() if r['type']=='evaluation']
                        expected=300 if pool=='cached' else 250
                        self.assertEqual(sum(len(b['requests']) for b in blocks),expected)
                        if pool=='cached':self.assertGreater(len(blocks),1)
                        if pool=='legacy' or direction=='lowest' and order=='rank_first':self.assertEqual(y,[])
            capture=self.fixture.capture(constant('-0'),first=253,last=258)
            left=self.run_scope(capture);right=self.run_scope(capture,resources)
            self.assertEqual([r['symbol'] for r in evidence_views.holdings(right,1,1)],
                [r['symbol'] for r in evidence_views.holdings(left,1,1)])
            self.assertEqual([r['rank'] for r in evidence_views.holdings(right,1,1)],list(range(253,259)))
            # begin() resets per-request book counters; the final complete tie
            # request uses one book rather than one book per formula chunk.
            self.assertEqual(resources.provider.stats['books'],1)


if __name__=='__main__':unittest.main()

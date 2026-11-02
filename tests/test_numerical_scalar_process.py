"""Actual candidate child and worker scalar protocol qualification.

The native wrapper installs only the narrow guarded entry translator.
Every financial fixture/store is external and synthetic. Supported paths use
public admission without private policy overrides.
"""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from copy import deepcopy
from threading import Event
import io
import json
import time
import unittest
from unittest.mock import Mock,patch

from backtest import scalar_result_evidence,result_evidence
from backtest.application import strategy_requests,calculations,candidate_calculations
from backtest.engines.numerical import trial,random,trial_pool,policy
from backtest.engines.numerical.identity import compiler_identity
from backtest.engines.numerical.execution import ExecutionPolicy
from backtest.engines.numerical.runtime import NumericalRuntime
from backtest.engines.numerical.workspace import RequestWorkspace
from backtest.runtime import backtest_control
import test_numerical_scalar as offline
LIMITS=offline.LIMITS

ROOT=Path(__file__).resolve().parents[1]


class ScalarPoolTests(unittest.TestCase):
    setUp=offline.ActualScopeTests.setUp
    options=offline.SessionRecoveryTests.options
    session=offline.SessionRecoveryTests.session
    result=offline.SessionRecoveryTests.result


    def test_failed_or_cancelled_failure_publication_closes_all_owned_slot_files(self):
        from backtest.engines.numerical import runtime
        details=dict(code='WORK_LIMIT',path='/execution',errors=[
            dict(code='WORK_LIMIT',path='/execution',message='Private scalar failure')])
        for failure in ('replace','cancel'):
            with self.subTest(failure=failure):
                value=self.session();pool=value.pool(scalar=True)
                pool.start(required_workers=1)
                target=pool.scratch/'slot-0.failure.json'
                pending=target.with_suffix('.pending')
                runtime.write_payload(target,details,runtime.MAX_REQUEST_BYTES)
                original=target.read_bytes()
                if failure=='replace':
                    replace=Path.replace
                    def blocked(path,destination):
                        if path==pending:raise OSError('Private failure publication replacement')
                        return replace(path,destination)
                    with patch.object(Path,'replace',blocked):
                        with self.assertRaises(OSError):
                            runtime.write_payload(target,details,runtime.MAX_REQUEST_BYTES)
                else:
                    def checkpoint():
                        if pending.exists():raise backtest_control.Cancelled()
                    with self.assertRaises(backtest_control.Cancelled):
                        runtime.write_payload(target,details,runtime.MAX_REQUEST_BYTES,checkpoint=checkpoint)
                self.assertTrue(pending.exists())
                self.assertEqual(target.read_bytes(),original)
                pool.close();self.assertTrue(pool.closed)
                self.assertFalse(pool.scratch.exists())
                self.assertTrue(all(row['eof'] and row['reader_stopped'] and row['streams_closed']
                    for row in pool.closure()['workers']))
                value.close()

    def test_actual_two_workers_warm_formulas_and_keep_complete_leased_artifacts(self):
        value=self.session();options=self.options(trials=3,seed=42);plan=value.plan(options)
        binding=value._binding(plan,scalar_capture=options['strategy'])
        execution=ExecutionPolicy(dict(workers=2,threads_per_worker=1,lane_budget=2,
            private_memory_budget_bytes=2*1024**3,artifact_bytes=16*1024**2,close_seconds=5))
        compiler=compiler_identity(value.inputs,1,decisions=value.inputs.policy.decisions)
        pool=trial_pool.TrialPool(source_root=ROOT,scratch=self.fixture.root/'actual-scalar-pool',
            reference=value.inputs.worker_reference(),source_identity=random.source_identity(),
            compiler_identity=compiler,policy=execution,workload='scalar')
        self.addCleanup(pool.close)
        specs=[trial.specification(binding,n) for n in (1,2,3)]
        send,event=pool._send,pool._event;delayed=[]
        def delayed_send(worker,item):
            if item.get('command')=='trial' and worker.index==0 and not delayed:
                delayed.append((worker,item));return
            return send(worker,item)
        def next_event(*args):
            worker,item=event(*args)
            if item.get('event')=='completed' and delayed:send(*delayed.pop())
            return worker,item
        numbers=[]
        with patch.object(pool,'_send',side_effect=delayed_send),patch.object(pool,'_event',side_effect=next_event):
            with pool.batch(specs) as batch:
                for completion in batch.completed():
                    numbers.append(completion.number)
                    records=list(completion.artifact.view.records())
                    self.assertTrue(any(r['type']=='evaluation' for r in records))
                    self.assertTrue(all(r['value']['id'].startswith('trial:'+str(completion.number)+':')
                        for r in records if r['type']=='scope'))
                    completion.release()
        self.assertEqual(numbers[0],2);self.assertEqual(set(numbers),{1,2,3})
        self.assertEqual(pool.stats['started_workers'],2)
        self.assertEqual(pool.stats['reserved_bytes'],0)
        self.assertTrue(all(row['measurements']['formula']['kernel_compilations']==1 for row in pool.stats['readiness']))
        self.assertLessEqual(pool.stats['peak_reserved_bytes'],execution.identity['artifact_total_bytes'])
        pool.close();self.assertTrue(pool.closed)
        self.assertTrue(all(row['eof'] and row['reader_stopped'] and row['streams_closed'] for row in pool.closure()['workers']))

    def test_actual_random_session_full_hit_starts_no_workers_or_compilers(self):
        from backtest.engines.numerical import scalar,formulas
        value=self.session();options=self.options(trials=2,seed=42);plan=value.plan(options)
        first,_,_=self.result(value,'random',options,plan)
        self.assertEqual(first.manifest['summary']['execution']['workers'],1)
        original=[r for r in first.records() if r['type'] in scalar_result_evidence.EXTRA]
        pool=value.trial_pool;value.close();self.assertTrue(pool.closed)
        reopened=self.session()
        with patch.object(reopened,'pool',side_effect=AssertionError('No workers')),patch.object(scalar,'Resources',side_effect=AssertionError('No constructors')):
            second,_,_=self.result(reopened,'random',options,plan)
        self.assertEqual(second.manifest['summary']['execution']['recovered_trials'],2)
        self.assertEqual(second.manifest['summary']['execution']['calculated_trials'],0)
        self.assertEqual([r for r in second.records() if r['type'] in scalar_result_evidence.EXTRA],original)


class WorkerMarkerTests(unittest.TestCase):
    def test_real_worker_marker_cancels_active_trial_and_closes_without_publication(self):
        from scalar_qualification import Scenario
        with Scenario(companies=300,first=2015,last=2016) as scenario:
            case=offline.SessionRecoveryTests('runTest');case.fixture=scenario.fixture;case.capture=scenario.capture
            try:
                value=case.session();options=scenario.options('random',trials=1);plan=value.plan(options)
                binding=value._binding(plan,scalar_capture=options['strategy'])
                pool=value.pool(scalar=True);ordinary=pool._event;requested=[];observed=[]
                def event(*args):
                    worker,item=ordinary(*args)
                    if item.get('event')=='stage' and item.get('stage')=='calculating' and not requested:
                        requested.append(time.perf_counter());(pool.scratch/'cancel').touch()
                    if item.get('event')=='cancelled':observed.append(time.perf_counter())
                    return worker,item
                with patch.object(pool,'_event',side_effect=event),self.assertRaisesRegex(RuntimeError,'Trial worker failed'):
                    with pool.batch([trial.specification(binding,1)]) as batch:
                        for completion in batch.completed():self.fail('Cancelled trial was published.')
                retired=time.perf_counter()
                self.assertEqual(len(requested),1);self.assertEqual(len(observed),1)
                self.assertLess(observed[0]-requested[0],10)
                self.assertTrue(pool.closed);self.assertFalse(pool.scratch.exists())
                self.assertEqual(pool.stats['completed_trials'],0)
                closure=pool.closure()
                self.assertTrue(all(row['eof'] and row['reader_stopped'] and row['streams_closed']
                    and row['native_handles_released'] for row in closure['workers']))
                value.close()
            finally:self.assertTrue(case.doCleanups())
        print('WORKER_CANCELLATION_RECEIPT '+json.dumps(dict(
            observation_seconds=observed[0]-requested[0],retirement_seconds=retired-requested[0],
            observation_scope='Parent marker publication to worker cancelled event; includes checkpoint wait and protocol delivery',
            stage='active shared-formula scalar trial after warm worker readiness',companies=300,
            first=2015,last=2016,trials=1,seed=42,closure=closure),sort_keys=True),
            file=sys.__stdout__,flush=True)



class ScalarCandidateTests(unittest.TestCase):
    setUp=offline.ActualScopeTests.setUp
    options=offline.SessionRecoveryTests.options

    def candidate(self,*,fault=None):
        from backtest.inputs import daily
        # The test child uses the exact parent-created private generation and
        # research reader. No installed raw/prepared asset is selected.
        root=self.fixture.root
        (root/'binding.json').write_text(json.dumps(self.fixture.store._binding()[0]))
        (root/'scalar-fixture.json').write_text(json.dumps(dict(kind='synthetic-scalar-fixture')))
        preparation=Mock();preparation.status.return_value=dict(state='current');created=[]
        def make():
            value=NumericalRuntime(source_root=ROOT,scratch=root/('wire-'+str(len(created))),
                generation_path=self.fixture.store.path,checkpoint_path=root/'wire-checkpoints.sqlite',
                python=sys.executable,coordinator=self.fixture.owner,
                session_factory='numerical_scalar_fixture:WireSession',session_options=dict(scalar_fixture=str(root),scalar_fault=fault,
                    execution=dict(workers=1,threads_per_worker=1,lane_budget=1)))
            start=value.start
            def launch(**kwargs):
                value.configuration['preparation_status']=False
                return start(**kwargs)
            value.start=launch;created.append(value);return value
        preparation._runtime.side_effect=make
        owner=candidate_calculations.Candidate(preparation);self.addCleanup(owner.retire)
        return owner,created

    def test_actual_candidate_child_transfers_codec2_all_modes_and_closes_before_result(self):
        owner,created=self.candidate()
        for mode,options in [('custom',self.options()),('latest',dict(strategy=self.capture.to_dict())),
                ('january',dict(strategy=self.capture.to_dict(),first=2015,last=2015)),
                ('random',self.options(trials=2,seed=42))]:
            output=io.BytesIO()
            owner.calculate_into(mode,options,output,None,lambda value:None,**LIMITS)
            self.assertIsNone(owner.runtime)
            runtime=created[-1]
            self.assertEqual(runtime.closure()['state'],'closed')
            reader=result_evidence.open_reader(output,**LIMITS)
            self.assertEqual(reader.format_version,2)
            self.assertEqual(reader.metadata['producer']['engine'],'experimental')
            self.assertGreater(reader.manifest['holdings'],0)

    def test_unsupported_scalar_mode_is_rejected_before_preparation_or_runtime(self):
        owner,created=self.candidate()
        with self.assertRaises(ValueError) as caught:owner.calculate_into('unsupported',self.options(),io.BytesIO(),None,None,**LIMITS)
        self.assertEqual(caught.exception.code,'UNSUPPORTED_CAPABILITY')
        self.assertFalse(created)
        owner.preparation.status.assert_not_called()

    def test_child_formula_error_preserves_safe_fields_and_closes_before_failure(self):
        from backtest.variables.definitions import FormulaError
        owner,created=self.candidate(fault='formula')
        with self.assertRaises(FormulaError) as caught:
            owner.calculate_into('custom',self.options(),io.BytesIO(),None,None,**LIMITS)
        self.assertEqual(caught.exception.code,'WORK_LIMIT')
        self.assertEqual(caught.exception.path,'/fixture/expression')
        self.assertEqual(len(caught.exception.to_dict()['errors']),1)
        self.assertIsNone(owner.runtime)
        self.assertEqual(created[-1].closure()['state'],'closed')

    def test_pinned_selectable_jobs_queue_retries_and_detached_saved_exports(self):
        from backtest.application import jobs,queue,library as saved,evidence_views,result_exports
        from backtest.inputs import research
        from backtest.variables import library as variable_library
        from test_strategy_requests import intent,formula
        from test_variable_definitions import definition
        variable_store=variable_library.Store(self.fixture.root/'variables.sqlite')
        authored=self.capture.to_dict()['variables']['program']['bundle']['definitions'][0]['definition']
        original_variable=variable_store.create('Original captured revenue',authored)
        captured_intent=intent(formula(original_variable))
        captured_intent['pool']='cached'
        self.capture=strategy_requests.capture_strategy(captured_intent,variable_store)
        owner,created=self.candidate()
        selectable=calculations.Selectable(owner.preparation);selectable.experimental=owner
        self.addCleanup(selectable.close)
        selectable.ready_for=lambda *args,**kwargs:True
        options=dict(self.options(),engine='experimental')
        manager=jobs.Jobs(selectable,evidence_root=self.fixture.root/'jobs');self.addCleanup(manager.close)
        store=queue.Store(self.fixture.root/'queue.sqlite');library=saved.Store(self.fixture.root/'saved.sqlite')
        consumer=queue.Queue(store,calculations=selectable,library=library);self.addCleanup(consumer.close)
        request=dict(id='c'*32,name='Pinned scalar',mode='custom',options=deepcopy(options),catalog=dict(metrics={},filters={}),presentation={})
        with patch.object(selectable.original,'calculate_into',side_effect=AssertionError('Pinned Candidate only')):
            entered,release=Event(),Event();calculate=selectable.calculate_into
            def held(*args,**kwargs):
                entered.set()
                if not release.wait(10):raise AssertionError('Private accepted-job barrier timed out.')
                return calculate(*args,**kwargs)
            with patch.object(selectable,'calculate_into',side_effect=held):
                manager.start('b'*32,'custom',options)
                try:
                    self.assertTrue(entered.wait(5))
                    changed=variable_store.edit(original_variable['variable_id'],original_variable['version'],
                        definition(dict(op='parameter',id='annual.operating_income'),'USD','usd'))
                    self.assertNotEqual(changed['revision'],original_variable['revision'])
                    variable_store.delete(changed['variable_id'],changed['version'])
                    with self.assertRaises(variable_library.Missing):variable_store.get(changed['variable_id'])
                finally:release.set()
                manager.runs['b'*32]['thread'].join(90)
            run=manager.snapshot('b'*32);self.assertEqual(run['state'],'complete',run)
            self.assertEqual(run['engine'],'experimental')
            count=len(created)
            self.assertEqual(manager.start('b'*32,'custom',deepcopy(options))['state'],'complete')
            self.assertEqual(len(created),count)
            store.enqueue(request);claimed=store.claim()
            # Startup recovery retains exact accepted intent through another claim.
            store.recover();claimed=store.claim()
            consumer._run(claimed)
            completed=store.listing()['records'][0]
            self.assertEqual(completed['state'],'complete',
                {key:completed.get(key) for key in ('state','error','code','path')})
            consumer.reconcile_completed();record=library.list()[0]
        with (patch.object(selectable,'calculate_into',side_effect=AssertionError('No calculation')),
              patch.object(strategy_requests,'builtin_catalog',side_effect=AssertionError('No live catalog')),
              patch.object(variable_library.Store,'capture',side_effect=AssertionError('No current variable capture')),
              patch.object(variable_library.Store,'get',side_effect=AssertionError('No current variable entry')),
              patch.object(selectable.preparation,'status',side_effect=AssertionError('No preparation lookup')),
              patch.object(selectable.preparation,'_runtime',side_effect=AssertionError('No runtime')),
              patch.object(research,'connect',side_effect=AssertionError('No input lookup')),
              patch.object(self.fixture.store,'open_current',side_effect=AssertionError('No generation lookup'))):
            with library.open_evidence(record['id']) as opened:
                self.assertEqual(opened.metadata['settings']['engine'],'experimental')
                with opened.open_reader() as reader:
                    self.assertEqual(reader.format_version,2)
                    self.assertEqual(reader.metadata['options']['strategy'],self.capture.to_dict())
                    holding=list(evidence_views.holdings(reader,1,1))[0]
                    self.assertEqual(holding['ranking_value'],100e6)
                    self.assertEqual(reader.metadata['options']['strategy']['variables']['presentation'][0]['name'],'Original captured revenue')
                    self.assertTrue(holding['scalar_evidence']['scope'].startswith('trial:1:'))
                    complete=result_exports.prepare(reader,'evidence')
                    original=b''.join(complete.chunks())
                    self.assertGreater(len(original),0)
                    self.assertEqual(len(original),complete.content_length)
                    self.assertEqual(result_evidence.open_reader(io.BytesIO(original),**LIMITS).metadata,reader.metadata)
                    csv=result_exports.prepare(reader,'holdings')
                    exported=b''.join(csv.chunks())
                    self.assertEqual(len(exported),csv.content_length)
                    self.assertIn(b'ranking_value',exported)
            with manager.display_evidence('b'*32,{}) as opened:
                self.assertEqual(opened.metadata['version'],4)
        self.assertTrue(all(value.closure()['state']=='closed' for value in created))


if __name__=='__main__':unittest.main()

"""Persistent candidate application admission on fictional numerical inputs."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.application.original_calculations import Original
from backtest.application.calculation_contract import Unavailable
from backtest.inputs import daily
import json
from pathlib import Path
import sys
import sqlite3
import time
from threading import Event, Thread
from unittest.mock import Mock, patch
import unittest

ROOT=Path(__file__).absolute().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'scripts'),str(ROOT)]
import test_numerical_runtime as runtime_tests
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.engines.numerical.portfolio import compare_results
from backtest.application.candidate_calculations import Candidate
from backtest.engines.original import robustness as robustness
from backtest.application import jobs as backtest_jobs
from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import cache_access as cache_access
from website.server import data_manager
from backtest.application import queue as backtest_queue
from test_queue import request
from backtest.engines.numerical.runtime import ClosureError


class CandidateTests(unittest.TestCase):
    setUp=runtime_tests.RuntimeTests.setUp
    make=runtime_tests.RuntimeTests.make
    options=runtime_tests.RuntimeTests.options
    assert_closed=runtime_tests.RuntimeTests.assert_closed
    # Reuse fictional runtime setup without repeating its independent suite.
    def candidate(self,**runtime_options):
        preparation=Mock()
        preparation.status.return_value=dict(state='current')
        preparation._runtime.side_effect=lambda:self.make(**runtime_options)
        owner=Candidate(preparation)
        owner.created=[]
        # These inputs use the runtime's fictional binding rather than a full
        # source-root preparation report. Real report checks run in the fixture.
        original=preparation._runtime.side_effect
        def make():
            value=original()
            owner.created.append(value)
            start=value.start
            def launch(**kw):
                value.configuration['preparation_status']=False
                return start(**kw)
            value.start=launch
            calculate=value.calculate
            def call(mode,*args,**kw):
                if mode=='__inspect__':return dict(state='current')
                value.configuration['preparation_status']=False
                return calculate(mode,*args,**kw)
            value.calculate=call
            return value
        preparation._runtime.side_effect=make
        self.addCleanup(owner.retire)
        return owner

    def test_operation_closure_full_trials_summary_replay_and_parent_handoff(self):
        owner=self.candidate();options=self.options()
        result=owner.calculate('custom',options,None,None)
        self.assertTrue(compare_results(self.fixture.s.backtest(self.fixture.db,**options),result)['exact'])
        runtime=owner.created[-1];self.assert_closed(runtime)
        self.assertIsNone(owner.runtime)
        self.assertEqual(owner.status()['state'],'current')
        self.assertTrue(compare_results(owner.calculate('custom',options,None,None),result)['exact'])
        self.assertIsNot(owner.created[-1],runtime)
        self.assert_closed(owner.created[-1])
        options=self.options(trials=24,seed=42);plans=[]
        full=owner.calculate('random',options,None,plans.append)
        self.assertEqual(len(full['trial_results']),24)
        trials=[]
        ordinary=robustness.run(self.fixture.db,plans[0],capture=lambda n,r:trials.append(r))
        self.assertEqual(ordinary['distributions'],full['distributions'])
        for expected,actual in zip(trials,full['trial_results']):
            self.assertTrue(compare_results(expected,actual)['exact'])
        for filters in ([dict(field='pe',op='lt',value=20.)],[dict(field='pe',op='gt',value=1e9)]):
            changed=self.options(filters=filters)
            actual=owner.calculate('custom',changed,None,None)
            self.assertTrue(compare_results(self.fixture.s.backtest(self.fixture.db,**changed),actual)['exact'])
        summary=owner.calculate('random',options,None,None,planned=plans[0],details=False)
        self.assertNotIn('trial_results',summary)
        self.assertEqual(summary['distributions'],full['distributions'])
        with owner.parent_operation():
            self.assert_closed(runtime)
            with self.fixture.owner.hold(timeout=0):pass
        self.assertIsNone(owner.runtime)
        owner.calculate('custom',self.options(),None,None)
        self.assertIsNone(owner.runtime)
        self.assert_closed(owner.created[-1])

    def test_uncertain_retirement_blocks_parent_until_proof_and_status_is_bounded(self):
        owner=self.candidate();owner.calculate('custom',self.options(),None,None)
        runtime=owner.preparation._runtime();owner.runtime=runtime;runtime.start()
        original=runtime.close;release=Event();entered=Event();done=Event()
        def close():
            entered.set()
            if not release.is_set():raise ClosureError(runtime)
            original()
        runtime.close=close
        def work():
            with owner.parent_operation():done.set()
        thread=Thread(target=work);thread.start();self.assertTrue(entered.wait(3))
        self.assertFalse(done.is_set());self.assertTrue(owner.status()['busy'])
        release.set();thread.join(5);self.assertFalse(thread.is_alive());self.assertTrue(done.is_set())

    def test_success_waits_for_closure_and_original_needs_no_retirement_step(self):
        owner=self.candidate();original=owner.preparation._runtime.side_effect
        entered=Event();release=Event();published=Event();errors=[]
        def make():
            value=original();close=value.close
            def delayed():
                entered.set()
                if not release.is_set():raise ClosureError(value)
                close()
            value.close=delayed
            return value
        owner.preparation._runtime.side_effect=make
        def work():
            try:
                owner.calculate('custom',self.options(),None,None)
                published.set()
            except BaseException as error:errors.append(error)
        thread=Thread(target=work);thread.start()
        try:
            self.assertTrue(entered.wait(30));self.assertFalse(published.is_set())
            self.assertTrue(owner.status()['busy'])
        finally:release.set();thread.join(10)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertTrue(published.is_set());self.assertIsNone(owner.runtime)
        self.assert_closed(owner.created[-1])
        ordinary=Original()
        def writable():
            db=sqlite3.connect(self.fixture.fixture.path)
            db.row_factory=sqlite3.Row
            return db
        with patch.object(cache_access,'workspace',self.fixture.owner), patch.object(daily,'connect',side_effect=writable):
            result=ordinary.calculate('custom',self.options(),None,None)
        self.assertTrue(compare_results(self.fixture.s.backtest(self.fixture.db,**self.options()),result)['exact'])
        # An unusable experimental preparation must not gate Original.
        owner.preparation.status.return_value=dict(state='unavailable')
        with self.assertRaises(Unavailable):
            owner.calculate('custom',self.options(),None,None)
        with patch.object(cache_access,'workspace',self.fixture.owner), patch.object(daily,'connect',side_effect=writable):
            self.assertEqual(ordinary.calculate('custom',self.options(),None,None)['periods'],result['periods'])

    def test_unsupported_filter_rejected_before_readiness_runtime_or_replay(self):
        # Simulate a future unsupported catalog; all current fields are supported.
        context=patch('backtest.engines.numerical.policy.UNSUPPORTED_THRESHOLDS',frozenset({'future_threshold'}))
        context.start();self.addCleanup(context.stop)
        owner=self.candidate();owner.preparation.status.side_effect=AssertionError('No preparation')
        options=self.options(filters=[dict(field='future_threshold',op='gt',value=5.)])
        for mode in ('custom','random'):
            for bounded in (False,True):
                with self.assertRaisesRegex(ValueError,'experimental does not support filter future_threshold'):
                    if bounded:owner.calculate_into(mode,options,None,None,None)
                    else:owner.calculate(mode,options,None,None)
        with self.assertRaisesRegex(ValueError,'experimental does not support'):
            owner.calculate('random',self.options(),None,None,planned=dict(options=options))
        owner.preparation._runtime.assert_not_called()
        self.assertIsNone(owner.runtime)

    def test_callback_failure_and_stop_close_before_application_outcome(self):
        owner=self.candidate()
        def fail(value):raise RuntimeError('fictional callback')
        with self.assertRaisesRegex(RuntimeError,'fictional callback'):
            owner.calculate('random',self.options(trials=2,seed=1),None,fail)
        self.assertIsNone(owner.runtime)
        owner.close()
        with self.assertRaises(backtest_control.Cancelled):owner.calculate('custom',self.options(),None,None)

    def test_data_check_and_partial_mutation_retire_before_financial_access(self):
        owner=self.candidate();owner.calculate('custom',self.options(),None,None)
        runtime=owner.created[-1];jobs=data_manager.Jobs(preparation=owner.preparation);jobs.calculations=owner
        o=data_manager.options({})
        def inspect(*a):
            self.assert_closed(runtime)
            self.assertIsNone(owner.runtime)
            return dict(warnings=[])
        with patch.object(cache_access,'workspace',self.fixture.owner),patch.object(data_manager,'inspect',side_effect=inspect):
            jobs.work('check',o)
        self.assertIsNone(jobs.snapshot()['job']['error'])
        owner.calculate('custom',self.options(),None,None)
        with patch.object(cache_access,'workspace',self.fixture.owner),patch.object(data_manager,'download',side_effect=ValueError('partial')):
            jobs.work('download',o)
        owner.preparation.invalidate.assert_called_once()
        self.assertIsNone(owner.runtime)

    def test_jobs_queue_and_saved_snapshots(self):
        owner=self.candidate();options=self.options()
        jobs=backtest_jobs.Jobs(owner);jobs.start('a'*32,'custom',options)
        jobs.runs['a'*32]['thread'].join(30)
        self.assertEqual(jobs.snapshot('a'*32)['state'],'complete');jobs.close()
        store=backtest_queue.Store(self.root/'queue.sqlite')
        record=store.enqueue(request(options=options))
        queue=backtest_queue.Queue(store,calculations=owner,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')))
        queue._run(store.claim())
        self.assertEqual(store.get(record['id'])['state'],'complete')

    def test_prepare_and_cancelled_data_admission_do_not_overlap_child(self):
        owner=self.candidate();owner.calculate('custom',self.options(),None,None)
        old=owner.created[-1];jobs=data_manager.Jobs(preparation=owner.preparation);jobs.calculations=owner
        def prepare(**kw):
            self.assert_closed(old)
            self.assertIsNone(owner.runtime)
            self.assertTrue(owner.status()['busy'])
        owner.preparation.prepare.side_effect=prepare
        with patch.object(cache_access,'workspace',self.fixture.owner),patch.object(data_manager,'inspect',return_value=dict(warnings=[])):
            jobs.work('prepare',data_manager.options({}))
        self.assertTrue(jobs.rebuilt)
        jobs.cancel.set()
        owner.preparation.prepare.reset_mock()
        jobs.work('prepare',data_manager.options({}))
        owner.preparation.prepare.assert_not_called()

    def test_active_job_stop_and_shutdown_confirm_child_retirement(self):
        for shutdown in (False,True):
            owner=self.candidate(session_options=dict(fault='cancel'))
            jobs=backtest_jobs.Jobs(owner);identifier=('b' if shutdown else 'c')*32
            jobs.start(identifier,'custom',self.options())
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                runtime=owner.runtime
                marker=runtime.scratch/'fixture-state.json' if runtime is not None else None
                try:
                    state=json.loads(marker.read_bytes()) if marker is not None else {}
                except (FileNotFoundError,PermissionError):
                    # Native marker replacement can briefly deny this observer.
                    # Retry within the same deadline; malformed JSON still fails.
                    state={}
                if state.get('running'):break
                time.sleep(.02)
            else:self.fail('Numerical job did not reach calculation')
            if shutdown:owner.close()
            else:jobs.cancel(identifier)
            jobs.close()
            self.assertEqual(jobs.snapshot(identifier)['state'],'cancelled')
            self.assert_closed(runtime);self.assertIsNone(owner.runtime)

    def test_calculation_uncertain_cleanup_restores_cancel_and_callback_outcomes(self):
        for primary in (backtest_control.Cancelled(),RuntimeError('callback failed')):
            owner=self.candidate();owner.calculate('custom',self.options(),None,None)
            runtime=owner.preparation._runtime();owner.runtime=runtime;runtime.start()
            close=runtime.close;attempts=[]
            def retry_close():
                attempts.append(True)
                if len(attempts)==1:raise ClosureError(runtime)
                close()
            runtime.close=retry_close
            with patch.object(runtime,'calculate',side_effect=ClosureError(runtime,primary)):
                with self.assertRaises(type(primary)) as caught:
                    owner.calculate('custom',self.options(),None,None)
            self.assertIs(caught.exception,primary);self.assert_closed(runtime)
            self.assertIsNone(owner.runtime);self.assertEqual(len(attempts),2)
        owner=self.candidate();owner.calculate('custom',self.options(),None,None)
        runtime=owner.preparation._runtime();owner.runtime=runtime;runtime.start()
        store=backtest_queue.Store(self.root/'shutdown-queue.sqlite')
        item=store.enqueue(request(options=self.options()))
        queue=backtest_queue.Queue(store,calculations=owner,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')))
        def interrupted(*args,**kw):
            queue.request_stop()
            raise ClosureError(runtime,backtest_control.Cancelled())
        with patch.object(runtime,'calculate',side_effect=interrupted):queue._run(store.claim())
        self.assertEqual(store.get(item['id'])['state'],'queued')
        self.assert_closed(runtime)

    def test_cross_process_contention_cancel_and_recovery(self):
        first=self.candidate()
        first.runtime=first.preparation._runtime();first.runtime.start()
        second=self.candidate();stop=Event();errors=[]
        def work():
            try:
                with backtest_control.cancel_when(stop.is_set):second.calculate('custom',self.options(),None,None,admission='queue')
            except BaseException as e:errors.append(e)
        thread=Thread(target=work);thread.start();time.sleep(.4);stop.set();thread.join(10)
        self.assertFalse(thread.is_alive());self.assertIsInstance(errors[0],backtest_control.Cancelled)
        first.retire();second.calculate('custom',self.options(),None,None)
        second.retire()


class UnavailableMappingTests(unittest.TestCase):
    def owner(self, primary, *, delayed=False):
        from backtest.engines.numerical.runtime import InputsUnavailable
        runtime=Mock(configuration={},state='ready')
        runtime.calculate.side_effect=ClosureError(runtime,primary) if delayed else primary
        if delayed:runtime.close.side_effect=[ClosureError(runtime),None]
        preparation=Mock()
        preparation.status.return_value={'state':'current'}
        preparation._runtime.return_value=runtime
        owner=Candidate(preparation)
        self.addCleanup(owner.retire)
        return owner,runtime

    def test_direct_and_delayed_unavailable_map_after_confirmed_retirement(self):
        from backtest.engines.numerical.runtime import InputsUnavailable
        for delayed in (False,True):
            with self.subTest(delayed=delayed):
                owner,runtime=self.owner(InputsUnavailable('Private fixture inputs changed.'),delayed=delayed)
                with self.assertRaises(Unavailable):
                    owner.calculate('custom',{},None,None)
                self.assertIsNone(owner.runtime)
                self.assertEqual(runtime.close.call_count,2 if delayed else 1)
                self.assertEqual(runtime.calculate.call_count,1)

    def test_other_restored_primary_preserves_exception_identity(self):
        primary=RuntimeError('Private fixture failure.')
        owner,runtime=self.owner(primary,delayed=True)
        with self.assertRaises(RuntimeError) as failure:owner.calculate('custom',{},None,None)
        self.assertIs(failure.exception,primary)
        self.assertIsNone(owner.runtime)
        self.assertEqual(runtime.close.call_count,2)

    def test_delayed_unavailable_keeps_original_queue_settings_waiting(self):
        from backtest.engines.numerical.runtime import InputsUnavailable
        import tempfile
        owner,runtime=self.owner(InputsUnavailable('Private fixture inputs changed.'),delayed=True)
        with tempfile.TemporaryDirectory() as folder:
            store=backtest_queue.Store(Path(folder)/'queue.sqlite')
            submitted=request('Retain original settings')
            submitted['options']['engine']='experimental'
            original=json.loads(json.dumps(submitted['options']))
            item=store.enqueue(submitted)
            job=store.claim()
            queue=backtest_queue.Queue(store,calculations=owner,library=Mock())
            queue._run(job)
            record=store.get(item['id'])
            self.assertEqual(record['state'],'queued')
            self.assertEqual(record['options'],original)
            self.assertIsNone(record['error'])
            self.assertIsNone(owner.runtime)
            self.assertEqual(runtime.close.call_count,2)


if __name__=='__main__':unittest.main()

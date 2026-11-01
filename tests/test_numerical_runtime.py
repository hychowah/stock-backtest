"""Explicit persistent runtime proof on disposable synthetic inputs only."""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from copy import deepcopy
from datetime import date
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sqlite3
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).absolute().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tools'),str(ROOT/'website')]
import test_numerical_generation as generations
import numerical_runtime as runtime
from numerical_portfolio import compare_results
import backtest_control
import cache_access
import robustness


class InputProtocolTests(unittest.TestCase):
    def receiver(self, parts):
        parts=list(parts)
        def receive(maximum):
            if not parts:return b''
            part=parts.pop(0)
            if part is None:return None
            if len(part)>maximum:parts.insert(0,part[maximum:]);part=part[:maximum]
            return part
        return receive

    def test_raw_frames_keep_go_read_ahead_crlf_and_fragmented_utf8(self):
        from numerical_runtime_child import _framed_lines
        command=json.dumps(dict(command='cancel',label='測試'),ensure_ascii=False).encode('utf-8')
        polls=[]
        lines=_framed_lines(self.receiver([None,b'GO\r\n'+command+b'\r\n']),pause=lambda:polls.append(True))
        self.assertEqual(next(lines),'GO\n')
        self.assertEqual(json.loads(next(lines)),dict(command='cancel',label='測試'))
        self.assertEqual(list(lines),[]);self.assertEqual(polls,[True])
        fragmented=_framed_lines(self.receiver([bytes([byte]) for byte in command+b'\r\n']))
        self.assertEqual(json.loads(next(fragmented)),dict(command='cancel',label='測試'))
        self.assertEqual(list(fragmented),[])

    def test_raw_frames_reject_truncated_invalid_and_oversized_protocol(self):
        from numerical_runtime_child import _framed_lines
        for parts,message in (([b'{"a":'], 'inside a frame'),([b'x'*8+b'\n'],'byte bound')):
            with self.assertRaisesRegex(ValueError,message):
                list(_framed_lines(self.receiver(parts),frame_bytes=8))
        with self.assertRaises(UnicodeDecodeError):list(_framed_lines(self.receiver([b'\xff\n'])))
        self.assertEqual(list(_framed_lines(self.receiver([b'1234567\n']),frame_bytes=8)),['1234567\n'])

    @unittest.skipUnless(os.name=='nt','Requires the actual Windows CRT and NumPy/Numba extension loader.')
    def test_native_import_with_live_polling_stdin_reader(self):
        # Actual source-owned, contained cold import. The old blocked text reader
        # hung in NumPy's extension create_module under the same native owner.
        code = ("import sys,os,json,time\nfrom pathlib import Path\nfrom threading import Thread,Event\n"
            +"root=Path("+repr(str(ROOT))+");sys.path[:0]=[str(root/'website'),str(root/'scripts')]\n"
            +"import runtime_access\nsource=runtime_access.ownership(root);source.__enter__()\n"
            +"from numerical_runtime_child import _stdin_lines\nlines=_stdin_lines();assert next(lines)=='GO\\n'\n"
            +"stopped=Event()\ndef controls():\n for line in lines:\n  if json.loads(line).get('command')=='close':stopped.set();return\n"
            +"Thread(target=controls,daemon=True).start()\nimport numpy,numba\n"
            +"print(json.dumps(dict(event='ready',numpy=numpy.__version__,numba=numba.__version__)),flush=True)\n"
            +"assert stopped.wait(10)\nos._exit(0)\n")
        env=dict(os.environ,NUMBA_NUM_THREADS='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
        owner=runtime.RuntimeProcess([sys.executable,'-I','-B','-c',code],env=env,close_seconds=2.)
        began=time.monotonic();ready=None
        try:
            owner.start();deadline=began+20
            while time.monotonic()<deadline:
                event=owner.event(.05)
                if event is None:self.fail('Cold-import child exited before readiness')
                if event.get('event')=='failed':self.fail('Cold-import transport failed')
                if event.get('event')=='ready':ready=event;break
            self.assertIsNotNone(ready,'Cold native import blocked with its polling reader alive')
            owner.process.stdin.write('{"command":"close"}\n');owner.process.stdin.flush()
        finally:owner.close()
        self.assertTrue(owner.closed);self.assertTrue(owner.descendants_empty);self.assertTrue(owner.eof)
        print(json.dumps(dict(check='native-import-polling-reader',seconds=time.monotonic()-began,
                              versions=ready,closure=owner.closure())),flush=True)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=generations.GenerationTests('test_export_values_order_missingness_and_mutable_books_reuse')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare()
        self.root=self.fixture.root
        (self.root/'binding.json').write_text(json.dumps(self.fixture.binding))
        self.counter=0

    def make(self,threads=1,**options):
        self.counter+=1
        session_options=options.pop('session_options',{})
        result=runtime.NumericalRuntime(source_root=ROOT,scratch=self.root/('runtime-'+str(self.counter)),
            generation_path=self.fixture.store.path,checkpoint_path=self.root/'trials.sqlite',threads=threads,
            python=sys.executable,session_factory='numerical_runtime_fixture:Session',
            coordinator=self.fixture.owner,session_options=session_options,**options)
        self.addCleanup(result.close)
        return result

    def options(self,**overrides):
        return dict(start='2015-01-02',end='2016-12-30',months=12,pool='cached',
                    min_cap=0.,min_ev=0.,rank_to=5,**overrides)

    def test_statistics_failure_never_publishes_completion_and_owner_closes(self):
        value=self.make(session_options={'fault':'stats-publication'})
        with self.assertRaisesRegex(ValueError,'PermissionError'):
            value.calculate('custom',self.options())
        self.assert_closed(value)
        self.assertEqual(json.loads((value.scratch/'payload.json').read_bytes())['periods'][0]['entry'],'2015-01-02')
        self.assertTrue((value.scratch/'stats.pending').is_file())
        failure=[event for event in value.diagnostics if event.get('stage')=='publication-failed']
        self.assertTrue(failure)
        self.assertEqual(failure[-1]['role'],'statistics');self.assertEqual(failure[-1]['phase'],'replace')
        self.assertEqual(failure[-1]['winerror'],32)

    def test_selected_provider_construction_counter_has_a_positive_fresh_control(self):
        value=self.make();value.start()
        self.assertEqual(value.last_stats['provider_builds'],0)
        self.assertEqual(value.last_stats['provider_constructions'],0)
        self.assertEqual(value.last_stats['factor_kernel_compilation_requests'],0)
        value.calculate('custom',self.options())
        self.assertEqual(value.last_stats['provider_builds'],1)
        self.assertEqual(value.last_stats['provider_constructions'],1)
        self.assertEqual(value.last_stats['provider_compilations'],1)
        self.assertEqual(value.last_stats['factor_kernel_compilation_requests'],1)
        value.close();self.assert_closed(value)

    def assert_closed(self,value):
        closure=value.closure()
        self.assertEqual(closure['state'],'closed')
        state=closure['process']
        if state is not None:
            for key in ('closed','eof','reader_stopped','streams_closed','descendants_empty','native_handles_released'):
                self.assertTrue(state[key],state)
            self.assertIsNotNone(state['leader_exit'])
        marker=value.scratch/'fixture-state.json'
        if marker.exists():
            observed=json.loads(marker.read_bytes())
            if observed.get('closed'):
                self.assertTrue(observed['sql_closed'],observed)
                self.assertTrue(observed['workspace_sql_closed'],observed)

    def test_serial_parallel_complete_results_random_capture_recovery_and_fresh_seeds(self):
        observed=[]
        for threads in (1,min(2,os.cpu_count() or 1)):
            with self.make(threads) as value:
                for pool in ('legacy','cached'):
                    options=self.options();options['pool']=pool
                    for metric in self.fixture.s.metrics.METRICS:
                        options['metric']=metric
                        expected=self.fixture.s.backtest(self.fixture.db,**options)
                        actual=value.calculate('custom',options)
                        self.assertTrue(compare_results(expected,actual)['exact'])
                options=self.options(trials=3,seed=42)
                plan=robustness.plan(self.fixture.db,**options)
                captures=[];configurations=[];events=[]
                result=value.calculate('random',options,events.append,configurations.append,planned=plan,
                    capture=lambda n,r:captures.append((n,r)))
                self.assertEqual(configurations,[plan]);self.assertEqual([n for n,r in captures],[1,2,3])
                self.assertEqual(result['trial_results'],[r for n,r in captures])
                references=[];ordinary=robustness.run(self.fixture.db,plan,capture=lambda n,r:references.append(r))
                self.assertEqual(ordinary['distributions'],result['distributions'])
                for a,b in zip(references,result['trial_results']):self.assertTrue(compare_results(a,b)['exact'])
                books=value.last_stats['provider']['books']
                replay=value.calculate('random',options,planned=plan)
                self.assertEqual(result['trial_results'],replay['trial_results'])
                self.assertEqual(replay['execution']['recovered_trials'],3)
                self.assertEqual(value.last_stats['provider']['books'],books)
                seeds=[]
                for _ in range(2):
                    fresh=self.options(trials=1)
                    value.calculate('random',fresh,configuration=lambda c:seeds.append(c['seed']))
                self.assertNotEqual(*seeds)
                observed.append(dict(threads=threads,stats=value.last_stats))
            self.assert_closed(value)
        print(json.dumps(dict(check='persistent-serial-parallel',observations=observed)),flush=True)

    def test_actual_matrix_reuse_filter_changes_retention_eviction_and_thread_stability(self):
        value=self.make(session_options=dict(result_cache_bytes=0,matrix_cache_bytes=32*1024))
        samples=[];tree_samples=[];file_samples=[]
        with value:
            for threshold in range(32):
                options=self.options(filters=[dict(field='pe',op='lt',value=float(10+threshold))])
                result=value.calculate('custom',options)
                self.assertTrue(compare_results(self.fixture.s.backtest(self.fixture.db,**options),result)['exact'])
                samples.append(deepcopy(value.last_stats))
                tree_samples.append(value.owner.tree_usage())
                file_samples.append(sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()))
            self.assertGreater(samples[-1]['matrix']['hits'],samples[0]['matrix']['hits'])
            self.assertLessEqual(samples[-1]['matrix']['retained_bytes'],32*1024)
            self.assertEqual(samples[-1]['result_retained_bytes'],0)
            if 'sampled_threads' in samples[-1]:
                self.assertEqual(samples[0]['sampled_threads'],samples[-1]['sampled_threads'])
            self.assertLessEqual(len(value.diagnostics),128)
        self.assert_closed(value)
        print(json.dumps(dict(check='repeated-filter-memory',first=samples[0],last=samples[-1],
            tree_samples=tree_samples,logical_file_bytes=file_samples,
            mapped_residency='not measured separately')),flush=True)

    def test_random_application_uses_two_workers_and_fresh_full_hit_starts_none(self):
        options=self.options(trials=3,seed=191)
        plan=robustness.plan(self.fixture.db,**options)
        settings=dict(execution=dict(workers=2,threads_per_worker=1))
        with self.make(session_options=settings) as value:
            result=value.calculate('random',options,planned=plan)
            self.assertEqual(result['execution']['workers'],2)
            self.assertEqual(value.last_stats['trial_pool']['started_workers'],2)
            self.assertEqual(value.last_stats['provider_builds'],0)
            for actual,dates in zip(result['trial_results'],plan['samples']):
                expected=self.fixture.s.backtest_dates(self.fixture.db,dates=dates,
                    **{key:options[key] for key in ('start','end','months')},**plan['options'])
                self.assertTrue(compare_results(expected,actual)['exact'])
        self.assert_closed(value)
        with self.make(session_options=settings) as recovered:
            replay=recovered.calculate('random',options,planned=plan)
            self.assertEqual(replay['trial_results'],result['trial_results'])
            self.assertEqual(replay['execution']['recovered_trials'],3)
            self.assertEqual(replay['execution']['workers'],0)
            self.assertIsNone(recovered.last_stats['trial_pool'])
            self.assertEqual(recovered.last_stats['provider_builds'],0)
            self.assertEqual(recovered.last_stats['provider_constructions'],0)
            self.assertEqual(recovered.last_stats['factor_kernel_compilation_requests'],0)
        self.assert_closed(recovered)

    def test_result_graph_and_ipc_budgets_reject_before_unbounded_accumulation(self):
        for mode,options in (('custom',self.options()),('random',self.options(trials=3,seed=1))):
            value=self.make(session_options=dict(result_workspace_bytes=1024))
            with self.assertRaisesRegex(ValueError,'result workspace bound'):
                value.calculate(mode,options)
            self.assert_closed(value)
        with self.assertRaisesRegex(ValueError,'IPC payload'):
            runtime.encoded({'x':'fictional'},3)

    def test_declared_weekly_pilot_fresh_complete_results_and_file_growth(self):
        # CB-14.gates.md declares these safety limits before execution. They are
        # fixture limits, not user acceptance budgets or full-window capacity.
        from backtest import calendar_requests as numerical_calendar
        value=self.make(threads=2,session_options=dict(result_cache_bytes=0))
        def logical():
            # Pool files publish and retire while this observer samples. A
            # vanished entry contributes no bytes to the completed observation.
            size=0
            for path in self.root.rglob('*'):
                try:
                    if path.is_file():size+=path.stat().st_size
                except FileNotFoundError:pass
            return size
        before=logical();sizes=[];tree_samples=[]
        with value:
            options=dict(calendar=dict(version=1,start='2015-01-02',end='2016-12-30',
                interval=dict(unit='week',count=1)),trials=24,seed=42,pool='cached',
                rank_to=5,min_cap=0.,min_ev=0.,metric='ev_ebitda',
                filters=[dict(field=n,op='gt',value=0.) for n in ('return_1y','return_3y')])
            sessions=[date.fromisoformat(row[0]) for row in self.fixture.db.execute('SELECT day FROM sessions ORDER BY day')]
            plan=numerical_calendar.plan(sessions,options)
            started=time.monotonic()
            result=value.calculate('random',options,planned=plan,
                capture=lambda n,r:(sizes.append(logical()),tree_samples.append(value.owner.tree_usage())),
                cancelled=lambda:time.monotonic()-started>180 or logical()>512*1024**2)
            seconds=time.monotonic()-started;stats=deepcopy(value.last_stats)
            self.assertEqual((result['completed'],result['valid'],result['execution']['recovered_trials']),(24,24,0))
            self.assertEqual(len(result['trial_results']),24)
            maximum_absolute=maximum_relative=0.
            for dates,actual in zip(plan['samples'],result['trial_results'],strict=True):
                expected=self.fixture.s.backtest_dates(self.fixture.db,dates=dates,
                    start=options['calendar']['start'],end=options['calendar']['end'],months=12,**plan['options'])
                expected.pop('months');expected['calendar']=options['calendar']
                agreement=compare_results(expected,actual);self.assertTrue(agreement['exact'],agreement)
                maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                maximum_relative=max(maximum_relative,agreement['maximum_relative'])
            self.assertLess(seconds,180);self.assertLess(max([logical(),*sizes]),512*1024**2)
        self.assert_closed(value)
        print(json.dumps(dict(check='declared-weekly-pilot',configuration=plan,seconds=seconds,
            boundary='ready resident request through full result transport; setup separate; no HTTP/browser',
            before_logical_bytes=before,after_logical_bytes=logical(),peak_observed_logical_bytes=max([logical(),*sizes]),
            tree_samples=tree_samples,mapped_residency='not measured separately',
            maximum_absolute=maximum_absolute,maximum_relative=maximum_relative,stats=stats,
            closure=value.closure())),flush=True)

    def test_current_input_validation_before_result_or_checkpoint_reuse(self):
        value=self.make()
        value.calculate('random',self.options(trials=1,seed=1))
        changed=deepcopy(self.fixture.binding);changed['prices']={'revision':1}
        (self.root/'binding.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'stale'):
            value.calculate('random',self.options(trials=1,seed=1))
        self.assert_closed(value)

    def test_new_generation_requires_new_child_without_a_second_jit_or_stale_checkpoint(self):
        options=self.options(trials=2,seed=19)
        plan=robustness.plan(self.fixture.db,**options)
        value=self.make();old_result=value.calculate('random',options,planned=plan)
        old=value.last_stats['generation'];old_pid=value.last_stats['pid']
        self.assertEqual(value.last_stats['attached_generations'],1)
        self.assertEqual(value.last_stats['provider_builds'],0)
        # Only this disposable fixture changes a pointer outside the held
        # coordinator. Ordinary coordinated publication waits for runtime exit.
        with patch.object(self.fixture.store,'coordinator',cache_access.WorkspaceAccess(self.root/'fixture-publication.lock')):
            self.fixture.advance()
        (self.root/'binding.json').write_text(json.dumps(self.fixture.binding))
        with self.assertRaisesRegex(ValueError,'generation changed'):
            value.calculate('random',options,planned=plan)
        self.assert_closed(value)
        closed=json.loads((value.scratch/'fixture-state.json').read_text())
        self.assertEqual(closed['provider_builds'],0,'A changed pointer must not construct another JIT provider')
        for field in ('closed','portfolio_closed','provider_closed','mappings_closed','record_db_closed','sql_closed','checkpoint_db_closed'):
            self.assertTrue(closed[field],closed)
        self.assertFalse(self.fixture.store._busy(old))
        # Renaming a former records database verifies its native handle release.
        records=self.fixture.store.path/old/'records.sqlite';renamed=records.with_suffix('.released')
        records.rename(renamed);renamed.rename(records)
        with self.make() as fresh:
            new_result=fresh.calculate('random',options,planned=plan)
            self.assertNotEqual(fresh.last_stats['generation'],old)
            self.assertNotEqual(fresh.last_stats['pid'],old_pid)
            self.assertEqual(fresh.last_stats['attached_generations'],1)
            self.assertEqual(fresh.last_stats['provider_builds'],0)
            self.assertEqual(new_result['execution']['recovered_trials'],0)
            self.assertEqual(new_result['execution']['calculated_trials'],2)
            new_generation=fresh.last_stats['generation']
        self.assert_closed(fresh)
        self.assertTrue(any(not compare_results(a,b)['exact'] for a,b in
                            zip(old_result['trial_results'],new_result['trial_results'])))
        expected=[];ordinary=robustness.run(self.fixture.db,plan,capture=lambda n,r:expected.append(r))
        self.assertEqual(ordinary['distributions'],new_result['distributions'])
        for a,b in zip(expected,new_result['trial_results']):self.assertTrue(compare_results(a,b)['exact'])
        with closing(sqlite3.connect(self.root/'trials.sqlite')) as db:
            bindings=[json.loads(row[0]) for row in db.execute('SELECT binding FROM experiments')]
        self.assertEqual({binding['generation'] for binding in bindings},{old,new_generation})
        print(json.dumps(dict(check='one-generation-per-process',old_pid=old_pid,new_generation=new_generation,
            old_generation=old,old_provider_builds=closed['provider_builds'],old_resources=closed,
            fresh_recovered_trials=new_result['execution']['recovered_trials'])),flush=True)

    def test_admission_no_calling_thread_lock_and_no_backlog(self):
        value=self.make()
        with self.fixture.owner.hold():
            with self.assertRaisesRegex(ValueError,'financial ownership'):value.start()
        value.start()
        self.assertTrue(value._call.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(ValueError,'active call'):value.calculate('custom',self.options())
        finally:value._call.release()
        value.close()
        with self.assertRaisesRegex(ValueError,'stopping or closed'):value.calculate('custom',self.options())
        self.assert_closed(value)

    def test_callback_failure_cancels_drains_closes_and_preserves_committed_trial(self):
        value=self.make()
        def broken(event):
            if event['completed']==1:raise LookupError('fictional observer failure')
        with self.assertRaisesRegex(LookupError,'observer'):
            value.calculate('random',self.options(trials=3,seed=7),progress=broken)
        self.assert_closed(value)
        with self.make() as recovered:
            result=recovered.calculate('random',self.options(trials=3,seed=7))
            self.assertGreaterEqual(result['execution']['recovered_trials'],1)

    def test_cooperative_cancel_and_stuck_native_force_exit_release(self):
        for fault in ('cancel','stuck'):
            value=self.make(session_options=dict(fault=fault),close_seconds=.5)
            value.start()
            marker=value.scratch/'fixture-state.json'
            began=time.monotonic()
            with self.assertRaises(backtest_control.Cancelled) as outcome:
                value.calculate('custom',self.options(),cancelled=lambda: 'running' in json.loads(marker.read_text()))
            self.assert_closed(value)
            if fault=='stuck':self.assertTrue(any(isinstance(error,TimeoutError) for error in outcome.exception.runtime_secondary_errors))
            self.assertLess(time.monotonic()-began,3.)
            with self.fixture.owner.hold(timeout=0):pass

    def test_start_close_serializes_paused_constructor_and_retains_timeout_owner(self):
        actual=runtime.RuntimeProcess
        for timeout in (False,True):
            value=self.make(close_seconds=.2 if timeout else 2.)
            entered,release=Event(),Event();owners=[];start_errors=[];close_errors=[]
            def constructor(*args,**kwargs):
                owner=actual(*args,**kwargs);owners.append(owner);entered.set()
                if not release.wait(5):raise AssertionError('Paused constructor fixture timed out')
                return owner
            def start():
                try:value.start()
                except BaseException as error:start_errors.append(error)
            def close():
                try:value.close()
                except BaseException as error:close_errors.append(error)
            with patch('numerical_runtime.RuntimeProcess',side_effect=constructor):
                starter=Thread(target=start);starter.start()
                try:
                    self.assertTrue(entered.wait(5));self.assertIsNone(value.owner)
                    closer=Thread(target=close);closer.start()
                    self.assertTrue(value._stop.wait(2))
                    self.assertNotEqual(value.state,'closed')
                    if timeout:
                        closer.join(2);self.assertFalse(closer.is_alive())
                        self.assertIsInstance(close_errors[0],runtime.ClosureError)
                        self.assertEqual(value.state,'failed-closure')
                        self.assertIs(runtime._PENDING[id(value)],value)
                        self.assertFalse(owners[0].closed)
                    else:self.assertTrue(closer.is_alive())
                finally:release.set()
                starter.join(5);closer.join(5)
            self.assertFalse(starter.is_alive());self.assertFalse(closer.is_alive())
            self.assertIsInstance(start_errors[0],backtest_control.Cancelled)
            if not timeout:self.assertEqual(close_errors,[])
            self.assertIs(value.owner,owners[0]);self.assert_closed(value)
            self.assertNotIn(id(value),runtime._PENDING)
            self.assertFalse(value._go_sent,'A stopped constructor must not publish GO or readiness')

    def test_forced_callback_cleanup_preserves_original_exception(self):
        value=self.make(session_options=dict(fault='callback-stuck'),close_seconds=.2)
        original=LookupError('fictional original observer error')
        def broken(event):raise original
        with self.assertRaises(LookupError) as raised:
            value.calculate('custom',self.options(),progress=broken)
        self.assertIs(raised.exception,original);self.assert_closed(value)
        self.assertTrue(any(isinstance(error,TimeoutError) for error in original.runtime_secondary_errors))

    def test_transport_failure_preserves_observed_cancel_and_callback_error(self):
        value=self.make(session_options=dict(fault='stuck'),close_seconds=.2);value.start()
        marker=value.scratch/'fixture-state.json';observed=[];normal_event=value._event
        def cancelled():
            ready=json.loads(marker.read_text()).get('running',False)
            if ready:observed.append(True)
            return ready
        def event():
            if observed:raise RuntimeError('fictional transport failure')
            return normal_event()
        with patch.object(value,'_event',side_effect=event):
            with self.assertRaises(backtest_control.Cancelled) as raised:
                value.calculate('custom',self.options(),cancelled=cancelled)
        self.assert_closed(value)
        self.assertTrue(any(isinstance(error,RuntimeError) for error in raised.exception.runtime_secondary_errors))
        callback=self.make();callback.start();send=callback._send;original=LookupError('fictional original callback')
        callback_observed=[]
        def broken(event):
            callback_observed.append(True);raise original
        def broken_ack(event):
            if event.get('command')=='ack' and callback_observed:raise BrokenPipeError('fictional broken acknowledgement pipe')
            return send(event)
        with patch.object(callback,'_send',side_effect=broken_ack):
            with self.assertRaises(LookupError) as outcome:
                callback.calculate('random',self.options(trials=1,seed=1),progress=broken)
        self.assertIs(outcome.exception,original);self.assert_closed(callback)
        self.assertIsInstance(original.runtime_secondary_errors[0],BrokenPipeError)

    def test_stalled_callback_close_stays_uncertain_until_caller_drains(self):
        for broken in (False,True):self._stalled_callback_case(broken)

    def _stalled_callback_case(self,broken):
        value=self.make(close_seconds=.2);value.start()
        entered,release=Event(),Event();errors=[];original=LookupError('fictional stalled observer')
        def callback(event):
            entered.set();release.wait(5)
            if broken:raise original
        def calculate():
            try:value.calculate('random',self.options(trials=1,seed=3),progress=callback)
            except BaseException as error:errors.append(error)
        worker=Thread(target=calculate);worker.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(runtime.ClosureError):value.close()
            self.assertEqual(value.state,'failed-closure');self.assertIs(runtime._PENDING[id(value)],value)
            self.assertTrue(worker.is_alive())
        finally:release.set()
        worker.join(5);self.assertFalse(worker.is_alive())
        if broken:self.assertEqual(errors,[original])
        else:
            self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],backtest_control.Cancelled)
        self.assert_closed(value)

    def test_startup_transport_failure_after_stop_preserves_cancellation(self):
        value=self.make(session_options=dict(fault='startup-cancel'),close_seconds=.2)
        receive=value._event
        def stopped_transport():
            event=receive()
            if event.get('stage')=='session-construct-prewarm':
                value._stop.set()
                raise RuntimeError('fictional startup transport failure')
            return event
        with patch.object(value,'_event',side_effect=stopped_transport):
            with self.assertRaises(backtest_control.Cancelled) as outcome:value.start()
        self.assert_closed(value)
        self.assertIsInstance(outcome.exception.runtime_secondary_errors[0],RuntimeError)

    def test_uncertain_cleanup_does_not_publish_cancelled_outcome(self):
        value=self.make(session_options=dict(fault='cancel'),close_seconds=.2);value.start()
        marker=value.scratch/'fixture-state.json'
        with patch.object(value.owner,'close',side_effect=TimeoutError('fictional unconfirmed cleanup')):
            with self.assertRaises(runtime.ClosureError) as outcome:
                value.calculate('custom',self.options(),cancelled=lambda:json.loads(marker.read_text()).get('running',False))
        self.assertIsInstance(outcome.exception.primary_error,backtest_control.Cancelled)
        self.assertNotIsInstance(outcome.exception,backtest_control.Cancelled)
        self.assertEqual(value.state,'failed-closure');self.assertIs(runtime._PENDING[id(value)],value)
        value.close();self.assert_closed(value)

    def test_partial_close_retry_startup_failure_and_windows_file_release(self):
        failed=self.make(session_options=dict(fault='startup'))
        with self.assertRaisesRegex(ValueError,'initialization failed'):failed.start()
        self.assert_closed(failed)
        value=self.make(session_options=dict(fault='close'))
        value.calculate('custom',self.options());value.close();self.assert_closed(value)
        state=json.loads((value.scratch/'fixture-state.json').read_text())
        self.assertGreaterEqual(state['close_attempts'],3)
        # Rename/delete the actual mapped asset after terminal close. This is a
        # Windows share-handle assertion as well as a POSIX filesystem check.
        path=self.fixture.store.path/value.last_stats['generation']/'raw_values.npy'
        target=path.with_suffix('.released');path.rename(target)
        original=target.read_bytes();target.unlink();path.write_bytes(original)
        for lease in (self.fixture.store.path/'leases').glob('*/*.lease'):
            lease.unlink()
        with self.fixture.owner.hold(timeout=0):pass

    def test_uncertain_owner_close_retained_for_explicit_retry(self):
        value=self.make();value.start()
        close=value.owner.close
        with patch.object(value.owner,'close',side_effect=TimeoutError('fictional unknown closure')):
            with self.assertRaises(TimeoutError):value.close()
        self.assertEqual(value.state,'failed-closure')
        self.assertIs(runtime._PENDING[id(value)],value)
        value.close();self.assert_closed(value)
        self.assertNotIn(id(value),runtime._PENDING)

    def test_owned_descendant_closes_before_release(self):
        value=self.make(session_options=dict(fault='descendant'),close_seconds=.5)
        value.calculate('custom',self.options())
        value.close();self.assert_closed(value)

    @unittest.skipUnless(os.name=='posix','Uses a real POSIX terminal signal; Windows console events require separate qualification.')
    def test_actual_sigint_cancels_child_and_releases_os_ownership(self):
        value=self.make(session_options=dict(fault='cancel'),close_seconds=1.)
        value.start();errors=[]
        thread=Thread(target=lambda:self._calculate_error(value,errors));thread.start()
        marker=value.scratch/'fixture-state.json'
        deadline=time.monotonic()+5
        while not json.loads(marker.read_text()).get('running'):
            if time.monotonic()>deadline:self.fail('Child did not enter calculation')
            time.sleep(.01)
        os.kill(value.last_stats['pid'],signal.SIGINT)
        thread.join(5);self.assertFalse(thread.is_alive())
        self.assertTrue(errors);self.assertIsInstance(errors[0],backtest_control.Cancelled)
        self.assert_closed(value)

    def test_loaded_source_change_rejects_checkpoint_and_result_before_reuse(self):
        private=self.root/'private-source';private.mkdir()
        for folder in ('scripts','website','backtest'):
            shutil.copytree(ROOT/folder,private/folder,ignore=shutil.ignore_patterns('__pycache__','dist','local','*.pyc'))
        (private/'tests').mkdir()
        self.assertFalse((private/'tools').exists())
        shutil.copy2(ROOT/'tests/numerical_runtime_fixture.py',private/'tests/numerical_runtime_fixture.py')
        value=runtime.NumericalRuntime(source_root=private,scratch=self.root/'source-change-runtime',
            generation_path=self.fixture.store.path,checkpoint_path=self.root/'source-change-trials.sqlite',
            python=sys.executable,threads=1,session_factory='numerical_runtime_fixture:Session',coordinator=self.fixture.owner)
        self.addCleanup(value.close)
        value.calculate('random',self.options(trials=1,seed=1))
        path=private/'backtest/financial/metrics.py'
        path.write_bytes(path.read_bytes()+b'\n# Private changed loaded catalog source.\n')
        with self.assertRaisesRegex(ValueError,'Loaded calculation source changed'):
            value.calculate('random',self.options(trials=1,seed=1))
        self.assert_closed(value)

    def test_cold_start_cancellation_and_deadline_close_owned_resources(self):
        value=self.make(session_options=dict(fault='startup-cancel'),close_seconds=1.)
        errors=[]
        def start():
            try:value.start()
            except BaseException as error:errors.append(error)
        thread=Thread(target=start);thread.start()
        marker=value.scratch/'fixture-state.json';deadline=time.monotonic()+10
        while not marker.exists():
            if time.monotonic()>deadline:self.fail('Startup fixture did not enter owned initialization')
            time.sleep(.01)
        value.close();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertTrue(errors);self.assert_closed(value)
        expired=self.make(start_seconds=.001,close_seconds=.2)
        with self.assertRaises(TimeoutError):expired.start()
        self.assert_closed(expired)
        with self.fixture.owner.hold(timeout=0):pass

    def test_explicit_caller_cancellation_applies_during_cold_start(self):
        value=self.make(session_options=dict(fault='startup-cancel'),close_seconds=1.)
        marker=value.scratch/'fixture-state.json'
        began=time.monotonic()
        with self.assertRaises(backtest_control.Cancelled):
            value.calculate('custom',self.options(),cancelled=marker.exists)
        self.assert_closed(value)
        self.assertLess(time.monotonic()-began,4.)

    def test_compiler_identity_binds_execution_policy_catalog_and_source(self):
        value=self.make();value.calculate('custom',self.options())
        identity=value.last_stats['compiler_identity'];fields=identity['fields']
        self.assertEqual(len(identity['signature']),64)
        self.assertEqual(fields['threads'],1)
        self.assertFalse(fields['fastmath']);self.assertFalse(fields['compiler_cache'])
        self.assertIn('scripts/numerical_matrix.py',fields['sources'])
        self.assertIn('scripts/numerical_runtime_child.py',fields['sources'])
        self.assertEqual(set(fields['versions']),{'numpy','numba','llvmlite'})
        self.assertTrue(fields['target']['cpu']);self.assertTrue(fields['catalog'])
        # The persistent recovery binding must retain the same target/compiler
        # identity as actual numerical matrix reuse, including CPU features.
        value.calculate('random',self.options(trials=1,seed=41))
        with closing(sqlite3.connect(self.root/'trials.sqlite')) as check:
            binding=json.loads(check.execute('SELECT binding FROM experiments ORDER BY touched DESC LIMIT 1').fetchone()[0])
        self.assertEqual(binding['execution']['compiler'],identity)
        value.close()
        if (os.cpu_count() or 1)>1:
            parallel=self.make(2);parallel.calculate('custom',self.options())
            self.assertNotEqual(identity['signature'],parallel.last_stats['compiler_identity']['signature'])
            parallel.close()

    def test_parent_exit_closes_idle_and_active_child_without_a_second_owner(self):
        for scenario in ('idle','active','descendant'):
            active=scenario=='active'
            self.counter+=1
            scratch=self.root/('orphan-'+str(self.counter))
            marker=self.root/('parent-'+str(self.counter)+'.json')
            config=dict(source_root=str(ROOT),scratch=str(scratch),generation_path=str(self.fixture.store.path),
                checkpoint_path=str(self.root/'orphan-trials.sqlite'),threads=1,python=sys.executable,
                session_factory='numerical_runtime_fixture:Session',session_options=dict(fault='cancel') if active else dict(fault='descendant') if scenario=='descendant' else {},
                close_seconds=.5)
            code=("import sys,os,json,time\nfrom pathlib import Path\n"
                +"root=Path("+repr(str(ROOT))+");sys.path[:0]=[str(root/'website'),str(root/'scripts')]\n"
                +"import runtime_access\nsource=runtime_access.ownership(root);source.__enter__()\n"
                +"from numerical_runtime import NumericalRuntime\n"
                +"value=NumericalRuntime(**"+repr(config)+");value.start()\n"
                +"Path("+repr(str(marker))+").write_text(json.dumps(value.last_stats))\n")
            if active:
                code += ("from threading import Thread\nThread(target=lambda:value.calculate('custom',"+repr(self.options())+")).start()\n"
                         +"state=value.scratch/'fixture-state.json'\n"
                         +"while not json.loads(state.read_text()).get('running'):time.sleep(.01)\n")
            if scenario=='descendant':
                code += ("value.calculate('custom',"+repr(self.options())+")\n"
                    +"info=json.loads((value.scratch/'fixture-state.json').read_text())\n"
                    +"Path("+repr(str(marker))+").write_text(json.dumps(info))\n")
            code += "os._exit(0)\n"
            parent=subprocess.Popen([sys.executable,'-I','-B','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                output,errors=parent.communicate(timeout=20)
                self.assertEqual(parent.returncode,0,(output,errors))
                recorded=json.loads(marker.read_text());pid=recorded['pid']
                deadline=time.monotonic()+5
                while self._alive(pid):
                    if time.monotonic()>deadline:self.fail('Owned runtime survived parent exit')
                    time.sleep(.02)
                if scenario=='descendant':self.assertFalse(self._alive(recorded['descendant']))
                with self.fixture.owner.hold(timeout=0):pass
            finally:
                if parent.poll() is None:parent.kill();parent.wait()
                parent.stdout.close();parent.stderr.close()

    @staticmethod
    def _alive(pid):
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes as w
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.restype=w.HANDLE
            handle=kernel.OpenProcess(0x100000,False,pid)
            if not handle:return False
            try:return kernel.WaitForSingleObject(w.HANDLE(handle),0)==0x102
            finally:kernel.CloseHandle(w.HANDLE(handle))
        path=Path('/proc')/str(pid)/'stat'
        if not path.exists():return False
        return path.read_text().rsplit(')',1)[1].split()[0]!='Z'

    def _calculate_error(self,value,errors):
        try:value.calculate('custom',self.options())
        except BaseException as error:errors.append(error)


if __name__=='__main__':unittest.main()

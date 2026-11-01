"""Persistent trial lifecycle and full financial parity on fictional assets."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'tests'), str(ROOT/'tools'), str(ROOT/'website')]
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import backtest_control as backtest_control
from backtest.engines.numerical.execution import ExecutionPolicy, effective_lanes, observe_resources
from backtest.engines.numerical import random as numerical_random
from backtest.engines.numerical import trial as numerical_trial
from backtest.engines.numerical import trial_pool as pools
from backtest.engines.numerical.numba import NumbaExecutor
from backtest.engines.numerical.portfolio import NumericalPortfolio, compare_results
import test_numerical_generation as generations
from backtest.engines.original import robustness as robustness
from backtest.engines.numerical import runtime as numerical_runtime
import runtime_access
from backtest.runtime.process_owner import windows_processes


class TrialPoolTests(unittest.TestCase):
    def setUp(self):
        self.fixture = generations.GenerationTests('test_export_values_order_missingness_and_mutable_books_reuse')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare()
        self.inputs = self.fixture.attach()
        self.policy = ExecutionPolicy(dict(workers=2, threads_per_worker=1, close_seconds=.5,
            artifact_bytes=8*1024**2, piece_bytes=127, record_bytes=16384))
        self.provider = NumbaExecutor(self.inputs, limits=self.policy.provider_limits)
        self.addCleanup(self.provider.close)
        self.portfolio = NumericalPortfolio(self.inputs, self.provider)
        self.addCleanup(self.portfolio.close)
        self.count = 0

    def make(self, **overrides):
        self.count += 1
        settings = dict(source_root=ROOT, scratch=self.fixture.root/('pool-'+str(self.count)),
            reference=self.inputs.worker_reference(), source_identity=numerical_random.source_identity(),
            compiler_identity=self.provider.compiler, policy=self.policy)
        settings.update(overrides)
        value = pools.TrialPool(**settings)
        self.addCleanup(value.close)
        return value

    def specifications(self, count=3, **options):
        config = robustness.plan(self.fixture.db, start='2015-01-05', end='2016-12-30',
            trials=count, seed=42, min_cap=0., min_ev=0., rank_to=5, **options)
        binding = numerical_random.checkpoint_binding(self.portfolio, config)
        return [numerical_trial.specification(binding, n) for n in range(1, count+1)]

    def consume(self, pool, specifications):
        result = {}
        with pool.batch(specifications) as batch:
            for completion in batch.completed():
                result[completion.number] = dict(periods=list(completion.artifact.periods()),
                                                **completion.artifact.summary)
                completion.release()
        return result

    def assert_closed(self, pool):
        closure = pool.closure()
        self.assertTrue(closure['closed'], closure)
        for worker in closure['workers']:
            self.assertIsNotNone(worker['exit'])
            for key in ('eof', 'reader_stopped', 'streams_closed'): self.assertTrue(worker[key], closure)
        self.assertNotIn(id(pool), pools._PENDING)
        self.assertFalse(pool.scratch.exists())

    def test_full_parity_reused_workers_mappings_provider_sql_and_no_financial_access(self):
        pool = self.make(); maximum_absolute = maximum_relative = 0.; cases = 0
        # Coordinator holds the actual process-shared lock. Any worker trying
        # ordinary preparation/financial coordination would fail or deadlock.
        with self.fixture.owner.hold():
            for stock_pool in ('legacy', 'cached'):
                for order in ('filter_first', 'rank_first'):
                    for metric in self.fixture.s.metrics.METRICS:
                        specs = self.specifications(3, pool=stock_pool, selection_order=order, metric=metric,
                            filters=[dict(field='pe', op='gt', value=-1e9)])
                        actual = self.consume(pool, specs)
                        for spec in specs:
                            expected = self.fixture.s.backtest_dates(self.fixture.db, **spec['request'], **spec['options'])
                            agreement = compare_results(expected, actual[spec['number']])
                            self.assertTrue(agreement['exact'], agreement)
                            maximum_absolute = max(maximum_absolute, agreement['maximum_absolute'])
                            maximum_relative = max(maximum_relative, agreement['maximum_relative'])
                            cases += 1
        identities = {index: tuple(ready['measurements'][key] for key in
            ('mappings', 'provider_instance', 'sql_workspace')) for index, ready in enumerate(pool.stats['readiness'])}
        for index, measurements in pool.stats['last_worker_measurements'].items():
            self.assertEqual(tuple(measurements[key] for key in
                ('mappings', 'provider_instance', 'sql_workspace')), identities[int(index)])
        self.assertEqual(pool.stats['started_workers'], 2)
        self.assertEqual(len({worker.process.pid for worker in pool.workers}), 2)
        self.assertLessEqual(pool.stats['peak_reserved_slots'], 2)
        self.assertLessEqual(pool.stats['peak_reserved_bytes'], pool.policy.identity['artifact_total_bytes'])
        self.assertEqual(pool.stats['reserved_bytes'], 0)
        self.assertFalse(list(self.fixture.root.glob('*trials.sqlite')))
        stats = pool.measurements(); pool.close(); self.assert_closed(pool)
        print(json.dumps(dict(check='persistent-trial-pool', cases=cases, maximum_absolute=maximum_absolute,
            maximum_relative=maximum_relative, tolerance=1e-12, measurements=stats, closure=pool.closure())), flush=True)

    def test_completion_order_and_release_held_reservations(self):
        pool = self.make(); original_send, original_event = pool._send, pool._event
        delayed = []
        def send(worker, event):
            if event.get('command') == 'trial' and worker.index == 0 and not delayed:
                delayed.append((worker, event)); return
            return original_send(worker, event)
        def event(*args):
            worker, value = original_event(*args)
            if value.get('event') == 'completed' and delayed:
                original_send(*delayed.pop())
            return worker, value
        with patch.object(pool, '_send', side_effect=send), patch.object(pool, '_event', side_effect=event):
            with pool.batch(self.specifications(2)) as batch:
                completions = batch.completed()
                first = next(completions)
                self.assertEqual(first.number, 2)
                self.assertEqual(pool.stats['reserved_slots'], 2)
                second = next(completions)
                self.assertEqual(second.number, 1)
                self.assertEqual(pool.stats['reserved_slots'], 2)
                self.assertTrue(first.stream and not first.stream.closed)
                first.release(); self.assertEqual(pool.stats['reserved_slots'], 1)
                first.release(); second.release()
                self.assertEqual(list(completions), [])
        self.assertEqual(pool.stats['reserved_slots'], 0)
        self.consume(pool, self.specifications(2))
        pool.close(); self.assert_closed(pool)

    def test_unreleased_capacity_is_bounded_and_abandoned_or_failed_observer_closes(self):
        pool = self.make()
        with self.assertRaisesRegex(ValueError, 'Release a completion'):
            with pool.batch(self.specifications(3)) as batch:
                list(batch.completed())
        self.assert_closed(pool)
        pool = self.make()
        with self.assertRaisesRegex(RuntimeError, 'observer'):
            with pool.batch(self.specifications(2)) as batch:
                for completion in batch.completed(): raise RuntimeError('fictional observer')
        self.assert_closed(pool)

    def test_source_generation_compiler_and_specification_mismatches(self):
        for override in (dict(source_identity={'changed': 'source'}),
                         dict(reference=dict(self.inputs.worker_reference(), identity='0'*64)),
                         dict(compiler_identity=dict(self.provider.compiler, signature='0'*64))):
            pool = self.make(**override)
            with self.assertRaises((ValueError, RuntimeError)): pool.start()
            self.assert_closed(pool)
        pool = self.make(); specs = self.specifications(2)
        malformed = deepcopy(specs); malformed[0]['options']['rank_to'] = 1
        with self.assertRaisesRegex(ValueError, 'digest'): pool.batch(malformed)
        with self.assertRaisesRegex(ValueError, 'Duplicate'): pool.batch([specs[0], specs[0]])
        self.assertFalse(pool.started)

    def test_cold_memory_admission_rejects_before_duplicate_start(self):
        settings = dict(workers=2, threads_per_worker=1, close_seconds=.5, private_memory_budget_bytes=1)
        pool = self.make(policy=ExecutionPolicy(settings))
        with self.assertRaisesRegex(ValueError, 'allowance'): pool.start()
        self.assertEqual(len(pool.workers), 1)
        self.assert_closed(pool)

    def test_worker_crash_bad_frame_descriptor_corruption_and_write_failure(self):
        pool = self.make(); pool.start(); pool.workers[0].process.kill()
        with self.assertRaises(RuntimeError): self.consume(pool, self.specifications(2))
        self.assert_closed(pool)
        for fault in ('descriptor', 'bytes', 'write', 'transport'):
            pool = self.make(); pool.start(); original = pool._event
            if fault == 'write': pool._artifact_path(0).mkdir()
            def event(*args):
                worker, value = original(*args)
                if value.get('event') == 'completed':
                    if fault == 'descriptor': value['descriptor']['specification'] = '0'*64
                    elif fault == 'bytes':
                        with pool._artifact_path(value['slot']).open('r+b') as stream:
                            stream.seek(10); stream.write(b'!')
                    elif fault == 'transport': value['unexpected'] = True
                return worker, value
            # Remove the deliberate directory only during cleanup so the
            # original disk failure remains the operation outcome.
            remove = pool._remove_slot
            def remove_slot(slot):
                path = pool._artifact_path(slot)
                if path.is_dir(): path.rmdir()
                remove(slot)
            with patch.object(pool, '_event', side_effect=event), patch.object(pool, '_remove_slot', side_effect=remove_slot):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.consume(pool, self.specifications(2))
            self.assert_closed(pool)

    def test_cancellation_start_and_calculation_and_partial_close_retry(self):
        pool = self.make(); calls = 0
        def stop():
            nonlocal calls
            calls += 1
            if pool.workers: raise backtest_control.Cancelled()
        pool.checkpoint = stop
        with self.assertRaises(backtest_control.Cancelled): pool.start()
        self.assert_closed(pool)
        pool = self.make(); pool.start()
        original = pool._send
        def cancel(worker, event):
            original(worker, event)
            if event.get('command') == 'trial': raise backtest_control.Cancelled()
        with patch.object(pool, '_send', side_effect=cancel), self.assertRaises(backtest_control.Cancelled):
            self.consume(pool, self.specifications(2))
        self.assert_closed(pool)
        pool = self.make(); self.consume(pool, self.specifications(1))
        original_remove = pool._remove_slot; failed = False
        def fail_once(slot):
            nonlocal failed
            if not failed: failed = True; raise OSError('fictional close failure')
            original_remove(slot)
        with patch.object(pool, '_remove_slot', side_effect=fail_once):
            with self.assertRaises(pools.ClosureError) as caught: pool.close()
        self.assertIs(caught.exception.numerical_runtime, pool)
        self.assertIs(pools._PENDING[id(pool)], pool)
        pool.close(); self.assert_closed(pool)

    def test_generation_retirement_waits_for_worker_pin_and_native_files_release(self):
        first = self.inputs.signature
        pool = self.make(); pool.start()
        self.portfolio.close(); self.provider.close(); self.inputs.close()
        self.fixture.advance(); self.fixture.advance()
        self.assertIn(first, self.fixture.store.retire_unused()['retained'])
        pool.close(); self.assert_closed(pool)
        self.assertIn(first, self.fixture.store.retire_unused()['removed'])

    def test_layout_above_old_four_thread_ceiling(self):
        if effective_lanes(observe_resources()) < 5: self.skipTest('Host has fewer than five effective numerical lanes.')
        policy = ExecutionPolicy(dict(workers=1, threads_per_worker=5, close_seconds=.5))
        provider = NumbaExecutor(self.inputs, limits=policy.provider_limits); self.addCleanup(provider.close)
        pool = self.make(policy=policy, compiler_identity=provider.compiler)
        self.consume(pool, self.specifications(1))
        self.assertEqual(pool.stats['readiness'][0]['threads'], 5)
        pool.close(); self.assert_closed(pool)

    def make_runtime(self, **extras):
        (self.fixture.root/'binding.json').write_text(json.dumps(self.fixture.binding))
        self.count += 1
        configuration = dict(source_root=str(ROOT), scratch=str(self.fixture.root/('runtime-'+str(self.count))),
            generation_path=str(self.fixture.store.path), checkpoint_path=str(self.fixture.root/'runtime-trials.sqlite'),
            threads=1, python=sys.executable, session_factory='numerical_trial_pool_fixture:Session',
            coordinator=self.fixture.owner, close_seconds=.5, session_options=dict(pool_start=True,
                execution=dict(workers=2, threads_per_worker=1, close_seconds=.5)))
        configuration.update(extras)
        return configuration

    def alive(self, pid):
        if os.name == 'nt': return str(pid) in windows_processes(include_pids=[pid])
        try: return Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
        except FileNotFoundError: return False

    def wait_gone(self, pids):
        deadline = time.monotonic()+10
        while any(self.alive(pid) for pid in pids):
            if time.monotonic() > deadline: self.fail('Owned processes survived actual parent death: '+str(pids))
            time.sleep(.02)

    def test_session_lazy_pool_owned_inside_runtime_containment_and_closed_before_inputs(self):
        configuration = self.make_runtime()
        configuration['session_options']['pool_start'] = False
        value = numerical_runtime.NumericalRuntime(**configuration); self.addCleanup(value.close)
        value.start()
        self.assertIsNone(value.last_stats['trial_pool'])
        result = value.calculate('__pool__', {})
        self.assertEqual(sorted(row['number'] for row in result['trials']), [1, 2, 3])
        self.assertEqual(value.last_stats['trial_pool']['started_workers'], 2)
        pids = value.last_stats['trial_pool']['worker_pids']
        if os.name != 'nt':
            for pid in pids: self.assertEqual(os.getsid(pid), value.owner.process.pid)
        else:
            tree = value.owner.tree_usage()
            self.assertGreaterEqual(tree['processes'], 3)
        value.close(); self.wait_gone(pids)
        marker = json.loads((Path(configuration['scratch'])/'fixture-state.json').read_bytes())
        self.assertTrue(marker['closed']); self.assertTrue(marker['mappings_closed'])
        self.assertTrue(marker['sql_closed']); self.assertTrue(marker['provider_closed'])
        self.assertFalse((Path(configuration['scratch'])/'trial-pool').exists())

    def test_actual_worker_parent_death_idle_and_active_releases_before_owner_cleanup(self):
        for active in (False, True):
            value = numerical_runtime.NumericalRuntime(**self.make_runtime()); self.addCleanup(value.close)
            value.start(); pids = value.last_stats['trial_pool']['worker_pids']
            if active:
                from threading import Event, Thread
                running = Event(); errors = []
                def progress(event): running.set()
                def calculate():
                    try: value.calculate('__pool__', {}, progress=progress)
                    except BaseException as error: errors.append(type(error).__name__)
                thread = Thread(target=calculate); thread.start()
                self.assertTrue(running.wait(10))
            value.owner.process.kill(); value.owner.process.wait(timeout=5)
            # Check before owner.close(), whose containment kill could otherwise
            # mask a broken worker process-handle/pipe monitor.
            self.wait_gone(pids)
            if active: thread.join(timeout=10); self.assertFalse(thread.is_alive())
            value.close()
            self.assertTrue(value.closure()['process']['native_handles_released'])

    def test_actual_application_owner_death_idle_and_active_cleans_runtime_tree(self):
        for active in (False, True):
            configuration = self.make_runtime(); self.count += 1
            configuration['fixture_coordinator'] = str(configuration.pop('coordinator').path)
            launch = self.fixture.root/('owner-'+str(self.count)+'.json')
            ready = launch.with_suffix('.ready')
            launch.write_text(json.dumps(configuration))
            command = [sys.executable, '-I', '-B', str(ROOT/'tests'/'numerical_trial_pool_fixture.py'),
                       str(launch), str(ready)]+(['active'] if active else [])
            parent = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic()+60; state = None
                while True:
                    if ready.exists():
                        try: state = json.loads(ready.read_bytes())
                        except (ValueError, OSError): state = None
                    if state and (not active or state['stage'] == 'active'): break
                    if parent.poll() is not None or time.monotonic() > deadline:
                        self.fail('Private application owner did not become ready.')
                    time.sleep(.02)
                parent.kill(); parent.wait(timeout=5)
                self.wait_gone([state['runtime'], *state['workers']])
                with self.fixture.owner.hold(timeout=1): pass
            finally:
                if parent.poll() is None: parent.kill(); parent.wait(timeout=5)

    def test_small_subsets_start_only_needed_workers_and_identity_never_changes(self):
        pool = self.make(); identity = pool.execution_identity
        self.consume(pool, self.specifications(1))
        self.assertEqual(pool.stats['started_workers'], 1)
        self.assertEqual(pool.execution_identity, identity)
        first_pid = pool.workers[0].process.pid
        self.consume(pool, self.specifications(3))
        self.assertEqual(pool.stats['started_workers'], 2)
        self.assertEqual(pool.workers[0].process.pid, first_pid)
        self.assertEqual(pool.execution_identity, identity)

    def test_source_exclusion_before_import_and_cancel_observed_attachment_and_initialization(self):
        # Only the source-owning bootstrap can run in this deliberately minimal
        # private root. Rejection must precede every calculation/native import.
        private = self.fixture.root/'source-exclusion'
        for name in ('backtest/engines/numerical/trial_worker.py','website/runtime_access.py'):
            target = private/name; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/name,target)
        pool = self.make(source_root=private)
        with runtime_access.ownership(private, exclusive=True, timeout=0):
            with self.assertRaises(RuntimeError): pool.start()
        self.assertEqual(pool.stats['started_workers'], 0)
        self.assertFalse(pool.stats['worker_stages'])
        self.assert_closed(pool)
        for stage in ('attaching','initializing','calculating'):
            pool = self.make(); checkpoint = pool.checkpoint
            def stop():
                checkpoint()
                if stage in pool.stats['worker_stages'].values(): raise backtest_control.Cancelled()
            pool.checkpoint = stop
            with self.assertRaises(backtest_control.Cancelled):
                self.consume(pool, self.specifications(2))
            self.assert_closed(pool)

    def test_stuck_owned_worker_cleanup_is_finite_and_does_not_retry_task(self):
        pool = self.make(); pool.start(); worker = pool.workers[0]
        if os.name == 'nt':
            import ctypes as c
            from ctypes import wintypes as w
            kernel = c.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [w.DWORD,w.BOOL,w.DWORD]; kernel.OpenProcess.restype = w.HANDLE
            kernel.CloseHandle.argtypes = [w.HANDLE]
            native = c.WinDLL('ntdll')
            native.NtSuspendProcess.argtypes = [w.HANDLE]
            handle = kernel.OpenProcess(0x0800,False,worker.process.pid)
            self.assertTrue(handle)
            try: self.assertEqual(native.NtSuspendProcess(handle),0)
            finally: kernel.CloseHandle(handle)
        else: os.kill(worker.process.pid,signal.SIGSTOP)
        started = time.monotonic(); pool.close()
        self.assertLess(time.monotonic()-started,5.)
        self.assertEqual(pool.stats['completed_trials'],0)
        self.assert_closed(pool)

    def test_pending_launch_and_task_publication_failures_keep_original_outcome_and_remove_owned_files(self):
        original = pools.write_payload
        for phase in ('launch','task'):
            for failure in ('write','replace'):
                pool = self.make()
                if phase == 'task': pool.start(required_workers=1)
                def publish(path,value,limit):
                    if (path.name == 'worker.json') == (phase == 'launch'):
                        path.with_suffix('.pending').write_bytes(b'partial task-owned publication')
                        if failure == 'replace': raise PermissionError('fictional replace failure')
                        raise OSError('fictional write failure')
                    return original(path,value,limit)
                with patch.object(pools,'write_payload',side_effect=publish):
                    with self.assertRaises(OSError):
                        if phase == 'launch': pool.start()
                        else: self.consume(pool,self.specifications(1))
                self.assert_closed(pool)


if __name__ == '__main__': unittest.main()

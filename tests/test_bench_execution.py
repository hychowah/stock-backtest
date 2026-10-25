"""Actual bound reference/Numba paths on disposable captures, never real data."""
from contextlib import closing
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import test_bench_execution_inputs as fixtures
import bench_execution as execution
from bench_comparison import ComparisonProtocol, ComparisonError
from bench_generation import signature
from test_bench_input_store import metadata, REPORT


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkspaceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        raw = f.source / 'raw'; raw.mkdir()
        for name in ('universe.json', 'metrics.jsonl', 'spy-div.json', 'treasury.json'):
            (raw / name).write_text('[]')
        (raw / 'px').mkdir()
        (raw / 'financial-inputs' / 'income').mkdir(parents=True)
        (raw / 'financial-inputs' / 'income' / 'A.json').write_text('[]')
        (f.source / 'results').mkdir()
        (f.source / 'results' / 'summary-exits.txt').write_bytes(REPORT)
        (f.source / 'data').mkdir()
        names = ('baseline', 'metrics', 'books', 'cache_assets', 'run', 'revalue', 'financial_inputs')
        modules = {name: SimpleNamespace(__file__=str(f.source / 'scripts' / (name + '.py'))) for name in names}
        modules['baseline'].cutoff = lambda text: date(2026, 10, 21)
        observed = signature(SimpleNamespace(ROOT=f.source, RAW=raw, RESULTS=f.source / 'results',
            __file__=str(f.source / 'scripts/research.py'), **modules))
        engine = {name: [path.stat().st_size, path.stat().st_mtime_ns]
                  for name in ('schedules.py', 'book_batch.py') for path in [f.source / 'scripts' / name]}
        f.freshness['inputs'] = observed
        f.freshness['daily_inputs'] = dict(version=3, inputs=observed, engine=engine)
        with closing(sqlite3.connect(f.capture / 'research.sqlite')) as r, closing(sqlite3.connect(f.capture / 'schedules.sqlite')) as d:
            for db in (r, d):
                db.execute('DELETE FROM statements')
                db.execute('DELETE FROM financial_inputs')
                for year in range(2011, 2017):
                    fiscal = date(year, 6, 30)
                    db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                        ('A', str(fiscal), str(fiscal + timedelta(days=90)), 150e6, 180e6, 60e6, 60/180))
                    db.execute('INSERT INTO financial_inputs VALUES(?,?,?)',
                        ('A', str(fiscal), json.dumps(dict(totalStockholdersEquity=100e6, netIncome=30e6,
                                                         epsDiluted=year - 2010., freeCashFlow=20e6))))
            for table in ('prices', 'sessions', 'treasuries'):
                d.execute('DELETE FROM ' + table)
            day, index = date(2012, 1, 1), 0
            while day <= date(2016, 12, 30):
                if day.weekday() < 5:
                    d.execute('INSERT INTO prices VALUES(?,?,?,?)', ('A', str(day), 10 + index * .001, 10 + index * .001))
                    if day >= date(2015, 1, 1):
                        d.execute('INSERT INTO sessions VALUES(?,?)', (str(day), 100 + index * .02))
                    index += 1
                day += timedelta(days=1)
            d.execute("INSERT INTO treasuries VALUES('2014-12-31',.01)")
            metadata(r, dict(inputs=f.freshness['inputs'], prices=f.freshness['prices']))
            metadata(d, dict(daily_inputs=f.freshness['daily_inputs']))
            r.commit(); d.commit()
            f.meta = dict(zip(('research', 'daily'), (execution.inputs.artifacts.metadata(db,
                execution.inputs.ExecutionInputError, reason='incomplete') for db in (r, d))))
            f.identity = fixtures.semantic(r, d, f.sources)
        for name in ('research.sqlite', 'schedules.sqlite'):
            import shutil
            shutil.copy2(f.capture / name, f.source / 'data' / name)
            f.manifest['artifacts'][name] = fixtures.receipt(f.capture / name)
        f.manifest.update(financial_generation=f.identity, metadata=f.meta)
        f.manifest['originals']['freshness'] = f.freshness
        f.write_manifest()
        # Generate ordinary samples from actual source without live bootstrap.
        sys.path[:0] = [str(ROOT / 'scripts')]
        import robustness
        with closing(sqlite3.connect(f.capture / 'schedules.sqlite')) as db:
            db.row_factory = sqlite3.Row
            self.configuration = robustness.plan(db, start='2015-01-01', end='2016-12-30',
                months=1, trials=5, seed=42, pool='cached', rank_to=1, min_cap=0., min_ev=0.)

    def owner(self, **changes):
        f = self.fixture
        costs = dict(attachment=20., clone=10., setup=180., proof=30., request=90.,
                     collection=20., shutdown=30., finalization=20.)
        envelope = execution.ExecutionEnvelope(32 * 1024**2, 64 * 1024**2, 2 * 1024**3, 400., 2)
        protocol = ComparisonProtocol.freeze(configuration=self.configuration,
            binding=dict(capture_id=f.manifest['capture_id'], financial_generation=f.identity,
                         sources=execution.digest(f.sources)),
            environment=execution.environment(envelope), costs=costs,
            step_costs={step: {key: costs[key] / 4 for key in ('clone', 'setup', 'proof',
                        'request', 'collection', 'shutdown')} for step in
                        ('control_before', 'numba_source', 'numba_compiled', 'control_after')},
            whole_seconds=400., max_control_drift=1000., max_bracket_seconds=390.)
        values = dict(capture=f.capture, source=f.source, output=f.output, protocol=protocol,
            envelope=envelope,
            fixture_observation_root=f.source)
        values.update(changes)
        return execution.MeasurementExecution(**values)

    def fixture_command(self, owner, request):
        # There is no production flag or environmental admission override.
        # Patch only this disposable child's test harness, not shipped workers.
        return [sys.executable, '-I', '-B', '-c',
            'import sys;sys.path.insert(0,sys.argv[1]);'
            'from unittest.mock import patch;import bench_execution_worker as w;'
            'ctx=patch.object(w.admission,"require_execution");ctx.start();w.main()',
            str(owner._tools), str(request)]

    def test_default_admission_rejects_before_any_effects(self):
        owner = self.owner()
        with self.assertRaises(execution.admission.BenchmarkAdmissionError):
            owner.__enter__()
        self.assertFalse(self.fixture.output.exists())

    def test_actual_reference_numba_pair_preserves_capture_replay_and_closes(self):
        owner = self.owner()
        before = self.fixture.immutable_bytes()
        with patch.object(execution.admission, 'require_execution'), \
                patch.object(owner, '_command', side_effect=lambda request: self.fixture_command(owner, request)):
            with owner:
                owner.compare()
                with self.assertRaisesRegex(ComparisonError, 'incomplete'):
                    _ = owner.result
        result = owner.result
        self.assertEqual(result['status'], 'fixture_pair_complete')
        self.assertEqual(result['execution_admission'], 'unavailable')
        self.assertIsNone(owner._owned)
        self.assertFalse(owner._workspace._active)
        self.assertEqual(before, self.fixture.immutable_bytes())
        records = {step: json.loads((owner._workspace._folder / step / 'result.json').read_bytes())
                   for step in ('control_before', 'numba_source', 'numba_compiled', 'control_after')}
        self.assertGreater(records['control_before']['details']['execution']['workers'], 1)
        self.assertEqual({record['policy_signature'] for record in records.values()}, {owner._policy_signature})
        for record in records.values():
            self.assertEqual(record['details']['response_bytes'], record['details']['received_bytes'])
        self.fixture.output.rename(self.fixture.root / 'closed-experiment')

    def test_cancelled_attachment_preserves_originals_and_releases_owner(self):
        before = self.fixture.immutable_bytes()
        with patch.object(execution.admission, 'require_execution'):
            with self.assertRaisesRegex(execution.inputs.ExecutionInputError, 'cancelled'):
                with self.owner(cancel=lambda: True):
                    self.fail('Entered cancelled execution')
        self.assertEqual(before, self.fixture.immutable_bytes())

    def test_changed_current_inventory_is_rejected_without_later_steps(self):
        owner = self.owner()
        with patch.object(execution.admission, 'require_execution'), \
                patch.object(owner, '_command', side_effect=lambda request: self.fixture_command(owner, request)):
            with self.assertRaisesRegex(ComparisonError, 'stale'):
                with owner:
                    (self.fixture.source / 'raw' / 'financial-inputs' / 'income' / 'new.json').write_text('[]')
                    owner.compare()
        self.assertEqual([event['step'] for event in owner._ledger.events if event['event'] == 'start'], ['control_before'])
        self.assertIsNone(owner._owned)

    def test_report_journal_source_and_prepared_replacements_stop_the_pair(self):
        for kind in ('report', 'journal', 'source', 'prepared'):
            with self.subTest(kind=kind):
                f = self.fixture
                path = {'report': f.source / 'results/summary-exits.txt',
                        'journal': f.source / 'data/research.sqlite.publication.json',
                        'source': f.source / 'scripts/metrics.py',
                        'prepared': f.source / 'data/research.sqlite'}[kind]
                original = path.read_bytes() if path.exists() else None
                info = path.stat() if original is not None else None
                owner = self.owner()
                try:
                    with patch.object(execution.admission, 'require_execution'), \
                            patch.object(owner, '_command', side_effect=lambda request: self.fixture_command(owner, request)):
                        with self.assertRaises(ComparisonError):
                            with owner:
                                if kind == 'prepared':
                                    with closing(sqlite3.connect(path)) as db:
                                        metadata(db, dict(version=-1)); db.commit()
                                else:
                                    path.write_bytes((original or b'') + b'\n')
                                owner.compare()
                    self.assertIsNone(owner._owned)
                    self.assertNotIn(id(owner), execution._pending_measurements)
                finally:
                    if original is None:
                        path.unlink()
                    else:
                        path.write_bytes(original)
                        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))

    def test_cancellation_during_owned_child_work_reaps_before_release(self):
        owner = self.owner()
        owner.cancel = lambda: owner._owned is not None
        with patch.object(execution.admission, 'require_execution'), \
                patch.object(owner, '_command', side_effect=lambda request: self.fixture_command(owner, request)):
            with self.assertRaisesRegex(ComparisonError, 'cancelled'):
                with owner:
                    owner.compare()
        self.assertIsNone(owner._owned)
        self.assertFalse(owner._workspace._active)
        self.assertNotIn(id(owner), execution._pending_measurements)

    def test_unconfirmed_close_retains_ownership_until_explicit_retry(self):
        owner = self.owner()
        with patch.object(execution.admission, 'require_execution'):
            owner.__enter__()
            with patch.object(owner, '_close_child', side_effect=ComparisonError('closure_pending')):
                with self.assertRaisesRegex(ComparisonError, 'closure_pending'):
                    owner.__exit__(None, None, None)
            self.assertTrue(owner._workspace._active)
            self.assertIs(execution._pending_measurements[id(owner)], owner)
            with self.assertRaisesRegex(ComparisonError, 'incomplete'):
                owner.__exit__(None, None, None)
        self.assertNotIn(id(owner), execution._pending_measurements)
        self.assertFalse(owner._workspace._active)

    def test_wrong_generation_or_environment_never_starts_financial_workers(self):
        for kind in ('generation', 'environment'):
            with self.subTest(kind=kind):
                owner = self.owner()
                declaration = owner.protocol.value
                if kind == 'generation':
                    declaration['binding']['financial_generation'] = '0' * 64
                else:
                    declaration['environment']['python'] = 'changed interpreter'
                declaration.pop('version')
                owner.protocol = ComparisonProtocol.freeze(**declaration)
                with patch.object(execution.admission, 'require_execution'), patch.object(owner, '_command') as command:
                    with self.assertRaisesRegex(ComparisonError, 'mismatch'):
                        with owner:
                            owner.compare()
                    command.assert_not_called()
                self.assertNotIn(id(owner), execution._pending_measurements)

    def finish_ledger(self, owner):
        # Failure-path state fixture only. It supplies no financial/speed proof.
        for step in owner.protocol.value['order']:
            owner._ledger.begin(step)
            owner._ledger.finish(step, dict(financial_agreement=True, closed=True, request_seconds=1.))

    def test_failed_final_publication_cannot_expose_a_successful_result(self):
        owner = self.owner()
        with patch.object(execution.admission, 'require_execution'):
            owner.__enter__()
            self.finish_ledger(owner)
            publish = owner._persist
            def fail_complete(status, error=None):
                if status == 'complete':
                    raise OSError('Synthetic evidence publication failure')
                return publish(status, error)
            with patch.object(owner, '_persist', side_effect=fail_complete):
                with self.assertRaises(OSError):
                    owner.__exit__(None, None, None)
        with self.assertRaisesRegex(ComparisonError, 'incomplete'):
            _ = owner.result
        self.assertIsNone(owner._result)
        self.assertIsNotNone(owner._ledger.stopped)
        self.assertFalse(owner._workspace._active)

    def test_cleanup_retry_cannot_turn_a_failed_body_into_a_completed_pair(self):
        owner = self.owner()
        error = RuntimeError('Synthetic caller failure')
        with patch.object(execution.admission, 'require_execution'):
            owner.__enter__()
            self.finish_ledger(owner)
            with patch.object(owner, '_close_child', side_effect=ComparisonError('closure_pending')):
                self.assertFalse(owner.__exit__(type(error), error, None))
            self.assertTrue(owner._workspace._active)
            self.assertIs(owner._terminal_error, error)
            self.assertIsNotNone(owner._ledger.stopped)
            owner.__exit__(None, None, None)
        with self.assertRaisesRegex(ComparisonError, 'incomplete'):
            _ = owner.result
        self.assertFalse(owner._workspace._active)
        self.assertNotIn(id(owner), execution._pending_measurements)

    def test_failed_child_constructor_keeps_workspace_and_process_for_retry(self):
        from contextlib import ExitStack
        from bench_candidates_process import OwnedProcess, _pending_processes
        for failure_kind in ('descendants', 'handles'):
            with self.subTest(failure_kind=failure_kind):
                owner = self.owner()
                failure = RuntimeError('Synthetic reader initialization failure')
                with patch.object(execution.admission, 'require_execution'):
                    owner.__enter__()
                    with ExitStack() as faults:
                        faults.enter_context(patch('bench_candidates_process.Thread.start', side_effect=failure))
                        if failure_kind == 'descendants':
                            faults.enter_context(patch.object(OwnedProcess, 'wait_empty', side_effect=TimeoutError('Synthetic closure')))
                        else:
                            def partial_close(process):
                                for stream in (process.process.stdin, process.process.stdout):
                                    if not stream.closed: stream.close()
                                raise OSError('Synthetic native handle close failure')
                            faults.enter_context(patch.object(OwnedProcess, '_close_handles', partial_close))
                        with self.assertRaises(RuntimeError) as caught:
                            try: owner.compare()
                            except BaseException as error:
                                owner.__exit__(type(error), error, error.__traceback__)
                                raise
                        self.assertIs(caught.exception, failure)
                    process = owner._owned
                    self.assertIs(process, failure.owned_process)
                    self.assertIs(_pending_processes[id(process)], process)
                    self.assertTrue(owner._workspace._active)
                    self.assertIs(execution._pending_measurements[id(owner)], owner)
                    owner.__exit__(None, None, None)
                    self.assertNotIn(id(process), _pending_processes)
                    self.assertNotIn(id(owner), execution._pending_measurements)
                    self.assertFalse(owner._workspace._active)

if __name__ == '__main__':
    unittest.main()

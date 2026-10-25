"""Disposable captured-workspace proofs. No raw/cache/runtime or engine reads."""
from contextlib import closing
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from threading import Lock
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if '--runtime' in sys.argv:
    index = sys.argv.index('--runtime'); del sys.argv[index:index + 2]
sys.path.insert(0, str(ROOT / 'tools'))
import bench_execution_inputs as execution
import bench_input_artifacts as artifacts
import bench_input_store as store
from test_bench_input_store import fill, metadata, REPORT, EVIDENCE
from types import SimpleNamespace


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt(path):
    return dict(bytes=path.stat().st_size, mtime_ns=path.stat().st_mtime_ns, sha256=sha(path))


def semantic(research, daily, sources):
    budget = execution._Budget(None)
    rows = lambda db, table: artifacts.table_hash(db, table, budget,
        execution.ExecutionInputError, reason='corrupt', every=1024, pool_order=False)
    return artifacts.digest(dict(
        research={table: rows(research, table) for table in artifacts.RESEARCH_TABLES if table != 'metadata'},
        daily_base={table: rows(daily, table) for table in artifacts.DAILY_BASE},
        metadata=tuple(artifacts.metadata(db, execution.ExecutionInputError, reason='incomplete') for db in (research, daily)),
        report=hashlib.sha256(REPORT).hexdigest(), sources=sources))


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cb02-execution-inputs-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.capture = self.root / 'capture'; self.capture.mkdir()
        self.source = self.root / 'policy'; (self.source / 'scripts').mkdir(parents=True)
        for path in (ROOT / 'scripts').glob('*.py'):
            shutil.copy2(path, self.source / 'scripts' / path.name)
        (self.source / 'website').mkdir()
        shutil.copy2(ROOT / 'website/runtime_access.py', self.source / 'website/runtime_access.py')
        self.sources = {p.relative_to(self.source).as_posix(): sha(p)
                        for p in self.source.rglob('*.py')}
        self.freshness = dict(inputs={'raw/universe.json': [2, 1], 'raw/px': ['directory', 1],
            'historical_through': '2026-10-21'}, prices={'A.json': [100, 1234]})
        self.freshness['daily_inputs'] = dict(version=3, inputs=self.freshness['inputs'],
            engine={'schedules.py': [123, 456], 'book_batch.py': [234, 567]})
        with closing(sqlite3.connect(self.capture / 'research.sqlite')) as research, closing(sqlite3.connect(self.capture / 'schedules.sqlite')) as daily:
            fill(SimpleNamespace(research=research, daily=daily,
                write_report=lambda content: (self.capture / 'report.txt').write_bytes(content)))
            metadata(research, dict(inputs=self.freshness['inputs'], prices=self.freshness['prices']))
            metadata(daily, dict(daily_inputs=self.freshness['daily_inputs']))
            daily.execute("INSERT INTO periods VALUES(1,'2025-06-02','2025-06-03',0.1,0.04,1,1)")
            daily.execute("INSERT INTO period_pools VALUES(1,'legacy')")
            research.commit(); daily.commit()
            self.meta = dict(zip(('research', 'daily'),
                (artifacts.metadata(db, execution.ExecutionInputError, reason='incomplete') for db in (research, daily))))
            self.identity = semantic(research, daily, self.sources)
        receipts = {path.name: receipt(path) for path in self.capture.iterdir()}
        before = dict(assets=dict(zip(('data/research.sqlite', 'data/schedules.sqlite', 'results/summary-exits.txt'),
            (receipts[name] for name in ('research.sqlite', 'schedules.sqlite', 'report.txt')))),
            sources=self.sources, raw_inventory={'raw/universe.json': [2, 1]},
            freshness=self.freshness, installed_revision='a' * 40, deployment=None)
        self.manifest = dict(version=1, capture_id='b' * 32, financial_generation=self.identity,
            installed_revision='a' * 40, originals=before, metadata=self.meta, artifacts=receipts,
            limits=dict(database_bytes=4 * 1024**3, output_bytes=8 * 1024**3,
                sampled_current_memory_bytes=512 * 1024**2, wall_seconds=900.),
            benchmark_admitted=False, originals_unchanged=True)
        self.manifest = json.loads(artifacts.encoded(self.manifest))
        self.write_manifest()
        self.output = self.root / 'experiment'

    def write_manifest(self):
        (self.capture / 'capture.json').write_bytes(artifacts.encoded(self.manifest))

    def owner(self, output=None, **kwargs):
        return execution.CapturedWorkspace(self.capture, self.source, output or self.output, **kwargs)

    def assert_reason(self, reason, function):
        with self.assertRaises(execution.ExecutionInputError) as caught:
            function()
        self.assertEqual(caught.exception.reason, reason)

    def refresh_receipt(self, name):
        self.manifest['artifacts'][name] = receipt(self.capture / name)
        self.write_manifest()

    def immutable_bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for folder in (self.capture, self.source) for p in folder.rglob('*') if p.is_file()}

    def test_exact_attachment_saved_books_sources_report_and_final_closure(self):
        original = self.immutable_bytes()
        with self.owner() as inputs:
            self.assertEqual(inputs.identity, self.identity)
            self.assertEqual(inputs.capture_id, 'b' * 32)
            self.assertEqual(inputs.report, REPORT)
            self.assertEqual(inputs.captured_metadata, self.meta)
            self.assertEqual(inputs.captured_freshness, self.freshness)
            self.assertEqual(inputs.manifest_bytes, (self.capture / 'capture.json').read_bytes())
            self.assertEqual(inputs.daily.execute('SELECT COUNT(*) FROM periods').fetchone()[0], 1)
            self.assertEqual(inputs.daily.execute('SELECT * FROM period_pools').fetchone()[1], 'legacy')
            self.assertEqual({p.relative_to(inputs.source_snapshot).as_posix(): sha(p)
                              for p in inputs.source_snapshot.rglob('*.py')}, self.sources)
            daily, research = inputs.daily, inputs.research
            for db in (daily, research):
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute('DELETE FROM companies')
                db.execute('PRAGMA query_only=OFF')
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute('DELETE FROM companies')
            record = json.loads((inputs._folder / 'workspace.json').read_bytes())
            self.assertEqual(record['current_raw_freshness'], 'unavailable')
            self.assertEqual(record['execution_admission'], 'unavailable')
        for db in (daily, research):
            with self.assertRaises(sqlite3.ProgrammingError): db.execute('SELECT 1')
        self.assertEqual(original, self.immutable_bytes())
        self.assertEqual(json.loads((inputs._folder / 'workspace.json').read_bytes())['status'], 'complete')
        self.capture.rename(self.root / 'closed-capture')
        self.output.rename(self.root / 'closed-output')

    def test_derivatives_are_private_preserve_books_and_financial_identity(self):
        original = self.immutable_bytes()
        with self.owner() as inputs:
            with inputs.writable_daily() as daily:
                self.assertEqual(daily.execute('SELECT COUNT(*) FROM periods').fetchone()[0], 1)
                daily.execute("INSERT INTO periods VALUES(2,'2025-07-02','2025-07-03',0.2,0.04,1,1)")
                daily.commit()
                self.assertEqual(semantic(inputs.research, daily, self.sources), inputs.identity)
                self.assertEqual(inputs.daily.execute('SELECT COUNT(*) FROM periods').fetchone()[0], 1)
                path = Path(daily.execute('PRAGMA database_list').fetchone()[2])
                self.assertTrue(path.is_relative_to(self.output))
                self.assertFalse(path.is_relative_to(self.capture))
            with self.assertRaises(sqlite3.ProgrammingError): daily.execute('SELECT 1')
            with inputs.writable_daily() as next_daily:
                self.assertEqual(next_daily.execute('SELECT COUNT(*) FROM periods').fetchone()[0], 1)
        self.assertEqual(original, self.immutable_bytes())
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM periods').fetchone()[0], 2)
        path.rename(path.with_suffix('.closed'))

    def test_outer_exit_closes_escaped_derivative_before_owner_release(self):
        other = self.owner()
        with self.owner() as inputs:
            escaped = inputs.writable_daily(); daily = escaped.__enter__()
            path = Path(daily.execute('PRAGMA database_list').fetchone()[2])
            self.assert_reason('busy', other.__enter__)
        with self.assertRaises(sqlite3.ProgrammingError): daily.execute('SELECT 1')
        path.rename(path.with_suffix('.closed'))
        escaped.__exit__(None, None, None)
        self.assert_reason('incomplete', lambda: inputs.writable_daily().__enter__())
        self.assert_reason('incomplete', inputs.__enter__)
        with self.owner(): pass

    def test_both_caller_contexts_preserve_exception_identity_and_sanitize_evidence(self):
        for inner in (False, True):
            for error in (RuntimeError('private body'), sqlite3.OperationalError('private SQL body'),
                          FileNotFoundError('private path')):
                owner = self.owner()
                with self.subTest(inner=inner, kind=type(error).__name__):
                    with self.assertRaises(type(error)) as caught:
                        with owner as inputs:
                            if inner:
                                with inputs.writable_daily(): raise error
                            raise error
                    self.assertIs(caught.exception, error)
                    record = (owner._folder / 'workspace.json').read_text()
                    self.assertNotIn('private', record)
                    self.assertEqual(json.loads(record)['reason'], 'unexpected')
                    if inner:
                        records = list(owner._folder.glob('daily-*/attempt.json'))
                        self.assertEqual(len(records), 1)
                        self.assertEqual(json.loads(records[0].read_bytes())['reason'], 'unexpected')
        with self.owner(): pass

    def test_no_wait_lock_for_independent_instances_and_os_layer(self):
        with self.owner():
            self.assert_reason('busy', self.owner().__enter__)
            other = self.owner(); other._thread_lock = Lock()
            self.assert_reason('busy', other.__enter__)
        with self.owner(): pass

    def test_cancel_at_entry_and_backup_preserves_inputs_and_closes_handles(self):
        original = self.immutable_bytes()
        self.assert_reason('cancelled', self.owner(cancel=lambda: True).__enter__)
        cancelled = False
        with self.owner(cancel=lambda: cancelled) as inputs:
            original_progress = execution._Budget.backup_progress
            def cancel_at_page(budget, *args):
                nonlocal cancelled
                cancelled = True
                original_progress(budget, *args)
            with patch.object(execution._Budget, 'backup_progress', cancel_at_page):
                self.assert_reason('cancelled', lambda: inputs.writable_daily().__enter__())
            cancelled = False
        self.assertEqual(original, self.immutable_bytes())
        for path in self.output.glob('workspace-*/daily-*/schedules.sqlite'):
            path.rename(path.with_suffix('.closed'))
        records = list(self.output.glob('workspace-*/daily-*/attempt.json'))
        self.assertEqual(json.loads(records[0].read_bytes())['reason'], 'cancelled')

    def test_all_prospective_limits_reject_without_relaxing_store_limits(self):
        self.assertEqual((store._MAX_DATABASE_BYTES, store._MAX_OUTPUT_BYTES,
                          store._MAX_MEMORY_BYTES, store._MAX_SECONDS),
                         (32 * 1024**2, 64 * 1024**2, 128 * 1024**2, 10.))
        for name, value in (('MAX_DATABASE_BYTES', 1), ('MAX_OUTPUT_BYTES', 1),
                            ('MAX_MEMORY_BYTES', 1), ('MAX_SECONDS', -1)):
            with self.subTest(name=name), patch.object(execution, name, value):
                self.assert_reason('limit', self.owner().__enter__)
        with self.owner(): pass

    def test_partial_attachment_failure_closes_first_connection(self):
        real = execution._connect
        opened = []
        def fail_second(*args, **kwargs):
            if opened: raise sqlite3.OperationalError('private database failure')
            db = real(*args, **kwargs); opened.append(db); return db
        with patch.object(execution, '_connect', side_effect=fail_second):
            self.assert_reason('corrupt', self.owner().__enter__)
        with self.assertRaises(sqlite3.ProgrammingError): opened[0].execute('SELECT 1')
        self.capture.rename(self.root / 'renamed'); self.capture = self.root / 'renamed'
        with self.owner(): pass

    def test_owner_database_error_mapping_and_caller_programming_errors(self):
        for code, reason in ((sqlite3.SQLITE_BUSY, 'busy'), (sqlite3.SQLITE_LOCKED, 'busy'),
                             (sqlite3.SQLITE_FULL, 'limit'), (sqlite3.SQLITE_CORRUPT, 'corrupt')):
            error = sqlite3.OperationalError('private error'); error.sqlite_errorcode = code
            with self.subTest(reason=reason), patch.object(execution, '_connect', side_effect=error):
                self.assert_reason(reason, self.owner().__enter__)
        error = sqlite3.ProgrammingError('programming defect')
        with patch.object(execution, '_connect', side_effect=error):
            with self.assertRaises(sqlite3.ProgrammingError) as caught: self.owner().__enter__()
            self.assertIs(caught.exception, error)

    def test_corrupt_hash_schema_metadata_report_and_generation_reject(self):
        for name, content in (('schedules.sqlite', b'not sqlite'), ('report.txt', REPORT + b'changed')):
            path = self.capture / name; saved = path.read_bytes()
            path.write_bytes(content)
            self.assert_reason('corrupt', self.owner().__enter__)
            path.write_bytes(saved)
        self.manifest['financial_generation'] = '0' * 64; self.write_manifest()
        self.assert_reason('mismatch', self.owner().__enter__)
        self.manifest['financial_generation'] = self.identity; self.write_manifest()
        original_report = deepcopy(self.manifest['originals']['assets']['results/summary-exits.txt'])
        self.manifest['originals']['assets']['results/summary-exits.txt']['sha256'] = '0' * 64; self.write_manifest()
        self.assert_reason('mismatch', self.owner().__enter__)
        self.manifest['originals']['assets']['results/summary-exits.txt'] = original_report; self.write_manifest()
        path = self.capture / 'schedules.sqlite'; saved = path.read_bytes()
        path.write_bytes(b'not sqlite'); self.refresh_receipt(path.name)
        self.assert_reason('corrupt', self.owner().__enter__)
        path.write_bytes(saved); self.refresh_receipt(path.name)
        with closing(sqlite3.connect(path)) as db:
            db.execute('DROP TABLE sessions'); db.commit()
        self.refresh_receipt(path.name)
        self.assert_reason('unsupported', self.owner().__enter__)

    def test_mixed_shared_rows_and_metadata_reject_even_with_artifact_receipts(self):
        path = self.capture / 'schedules.sqlite'; saved = path.read_bytes()
        for defect in ('rows', 'metadata', 'report'):
            with closing(sqlite3.connect(path)) as db:
                if defect == 'rows': db.execute("UPDATE companies SET name='different'")
                else: metadata(db, dict(cached_symbols=['different']))
                db.commit()
            if defect == 'rows':
                self.refresh_receipt(path.name)
                self.assert_reason('mismatch', self.owner().__enter__)
            elif defect == 'metadata':
                self.refresh_receipt(path.name)
                self.assert_reason('mismatch', self.owner().__enter__)
            else:
                self.manifest['artifacts']['report.txt']['sha256'] = 'f' * 64; self.write_manifest()
                self.assert_reason('mismatch', self.owner().__enter__)
            path.write_bytes(saved)
            self.refresh_receipt(path.name)
        self.manifest['artifacts']['report.txt'] = receipt(self.capture / 'report.txt'); self.write_manifest()

    def test_malformed_nested_manifest_values_are_contained(self):
        original = deepcopy(self.manifest)
        mutations = [
            ('metadata', None), ('originals', []), ('limits', {'wall_seconds': None}),
            ('artifacts', []), ('financial_generation', []), ('capture_id', True),
        ]
        for key, value in mutations:
            self.manifest = deepcopy(original); self.manifest[key] = value; self.write_manifest()
            self.assert_reason('incomplete', self.owner().__enter__)
        changes = [
            ('sources', None), ('sources', {'scripts/books.py': []}),
            ('freshness', None), ('freshness', {'inputs': []}),
            ('raw_inventory', {'raw/x': [None, 1]}), ('assets', {'x': None}),
            ('deployment', {'bytes': True, 'mtime_ns': 1, 'sha256': 'a' * 64}),
        ]
        for key, value in changes:
            self.manifest = deepcopy(original); self.manifest['originals'][key] = value; self.write_manifest()
            self.assert_reason('incomplete', self.owner().__enter__)
        for value in (None, [], {'bytes': True, 'sha256': 'a' * 64, 'mtime_ns': 0},
                      {'bytes': 1, 'sha256': None, 'mtime_ns': 0}):
            self.manifest = deepcopy(original); self.manifest['artifacts']['schedules.sqlite'] = value; self.write_manifest()
            self.assert_reason('incomplete', self.owner().__enter__)
        for raw in (b'\xff', b'{broken', b'[]', b'{"limits":NaN}'):
            (self.capture / 'capture.json').write_bytes(raw)
            self.assert_reason('incomplete', self.owner().__enter__)
        self.manifest = original; self.write_manifest()
        with self.owner(): pass

    def test_malformed_database_metadata_is_contained(self):
        path = self.capture / 'schedules.sqlite'; saved = path.read_bytes()
        for value in (None, [], {'version': 3, 'inputs': {}, 'engine': []}, {'x': float('nan')}):
            with self.subTest(value=value), closing(sqlite3.connect(path)) as db:
                metadata(db, dict(daily_inputs=value)); db.commit()
            self.refresh_receipt(path.name)
            with self.assertRaises(execution.ExecutionInputError): self.owner().__enter__()
            path.write_bytes(saved)
        self.refresh_receipt(path.name)
        with self.owner(): pass

    def test_missing_changed_and_incomplete_source_dependencies_reject_without_fallback(self):
        path = self.source / 'scripts/metrics.py'; saved = path.read_bytes()
        path.write_bytes(saved + b'\n# changed\n')
        self.assert_reason('mismatch', self.owner().__enter__)
        path.unlink()
        self.assert_reason('incomplete', self.owner().__enter__)
        path.write_bytes(saved)
        for name in ('scripts/books.py', 'scripts/paths.py', 'scripts/diagnostics.py', 'scripts/book_batch.py'):
            expected = self.manifest['originals']['sources'].pop(name); self.write_manifest()
            self.assert_reason('incomplete', self.owner().__enter__)
            self.manifest['originals']['sources'][name] = expected
        self.write_manifest()
        with self.owner() as inputs:
            self.assertFalse((inputs.source_snapshot / 'raw').exists())

    def test_unsupported_source_imports_or_syntax_never_attach_unrecorded_modules(self):
        path = self.source / 'scripts/metrics.py'; original = path.read_bytes()
        for appended in (b'\nimport missing_unrecorded_dependency\n', b'\nfrom . import policy\n',
                         b'\n__import__("hidden")\n', b'\nthis is invalid syntax!\n'):
            path.write_bytes(original + appended)
            self.manifest['originals']['sources']['scripts/metrics.py'] = sha(path)
            self.write_manifest()
            with self.assertRaises(execution.ExecutionInputError) as caught:
                self.owner().__enter__()
            self.assertIn(caught.exception.reason, ('incomplete', 'unsupported'))
        path.write_bytes(original); self.manifest['originals']['sources']['scripts/metrics.py'] = sha(path); self.write_manifest()
        with self.owner(): pass

    def test_path_traversal_absolute_paths_and_output_overlap_reject(self):
        for name in ('../escape.py', '/escape.py', 'scripts/../escape.py', 'scripts//books.py',
                     'C:/escape.py', 'scripts\\books.py', 'scripts/./books.py'):
            self.manifest['originals']['sources'][name] = 'a' * 64; self.write_manifest()
            self.assert_reason('unsupported', self.owner().__enter__)
            del self.manifest['originals']['sources'][name]
        self.write_manifest()
        for output in (self.source, self.source / 'child', self.capture, self.capture / 'child', self.root):
            self.assert_reason('unsupported', lambda: self.owner(output))
        for invalid in (None, 123):
            self.assert_reason('unsupported', lambda: execution.CapturedWorkspace(invalid, self.source, self.output))
        self.assertFalse((self.source / 'owner.lock').exists())
        self.assertFalse((self.capture / 'owner.lock').exists())

    def test_existing_foreign_experiment_directory_is_preserved_and_rejected(self):
        self.output.mkdir()
        path = self.output / 'foreign.txt'; path.write_bytes(b'preserve')
        self.assert_reason('unsupported', self.owner().__enter__)
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()},
                         {'foreign.txt': b'preserve'})
        path.unlink()
        self.assert_reason('unsupported', self.owner().__enter__)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_symlink_source_capture_and_output_escapes_reject(self):
        path = self.source / 'scripts/metrics.py'; saved = path.read_bytes(); path.unlink()
        outside = self.root / 'outside.py'; outside.write_bytes(saved)
        try:
            path.symlink_to(outside)
        except OSError:
            path.write_bytes(saved)
            self.skipTest('Symlink creation unavailable')
        self.assert_reason('unsupported', self.owner().__enter__)
        path.unlink(); path.write_bytes(saved)
        alias = self.root / 'alias'; alias.symlink_to(self.capture, target_is_directory=True)
        self.assert_reason('unsupported', lambda: execution.CapturedWorkspace(alias, self.source, self.output))
        alias.unlink(); alias.symlink_to(self.root / 'other', target_is_directory=True)
        self.assert_reason('unsupported', lambda: self.owner(alias))
        alias.unlink()
        (self.output / 'owner.lock').unlink()
        (self.output / 'owner.lock').symlink_to(outside)
        self.assert_reason('unsupported', self.owner().__enter__)
        self.assertEqual(outside.read_bytes(), saved)

    def test_sidecars_and_extra_capture_files_reject_without_removal(self):
        for name in ('schedules.sqlite-wal', 'research.sqlite-journal', 'capture.extra'):
            path = self.capture / name; path.write_bytes(b'evidence')
            self.assert_reason('incomplete', self.owner().__enter__)
            self.assertEqual(path.read_bytes(), b'evidence'); path.unlink()

    def test_no_runtime_discovery_engine_imports_or_database_fallback(self):
        imported = []
        original_import = builtins.__import__
        def guarded(name, *args, **kwargs):
            imported.append(name)
            if name in ('research', 'schedules', 'baseline', 'cache_access', 'run', 'runtime_access', 'bench_metrics'):
                raise AssertionError('Unexpected financial import: ' + name)
            return original_import(name, *args, **kwargs)
        spec = importlib.util.spec_from_file_location('independent_workspace_module', ROOT / 'tools/bench_execution_inputs.py')
        module = importlib.util.module_from_spec(spec)
        with patch('builtins.__import__', side_effect=guarded): spec.loader.exec_module(module)
        connections = []
        connect = sqlite3.connect
        def observed(path, *args, **kwargs):
            connections.append(path)
            return connect(path, *args, **kwargs)
        with patch.object(sqlite3, 'connect', side_effect=observed):
            with module.CapturedWorkspace(self.capture, self.source, self.output) as inputs:
                with inputs.writable_daily(): pass
        self.assertEqual(len(connections), 3)
        self.assertTrue(all(str(self.root.as_uri()) in value for value in connections))
        self.assertTrue(all('mode=ro' in value for value in connections[:2]))
        self.assertIn('mode=rw', connections[2])
        self.assertFalse((self.source / 'raw').exists())
        self.assertFalse((self.source / 'data').exists())

    def test_import_and_attachment_do_not_change_closed_admission(self):
        import bench_admission
        with self.owner():
            with self.assertRaises(bench_admission.BenchmarkAdmissionError): bench_admission.require_execution()
        with self.assertRaises(bench_admission.BenchmarkAdmissionError): bench_admission.require_execution()

    def test_frozen_pre_extraction_store_and_capture_semantic_identities(self):
        fixture = store.InputStore(self.root / 'identity-fixture')
        with fixture.produce(EVIDENCE) as producer: fill(producer)
        with fixture.open(producer.generation_id) as inputs:
            self.assertEqual(inputs.identity, '2996e3db84abd70ffd0bafd0f134326ed50228fc8a5a6804d5ae136e175f24bd')
            self.assertEqual(semantic(inputs.research, inputs.daily, EVIDENCE['sources']),
                '0bfceceb30c29e92b35d55def70074382c4de2bebe8338ed4e81bd0900a06668')


if __name__ == '__main__':
    unittest.main()

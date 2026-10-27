"""Stopped-runtime capture proofs on disposable fixtures; no real cache reads."""
import ast
from contextlib import contextmanager, closing
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if '--runtime' in sys.argv:
    index = sys.argv.index('--runtime'); del sys.argv[index:index + 2]
sys.path.insert(0, str(ROOT / 'tools'))
import bench_capture_offline as capture
from test_bench_input_store import RESEARCH_SCHEMA, DAILY_SCHEMA, REPORT, fill, metadata


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cb02-offline-capture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'runtime'
        for name in ('scripts', 'website', 'raw/px', 'raw/financial-inputs/income', 'data', 'results', 'tmp'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        for path in (ROOT / 'scripts').glob('*.py'):
            shutil.copy2(path, self.root / 'scripts' / path.name)
        shutil.copy2(ROOT / 'website/runtime_access.py', self.root / 'website/runtime_access.py')
        for name in ('universe.json', 'metrics.jsonl', 'spy-div.json', 'treasury.json'):
            (self.root / 'raw' / name).write_text('[]')
        (self.root / 'raw/px/A.json').write_text('[]')
        (self.root / 'raw/financial-inputs/income/A.json').write_text('[]')
        with closing(sqlite3.connect(self.root / 'data/research.sqlite')) as research, closing(sqlite3.connect(self.root / 'data/schedules.sqlite')) as daily:
            producer = SimpleNamespace(research=research, daily=daily,
                write_report=lambda content: (self.root / capture.REPORT).write_bytes(content))
            fill(producer)
            self.freshen(research, daily)
            daily.execute("INSERT INTO periods VALUES(1,'2025-06-02','2025-06-03',0.1,0.04,1,1)")
            daily.execute("INSERT INTO period_pools VALUES(1,'legacy')")
            daily.commit()
        self.manifest = self.root / 'data/deployment.json'
        sources = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for directory in ('scripts', 'website') for p in (self.root / directory).glob('*.py')}
        self.manifest.write_text(json.dumps(dict(commit='a' * 40, files=sources)))
        self.destination = self.root / 'tmp/experiment'

    def freshen(self, research, daily):
        observed = capture.freshness(self.root, capture.Budget(None, None))
        metadata(research, dict(inputs=observed['inputs'], prices=observed['prices']))
        metadata(daily, dict(daily_inputs=observed['daily_inputs']))
        research.commit(); daily.commit()

    def snapshot(self):
        paths = [self.root / value for value in (*capture.DATABASES.values(), capture.REPORT)]
        return {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_size, p.stat().st_mtime_ns) for p in paths}

    def run_capture(self, **kwargs):
        return capture.capture_offline(self.root, self.destination, **kwargs)

    def assert_reason(self, reason, operation):
        with self.assertRaises(capture.OfflineCaptureError) as caught:
            operation()
        self.assertEqual(caught.exception.reason, reason)

    def test_complete_copy_preserves_original_bytes_metadata_and_saved_books(self):
        before = self.snapshot(); events = []
        published = self.run_capture(progress=events.append)
        self.assertEqual(before, self.snapshot())
        self.assertEqual((published / 'report.txt').read_bytes(), REPORT)
        receipt = json.loads((published / 'capture.json').read_bytes())
        self.assertTrue(receipt['originals_unchanged']); self.assertFalse(receipt['benchmark_admitted'])
        self.assertEqual(receipt['installed_revision'], 'a' * 40)
        self.assertEqual(len(receipt['financial_generation']), 64)
        for name in capture.DATABASES:
            path = published / name
            self.assertEqual(receipt['artifacts'][name]['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        with closing(sqlite3.connect(published / 'schedules.sqlite')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM periods').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT * FROM period_pools').fetchall(), [(1, 'legacy')])
        self.assertIn('backup_progress', [event['event'] for event in events])
        moved = published.with_name('closed-copy'); published.rename(moved)
        for path in moved.iterdir(): path.unlink()
        moved.rmdir()

    def test_source_then_cache_ownership_and_handles_close_before_release(self):
        source_owner = capture.runtime_access.ownership
        cache_owner = capture.cache_access.WorkspaceAccess
        order = []
        @contextmanager
        def source(root, **kwargs):
            self.assertEqual(kwargs, dict(exclusive=True, timeout=0))
            with source_owner(root, **kwargs):
                order.append('source-in'); yield; order.append('source-out')
        class Access:
            def __init__(self, path): self.owner = cache_owner(path)
            @contextmanager
            def hold(inner, **kwargs):
                self.assertEqual(kwargs, dict(timeout=0))
                with inner.owner.hold(**kwargs):
                    order.append('cache-in'); yield; order.append('cache-out')
        with patch.object(capture.runtime_access, 'ownership', source), patch.object(capture.cache_access, 'WorkspaceAccess', Access):
            self.run_capture()
        self.assertEqual(order, ['source-in', 'cache-in', 'cache-out', 'source-out'])

    def test_source_holder_and_cache_holder_reject_without_waiting_or_output(self):
        for kind in ('source', 'cache'):
            owner = (capture.runtime_access.ownership(self.root) if kind == 'source' else
                     capture.cache_access.WorkspaceAccess(self.root / 'data/website-data-0.lock').hold())
            with self.subTest(kind=kind), owner:
                before = time.monotonic()
                self.assert_reason('busy', self.run_capture)
                self.assertLess(time.monotonic() - before, 2)
                self.assertFalse(self.destination.exists())

    def test_pending_journals_sidecars_and_wal_headers_reject_unchanged(self):
        for relative in ('data/deployment.pending.json', 'data/research.sqlite.publication.json',
                         'data/research.sqlite-wal', 'data/schedules.sqlite-shm', 'data/schedules.sqlite-journal'):
            path = self.root / relative; path.write_bytes(b'')
            with self.subTest(relative=relative):
                before = self.snapshot()
                self.assert_reason('pending' if relative.endswith('.json') else 'unsupported', self.run_capture)
                self.assertEqual(before, self.snapshot()); self.assertTrue(path.exists())
            path.unlink()
        path = self.root / 'data/schedules.sqlite'; content = path.read_bytes()
        changed = bytearray(content); changed[18:20] = b'\x02\x02'; path.write_bytes(changed)
        before = self.snapshot()
        self.assert_reason('unsupported', self.run_capture)
        self.assertEqual(before, self.snapshot())
        path.write_bytes(content)

    def test_active_original_transaction_is_refused_without_checkpoint_or_repair(self):
        path = self.root / 'data/schedules.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('UPDATE prices SET adjusted=99')
            journal = Path(str(path) + '-journal'); self.assertTrue(journal.exists())
            before = self.snapshot()
            self.assert_reason('unsupported', self.run_capture)
            self.assertEqual(before, self.snapshot()); self.assertTrue(db.in_transaction)
            db.rollback()
        self.assertFalse(self.destination.exists())

    def test_metadata_report_shared_rows_and_freshness_mismatches_reject(self):
        for defect in ('metadata', 'report', 'shared', 'stale'):
            with self.subTest(defect=defect):
                if defect == 'report':
                    (self.root / capture.REPORT).write_bytes(REPORT + b'revised\n')
                elif defect == 'stale':
                    (self.root / 'raw/financial-inputs/income/A.json').write_text('[1]')
                else:
                    with closing(sqlite3.connect(self.root / 'data/schedules.sqlite')) as db:
                        if defect == 'metadata': metadata(db, dict(daily_inputs=dict(version=3, inputs={}, engine={})))
                        else: db.execute("UPDATE companies SET name='different'")
                        db.commit()
                before = self.snapshot()
                with self.assertRaises(capture.OfflineCaptureError): self.run_capture()
                self.assertEqual(before, self.snapshot())
                # Each defect uses a fresh fixture and destination.
                self.tearDown_fixture_for_loop()

    def tearDown_fixture_for_loop(self):
        # All current fixtures are owned by this test. Retain earlier failed
        # attempt evidence while constructing an independent next runtime.
        previous = self.root
        self.setUp()
        self.assertTrue(previous.exists())

    def test_cancel_and_publication_failure_preserve_originals_and_prior_destination(self):
        before = self.snapshot()
        state = False
        def progress(event):
            nonlocal state
            if event['event'] == 'backup_start': state = True
        self.assert_reason('cancelled', lambda: self.run_capture(cancel=lambda: state, progress=progress))
        self.assertEqual(before, self.snapshot())
        failure = json.loads((self.destination / 'failure.json').read_bytes())
        self.assertEqual(failure['reason'], 'cancelled')
        evidence = json.loads((self.destination / 'originals-before.json').read_bytes())
        self.assertEqual(evidence['assets']['data/research.sqlite']['sha256'],
                         hashlib.sha256(before['data/research.sqlite'][0]).hexdigest())
        previous = {p.relative_to(self.destination).as_posix(): p.read_bytes() for p in self.destination.rglob('*') if p.is_file()}
        self.assert_reason('unsupported', self.run_capture)
        self.assertEqual(previous, {p.relative_to(self.destination).as_posix(): p.read_bytes() for p in self.destination.rglob('*') if p.is_file()})
        self.destination = self.root / 'tmp/failure'
        with patch.object(Path, 'rename', side_effect=OSError('private exception body')):
            with self.assertRaises(OSError): self.run_capture()
        self.assertEqual(before, self.snapshot())
        failure = (self.destination / 'failure.json').read_text()
        self.assertNotIn('private exception body', failure)
        self.assertEqual(json.loads(failure)['reason'], 'unexpected')

    def test_changed_original_during_copy_rejects_publication(self):
        def progress(event):
            if event['event'] == 'destination_verified':
                (self.root / capture.REPORT).write_bytes(REPORT + b'manual change\n')
        self.assert_reason('changed-original', lambda: self.run_capture(progress=progress))
        self.assertEqual(list(self.destination.glob('capture-*')), [])

    def test_current_source_manifest_mismatch_and_unsupported_schema_reject(self):
        manifest = json.loads(self.manifest.read_bytes()); manifest['files']['scripts/metrics.py'] = '0' * 64
        self.manifest.write_text(json.dumps(manifest))
        self.assert_reason('stale', self.run_capture)
        self.destination = self.root / 'tmp/schema'
        manifest['files']['scripts/metrics.py'] = hashlib.sha256((self.root / 'scripts/metrics.py').read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps(manifest))
        with closing(sqlite3.connect(self.root / 'data/research.sqlite')) as db:
            db.execute('DROP TABLE statements'); db.commit()
        self.assert_reason('unsupported', self.run_capture)

    def test_malformed_metadata_and_database_body_fail_as_unsupported(self):
        with closing(sqlite3.connect(self.root / 'data/schedules.sqlite')) as db:
            metadata(db, dict(daily_inputs=None)); db.commit()
        self.assert_reason('unsupported', self.run_capture)
        self.destination = self.root / 'tmp/body-corruption'
        path = self.root / 'data/research.sqlite'
        contents = bytearray(path.read_bytes())
        contents[100:] = b'X' * (len(contents) - 100)
        path.write_bytes(contents)
        before = self.snapshot()
        self.assert_reason('unsupported', self.run_capture)
        self.assertEqual(before, self.snapshot())

    def test_path_and_resource_caps_fail_closed(self):
        for destination in (self.root / 'data/copy', self.root / 'raw/copy', self.root / 'tmp', self.root.parent / 'outside'):
            self.assert_reason('unsupported', lambda: capture.capture_offline(self.root, destination))
        for name, value in (('MAX_DATABASE_BYTES', 1), ('MAX_MEMORY_BYTES', 1), ('MAX_SECONDS', -1), ('MAX_OUTPUT_BYTES', 1)):
            self.destination = self.root / 'tmp' / name
            with self.subTest(name=name), patch.object(capture, name, value):
                self.assert_reason('limit', self.run_capture)

    def test_explicit_root_freshness_matches_authoritative_functions(self):
        def isolated(module, name, namespace):
            tree = ast.parse((self.root / 'scripts' / (module + '.py')).read_text())
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            exec(compile(ast.Module(body=[function], type_ignores=[]), '<isolated fixture function>', 'exec'), namespace)
            return namespace[name]
        baseline_namespace = dict(re=re, date=date, run=SimpleNamespace(ASOF=capture.constant(self.root, 'run', 'ASOF')))
        cutoff = isolated('baseline', 'cutoff', baseline_namespace)
        namespace = dict(ROOT=self.root, RAW=self.root / 'raw', RESULTS=self.root / 'results', Path=Path,
                         __file__=str(self.root / 'scripts/research.py'), baseline=SimpleNamespace(cutoff=cutoff, __file__=str(self.root / 'scripts/baseline.py')))
        for name in ('metrics', 'books', 'cache_assets', 'run', 'revalue', 'financial_inputs'):
            namespace[name] = SimpleNamespace(__file__=str(self.root / 'scripts' / (name + '.py')))
        signature = isolated('research', 'signature', namespace)
        prices = isolated('research', 'price_sources', namespace)
        fingerprint = isolated('schedules', 'fingerprint', dict(Path=Path, VERSION=3,
            __file__=str(self.root / 'scripts/schedules.py'), r=SimpleNamespace(signature=signature),
            schedule_calendar=SimpleNamespace(__file__=str(self.root / 'scripts/schedule_calendar.py')),
            portfolio_results=SimpleNamespace(__file__=str(self.root / 'scripts/portfolio_results.py'))))
        for change in ('initial', 'added', 'removed', 'cutoff', 'calendar', 'portfolio'):
            if change == 'added': (self.root / 'raw/financial-inputs/income/B.json').write_text('{}')
            elif change == 'removed': (self.root / 'raw/financial-inputs/income/B.json').unlink()
            elif change == 'cutoff': (self.root / capture.REPORT).write_text('Through 2025-12-31\n')
            elif change == 'calendar':
                path=self.root / 'scripts/schedule_calendar.py'
                path.write_bytes(path.read_bytes()+b'\n# changed calendar fixture\n')
            elif change == 'portfolio':
                path=self.root / 'scripts/portfolio_results.py'
                path.write_bytes(path.read_bytes()+b'\n# changed result fixture\n')
            observed = capture.freshness(self.root, capture.Budget(None, None))
            self.assertEqual(observed, dict(inputs=signature(), prices=prices(), daily_inputs=fingerprint()))


if __name__ == '__main__':
    unittest.main()

"""Synthetic-only owned handoffs. No runtime import, raw cache or live capture."""
import ast
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if '--runtime' in sys.argv:
    index = sys.argv.index('--runtime')
    del sys.argv[index:index + 2]
sys.path.insert(0, str(ROOT / 'tools'))
import bench_input_store as store


def source_constant(path, name):
    """Read schemas as data. Do not import application globals or bootstrap."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return ast.literal_eval(next(node.value for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
        and target.id == name for target in node.targets)))


RESEARCH_SCHEMA = source_constant(ROOT / 'backtest/inputs/research.py', 'SCHEMA')
POOL_SCHEMA = source_constant(ROOT / 'backtest/inputs/daily.py', 'POOL_SCHEMA')
# The real daily schema is research schema + its literal extension + pool schema.
_schedule_tree = ast.parse((ROOT / 'backtest/inputs/daily.py').read_text(encoding='utf-8'))
_daily_expr = next(node.value for node in _schedule_tree.body if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in node.targets))
DAILY_SCHEMA = RESEARCH_SCHEMA + ast.literal_eval(_daily_expr.left.right) + POOL_SCHEMA
REPORT = b'Through 2026-10-21\nSynthetic verified report\n'
EVIDENCE = dict(sources={'scripts/metrics.py': 'a' * 64},
                policy_sha256='b' * 64, catalog_sha256='c' * 64)


def metadata(db, values):
    db.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',
                   ((key, json.dumps(value)) for key, value in values.items()))


def fill(producer, *, generation='fixture-1', wal=False):
    producer.research.executescript(RESEARCH_SCHEMA)
    producer.daily.executescript(DAILY_SCHEMA)
    inventory = dict(fixture_generation=generation, historical_through='2026-10-21')
    for db in (producer.research, producer.daily):
        if wal:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
        db.execute("INSERT INTO companies VALUES('A','A','NYSE','Energy')")
        db.execute("INSERT INTO statements VALUES('A','2024-12-31','2025-03-31',150e6,180e6,60e6,0.3333333333333333)")
        db.execute("INSERT INTO financial_inputs VALUES('A','2024-12-31','{}')")
    metadata(producer.research, dict(version=store.RESEARCH_VERSION, inputs=inventory,
        prices={'A.json': [100, 1234]}, baseline_report_sha=hashlib.sha256(REPORT).hexdigest()))
    metadata(producer.daily, dict(daily_inputs=dict(version=store.DAILY_VERSION,
        inputs=inventory, engine={'schedules.py': [123, 456]}), cached_symbols=['A']))
    producer.daily.execute("INSERT INTO prices VALUES('A','2025-06-02',10,10)")
    producer.daily.execute("INSERT INTO sessions VALUES('2025-06-02',100)")
    producer.daily.execute("INSERT INTO treasuries VALUES('2025-06-02',0.04)")
    producer.research.commit(); producer.daily.commit()
    producer.write_report(REPORT)


class InputStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cb02-input-store-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = store.InputStore(self.root / 'store')

    def produce(self, **kwargs):
        with self.store.produce(EVIDENCE) as producer:
            fill(producer, **kwargs)
        return producer.generation_id

    def folder(self, identifier):
        return self.store.root / 'generations' / identifier

    def assert_reason(self, reason, function):
        with self.assertRaises(store.InputStoreError) as caught:
            function()
        self.assertEqual(caught.exception.reason, reason)

    def test_real_schema_versions_and_owned_handoff_readonly_and_closure(self):
        self.assertEqual(store.RESEARCH_VERSION, 7)  # Historical capture remains schema 7.
        self.assertEqual(source_constant(ROOT / 'backtest/inputs/research.py', 'SCHEMA_VERSION'), 8)
        self.assertEqual(store.DAILY_VERSION, source_constant(ROOT / 'backtest/inputs/daily.py', 'VERSION'))
        identifier = self.produce()
        with self.store.open(identifier) as inputs:
            self.assertEqual(inputs.report, REPORT)
            self.assertEqual(inputs.daily.execute('SELECT COUNT(*) FROM prices').fetchone()[0], 1)
            self.assertEqual(len(inputs.identity), 64)
            daily, research = inputs.daily, inputs.research
            for db in (daily, research):
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute('DELETE FROM companies')
        for db in (daily, research):
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
        moved = self.folder(identifier).with_name('closed-generation')
        self.folder(identifier).rename(moved)
        for path in moved.iterdir():
            path.unlink()
        moved.rmdir()

    def test_writable_clone_changes_only_owned_books_and_preserves_base_identity(self):
        identifier = self.produce()
        before = {p.name: p.read_bytes() for p in self.folder(identifier).iterdir()}
        with self.store.open(identifier) as inputs:
            with inputs.writable_daily() as daily:
                daily.execute("INSERT INTO periods VALUES(1,'2025-06-02','2025-06-03',0.1,0.04,1,1)")
                daily.execute("INSERT INTO period_pools VALUES(1,'legacy')")
                daily.commit()
                semantic = store._coherence(inputs.research, daily,
                    hashlib.sha256(REPORT).hexdigest(), EVIDENCE, store._Budget(None), fresh=False)
                self.assertEqual(semantic, inputs.identity)
                self.assertEqual(inputs.daily.execute('SELECT COUNT(*) FROM periods').fetchone()[0], 0)
            with self.assertRaises(sqlite3.ProgrammingError):
                daily.execute('SELECT 1')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder(identifier).iterdir()})
        runs = list((self.store.root / 'runs').iterdir())
        self.assertEqual(len(runs), 1)
        with closing(sqlite3.connect(runs[0] / 'daily.sqlite')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM periods').fetchone()[0], 1)

    def test_no_wait_ownership_across_store_instances_and_threads(self):
        identifier = self.produce()
        other = store.InputStore(self.store.root)
        errors = []
        def probe():
            try:
                with other.open(identifier):
                    errors.append('admitted')
            except store.InputStoreError as error:
                errors.append(error.reason)
        with self.store.open(identifier):
            began = time.monotonic()
            thread = Thread(target=probe); thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertLess(time.monotonic() - began, 2)
            self.assertEqual(errors, ['busy'])
        with other.open(identifier):
            pass

    def test_os_lock_is_nonblocking_independent_of_thread_registry(self):
        identifier = self.produce()
        other = store.InputStore(self.store.root)
        from threading import Lock
        other._thread_lock = Lock()  # exercise the actual file-lock layer too
        with self.store.open(identifier):
            self.assert_reason('busy', lambda: other.open(identifier).__enter__())
        with other.open(identifier):
            pass

    def test_mixed_metadata_base_rows_report_and_schema_reject(self):
        for defect in ('inventory', 'base', 'report', 'version', 'schema'):
            with self.subTest(defect=defect), self.assertRaises(store.InputStoreError):
                with self.store.produce(EVIDENCE) as producer:
                    fill(producer)
                    if defect == 'inventory':
                        metadata(producer.daily, dict(daily_inputs=dict(version=3, inputs={'other': 1}, engine={'x': 1})))
                    elif defect == 'base':
                        producer.daily.execute("UPDATE statements SET ebitda=70e6")
                    elif defect == 'report':
                        producer.write_report(b'Through 2026-10-21\nOther report\n')
                    elif defect == 'version':
                        metadata(producer.research, {'version': -1})
                    else:
                        producer.daily.execute('DROP TABLE sessions')
                    producer.daily.commit(); producer.research.commit()
        self.assertEqual(list((self.store.root / 'generations').iterdir()), [])

    def test_incomplete_evidence_staging_journal_and_nonempty_books_reject(self):
        self.assert_reason('incomplete', lambda: self.store.produce({}).__enter__())
        for defect in ('report', 'journal', 'books', 'tables'):
            with self.subTest(defect=defect), self.assertRaises(store.InputStoreError):
                with self.store.produce(EVIDENCE) as producer:
                    if defect != 'tables':
                        fill(producer)
                    if defect == 'report':
                        (producer.folder / 'report.txt').unlink()
                    elif defect == 'journal':
                        (producer.folder / 'research.sqlite.publication.json').write_text('{}')
                    elif defect == 'books':
                        producer.daily.execute("INSERT INTO periods VALUES(1,'2025-01-01','2026-01-01',0,0,1,1)")
                        producer.daily.commit()
        self.assertEqual(list((self.store.root / 'generations').iterdir()), [])

    def test_uncommitted_transactions_reject_and_close_without_publishing(self):
        with self.assertRaises(store.InputStoreError) as caught:
            with self.store.produce(EVIDENCE) as producer:
                fill(producer)
                producer.daily.execute("UPDATE prices SET price=99")
        self.assertEqual(caught.exception.reason, 'incomplete')
        with self.assertRaises(sqlite3.ProgrammingError):
            producer.daily.execute('SELECT 1')
        self.assertIsNone(producer.generation_id)
        self.assertEqual(list((self.store.root / 'generations').iterdir()), [])

    def test_wal_committed_rows_are_preserved_and_owned_backup_works(self):
        with self.store.produce(EVIDENCE) as producer:
            fill(producer, wal=True)
            self.assertTrue((producer.folder / 'daily.sqlite-wal').exists())
            self.assertEqual(producer.daily.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            producer.daily.execute("INSERT INTO prices VALUES('A','2025-06-03',11,11)")
            producer.daily.commit()
        with self.store.open(producer.generation_id) as inputs:
            with inputs.writable_daily() as daily:
                self.assertEqual(daily.execute('SELECT adjusted FROM prices WHERE day=?', ('2025-06-03',)).fetchone()[0], 11)
        self.assertEqual({p.name for p in producer.folder.parent.parent.joinpath('generations', producer.generation_id).iterdir()},
                         set(store.ARTIFACTS) | {'manifest.json'})

    def test_cancelled_and_failed_publication_keep_previous_generation_and_evidence(self):
        identifier = self.produce()
        before = {p.name: p.read_bytes() for p in self.folder(identifier).iterdir()}
        cancelled = False
        with self.assertRaises(store.InputStoreError) as caught:
            with self.store.produce(EVIDENCE, cancel=lambda: cancelled) as producer:
                fill(producer)
                cancelled = True
        self.assertEqual(caught.exception.reason, 'cancelled')
        with patch.object(Path, 'rename', side_effect=OSError('private body must not be saved')):
            with self.assertRaises(OSError):
                self.produce(generation='fixture-2')
        records = [json.loads(p.read_bytes()) for p in (self.store.root / 'failures').iterdir()]
        self.assertEqual({r['reason'] for r in records}, {'cancelled', 'unexpected'})
        self.assertTrue(all(set(r) == {'attempt', 'reason', 'error_type'} for r in records))
        self.assertNotIn('private body', json.dumps(records))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder(identifier).iterdir()})
        with self.store.open(identifier):
            pass

    def test_artifact_damage_manifest_identity_and_sidecar_reject(self):
        for defect in ('artifact', 'identity', 'manifest', 'sidecar'):
            identifier = self.produce()
            folder = self.folder(identifier)
            with self.subTest(defect=defect):
                if defect == 'artifact':
                    (folder / 'daily.sqlite').write_bytes(b'corrupt')
                elif defect == 'sidecar':
                    (folder / 'daily.sqlite-journal').write_bytes(b'pending')
                else:
                    path = folder / 'manifest.json'
                    if defect == 'manifest':
                        path.write_text('{broken')
                    else:
                        manifest = json.loads(path.read_bytes()); manifest['identity'] = '0' * 64
                        path.write_text(json.dumps(manifest))
                with self.assertRaises(store.InputStoreError):
                    with self.store.open(identifier):
                        self.fail('Damaged generation admitted')

    def test_size_memory_deadline_and_cancel_checkpoints_reject(self):
        for target, value in (('_MAX_DATABASE_BYTES', 1), ('_MAX_OUTPUT_BYTES', 1),
                              ('_MAX_MEMORY_BYTES', 1), ('_MAX_SECONDS', -1)):
            with self.subTest(target=target), patch.object(store, target, value):
                with self.assertRaises(store.InputStoreError) as caught:
                    self.produce()
                self.assertEqual(caught.exception.reason, 'limit')
        self.assertEqual(list((self.store.root / 'generations').iterdir()), [])

    def test_cancel_during_backup_preserves_input_and_closes_target(self):
        identifier = self.produce()
        state = False
        with self.store.open(identifier, cancel=lambda: state) as inputs:
            original = store._Budget.backup_progress
            def cancel_at_page(budget, *args):
                nonlocal state
                state = True
                original(budget, *args)
            with patch.object(store._Budget, 'backup_progress', cancel_at_page):
                with self.assertRaises(store.InputStoreError) as caught:
                    with inputs.writable_daily():
                        self.fail('Cancelled backup yielded')
                self.assertEqual(caught.exception.reason, 'cancelled')
        state = False
        with self.store.open(identifier):
            pass
        for path in (self.store.root / 'runs').glob('*/daily.sqlite'):
            path.rename(path.with_suffix('.closed'))

    def test_original_synthetic_writers_progress_while_reading_published_handoff(self):
        identifier = self.produce()
        original = store.InputStore(self.root / 'original')
        outcomes = []
        errors = []
        with original.produce(EVIDENCE) as producer:
            fill(producer)
            def writer():
                try:
                    with ExitStack() as connections:
                        databases = []
                        for name in ('research.sqlite', 'daily.sqlite'):
                            db = sqlite3.connect(producer.folder / name, timeout=0)
                            connections.callback(db.close); databases.append(db)
                        for number in range(2, 12):
                            for db in databases:
                                db.execute('UPDATE companies SET name=?', (str(number),)); db.commit()
                            outcomes.append(number)
                except BaseException as error:
                    errors.append(type(error).__name__)
            with self.store.open(identifier) as inputs:
                inputs.daily.execute('BEGIN')
                inputs.daily.execute('SELECT * FROM prices').fetchall()
                thread = Thread(target=writer); thread.start(); thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(outcomes, list(range(2, 12)))
                self.assertEqual(inputs.daily.execute('SELECT name FROM companies').fetchone()[0], 'A')
                inputs.daily.rollback()

    def test_negative_rollback_reader_delays_original_writer_commit(self):
        path = self.root / 'rollback.sqlite'
        with ExitStack() as resources:
            reader = sqlite3.connect(path, timeout=0); resources.callback(reader.close)
            writer = sqlite3.connect(path, timeout=0); resources.callback(writer.close)
            reader.execute('PRAGMA journal_mode=DELETE')
            reader.execute('CREATE TABLE state(value INTEGER)')
            reader.execute('INSERT INTO state VALUES(1)'); reader.commit()
            reader.execute('BEGIN'); reader.execute('SELECT * FROM state').fetchall()
            writer.execute('UPDATE state SET value=2')
            with self.assertRaises(sqlite3.OperationalError):
                writer.commit()
            self.assertTrue(writer.in_transaction)
            reader.rollback(); writer.commit()
            self.assertEqual(reader.execute('SELECT value FROM state').fetchone()[0], 2)

    def test_unexpected_builder_failure_is_preserved_and_sanitized(self):
        with self.assertRaisesRegex(RuntimeError, 'producer failure'):
            with self.store.produce(EVIDENCE):
                raise RuntimeError('producer failure')
        record = json.loads(next((self.store.root / 'failures').iterdir()).read_bytes())
        self.assertEqual(record['reason'], 'unexpected')
        self.assertEqual(record['error_type'], 'RuntimeError')
        self.assertNotIn('producer failure', json.dumps(record))

    def test_outer_owner_closes_escaped_clone_before_releasing_store(self):
        identifier = self.produce()
        with self.store.open(identifier) as inputs:
            clone = inputs.writable_daily()
            daily = clone.__enter__()
            daily.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError):
            daily.execute('SELECT 1')
        clone.__exit__(None, None, None)
        with self.store.open(identifier):
            pass
        self.assert_reason('incomplete', lambda: inputs.writable_daily().__enter__())

    def test_corruption_is_checked_even_with_refreshed_artifact_receipt(self):
        identifier = self.produce()
        folder = self.folder(identifier)
        database = folder / 'daily.sqlite'
        database.write_bytes(b'not sqlite')
        path = folder / 'manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest['artifacts']['daily.sqlite'] = dict(bytes=database.stat().st_size,
            sha256=hashlib.sha256(database.read_bytes()).hexdigest())
        path.write_text(json.dumps(manifest))
        with self.assertRaises(store.InputStoreError) as caught:
            with self.store.open(identifier):
                self.fail('Corrupt database admitted')
        self.assertEqual(caught.exception.reason, 'corrupt')

    def test_caller_sqlite_programming_failures_preserve_exception_identity(self):
        captured = []
        with self.assertRaises(sqlite3.OperationalError) as caught:
            with self.store.produce(EVIDENCE) as producer:
                try:
                    producer.daily.execute('THIS IS INVALID SQL')
                except sqlite3.OperationalError as error:
                    captured.append(error)
                    raise
        self.assertIs(caught.exception, captured[0])
        record = json.loads(next((self.store.root / 'failures').iterdir()).read_bytes())
        self.assertEqual(record['reason'], 'unexpected')
        self.assertEqual(record['error_type'], 'OperationalError')
        identifier = self.produce()
        with self.assertRaises(sqlite3.OperationalError) as caught:
            with self.store.open(identifier) as inputs:
                try:
                    inputs.daily.execute('SELECT missing FROM nonexistent')
                except sqlite3.OperationalError as error:
                    captured.append(error)
                    raise
        self.assertIs(caught.exception, captured[1])
        with self.store.open(identifier):
            pass

    def test_malformed_nested_manifest_receipts_are_contained(self):
        identifier = self.produce()
        path = self.folder(identifier) / 'manifest.json'
        original = path.read_bytes()
        changes = [
            ('artifacts', None), ('artifacts', []),
            ('identity', None), ('evidence', {'sources': None}),
        ]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                manifest = json.loads(original); manifest[key] = value
                path.write_text(json.dumps(manifest))
                self.assert_reason('incomplete', lambda: self.store.open(identifier).__enter__())
        for receipt in (None, [], {'bytes': None, 'sha256': 'a' * 64},
                        {'bytes': True, 'sha256': 'a' * 64},
                        {'bytes': -1, 'sha256': 'a' * 64},
                        {'bytes': 1, 'sha256': None},
                        {'bytes': 1, 'sha256': []},
                        {'bytes': 1, 'sha256': 'invalid'}):
            with self.subTest(receipt=receipt):
                manifest = json.loads(original)
                manifest['artifacts']['daily.sqlite'] = receipt
                path.write_text(json.dumps(manifest))
                self.assert_reason('incomplete', lambda: self.store.open(identifier).__enter__())
        path.write_bytes(b'\xff')
        self.assert_reason('incomplete', lambda: self.store.open(identifier).__enter__())
        path.write_bytes(original)
        with self.store.open(identifier):
            pass

    def test_malformed_nested_metadata_is_contained_at_artifact_boundary(self):
        identifier = self.produce()
        folder = self.folder(identifier)
        manifest_path = folder / 'manifest.json'
        original_manifest = manifest_path.read_bytes()
        database = folder / 'daily.sqlite'
        with closing(sqlite3.connect(database)) as db:
            saved = db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0]
        for value in (None, [], {'version': 3, 'inputs': {}, 'engine': []},
                      {'version': 3, 'inputs': {'invalid': float('nan')}, 'engine': {'x': 1}}):
            with self.subTest(value=value):
                with closing(sqlite3.connect(database)) as db:
                    db.execute("UPDATE metadata SET value=? WHERE key='daily_inputs'", (json.dumps(value),))
                    db.commit()
                manifest = json.loads(original_manifest)
                manifest['artifacts']['daily.sqlite'] = dict(bytes=database.stat().st_size,
                    sha256=hashlib.sha256(database.read_bytes()).hexdigest())
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaises(store.InputStoreError):
                    with self.store.open(identifier):
                        self.fail('Malformed metadata admitted')
        with closing(sqlite3.connect(database)) as db:
            db.execute("UPDATE metadata SET value=? WHERE key='daily_inputs'", (saved,)); db.commit()
        # SQLite layout may change after valid rewrites. Restore the valid
        # artifact receipt explicitly, then require semantic agreement again.
        manifest = json.loads(original_manifest)
        manifest['artifacts']['daily.sqlite'] = dict(bytes=database.stat().st_size,
            sha256=hashlib.sha256(database.read_bytes()).hexdigest())
        manifest_path.write_text(json.dumps(manifest))
        with self.store.open(identifier):
            pass

    def test_invalid_generation_identifier_never_resolves_outside_store(self):
        for identifier in ('../outside', 'A' * 32, '', None):
            self.assert_reason('incomplete', lambda: self.store.open(identifier).__enter__())


if __name__ == '__main__':
    unittest.main()

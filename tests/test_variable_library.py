"""Durable variable records in private synthetic stores; no application integration."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import subprocess
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from backtest.runtime import backtest_control
from backtest.variables import definitions as d, library
from test_variable_definitions import definition, constant, root, reference, binary


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'variable-library.sqlite'
        self.store = library.Store(self.path)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            return db.execute('SELECT * FROM entries ORDER BY variable_id').fetchall(), db.execute(
                'SELECT * FROM revisions ORDER BY variable_id,revision').fetchall()

    def test_construction_and_empty_list_do_not_create_store(self):
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.path.exists())
        self.assertEqual(library.DATABASE.name, 'variable-library.sqlite')
        self.assertEqual(library.DATABASE.parent.name, 'data')

    def test_create_persists_raw_content_and_detached_metadata(self):
        authored = definition(constant('1e100'))
        record = self.store.create(' Fictional variable ', authored, favourite=True)
        self.assertRegex(record['variable_id'], r'^var:[0-9a-f]{32}$')
        self.assertEqual(record['revision'], d.revision(authored))
        self.assertEqual(record['version'], 1)
        self.assertEqual(record['name'], 'Fictional variable')
        self.assertTrue(record['favourite'])
        self.assertFalse(record['deleted'])
        record['name'] = 'not persisted'
        authored['expression']['value'] = '2'
        reopened = library.Store(self.path)
        current = reopened.list()[0]
        self.assertEqual(current['name'], 'Fictional variable')
        _, revisions = self.rows()
        self.assertEqual(json.loads(revisions[0][2])['expression']['value'], '1e100')
        program = reopened.resolve([root(current)])
        self.assertEqual(len(d.require_program(program)['nodes'][0]['value']), 101)

    def test_formula_edits_create_immutable_revisions_and_can_reuse_old_revision(self):
        original = self.store.create('Original', definition())
        first_rows = self.rows()[1]
        updated = self.store.edit(original['variable_id'], 1, definition(constant('2')))
        self.assertEqual(updated['version'], 2)
        self.assertNotEqual(updated['revision'], original['revision'])
        reverted = self.store.edit(updated['variable_id'], 2, definition())
        self.assertEqual(reverted['revision'], original['revision'])
        self.assertEqual(reverted['version'], 3)
        self.assertEqual(len(self.rows()[1]), 2)
        self.assertIn(first_rows[0], self.rows()[1])
        for record, expected in ((original, '1'), (updated, '2')):
            self.assertEqual(self.store.resolve([root(record)]).to_dict()['nodes'][0]['value'], expected)

    def test_equivalent_formula_and_identical_metadata_are_noops(self):
        original = self.store.create('Original', definition(constant('8e-2')))
        before = self.rows()
        self.assertEqual(self.store.edit(original['variable_id'], 1, definition(constant('.08'))), original)
        self.assertEqual(self.store.rename(original['variable_id'], 1, 'Original'), original)
        self.assertEqual(self.store.favourite(original['variable_id'], 1, False), original)
        self.assertEqual(self.rows(), before)

    def test_name_and_favourite_versions_do_not_change_definition(self):
        original = self.store.create('Original', definition())
        before = self.rows()[1]
        named = self.store.rename(original['variable_id'], 1, 'Renamed')
        starred = self.store.favourite(original['variable_id'], 2, True)
        self.assertEqual((named['version'], starred['version']), (2, 3))
        self.assertEqual(starred['revision'], original['revision'])
        self.assertEqual(starred['created_at'], original['created_at'])
        self.assertEqual(self.rows()[1], before)
        program = self.store.resolve([root(original)])
        self.assertNotIn('Renamed', program.to_json())
        self.assertNotIn('favourite', program.to_json())

    def test_display_change_is_definition_content(self):
        original = self.store.create('Original', definition())
        changed = self.store.edit(original['variable_id'], 1, definition(display='percent'))
        self.assertNotEqual(changed['revision'], original['revision'])
        self.assertEqual(changed['version'], 2)

    def test_stale_versions_fail_across_independent_instances(self):
        original = self.store.create('Original', definition())
        other = library.Store(self.path)
        self.store.rename(original['variable_id'], 1, 'Renamed')
        for action in (lambda: other.rename(original['variable_id'], 1, 'Lost'),
                       lambda: other.favourite(original['variable_id'], 1, True),
                       lambda: other.edit(original['variable_id'], 1, definition()),
                       lambda: other.delete(original['variable_id'], 1)):
            with self.assertRaises(library.Conflict):
                action()
        self.assertEqual(other.get(original['variable_id'])['name'], 'Renamed')

    def test_concurrent_writers_publish_exactly_one_edit(self):
        original = self.store.create('Original', definition())
        barrier = Barrier(2)
        def change(value):
            store = library.Store(self.path)
            barrier.wait(timeout=5)
            try:
                return store.edit(original['variable_id'], 1, definition(constant(value)))
            except library.Conflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(change, ['2', '3']))
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(self.store.get(original['variable_id'])['version'], 2)
        self.assertEqual(len(self.rows()[1]), 2)

    def test_exact_references_survive_dependency_edit_and_deletion(self):
        a = self.store.create('Dependency', definition(constant('8e-2')))
        b = self.store.create('Consumer', definition(binary('add', reference(a), constant('2'))))
        changed = self.store.edit(a['variable_id'], 1, definition(constant('9')))
        self.store.delete(a['variable_id'], changed['version'])
        self.assertEqual([row['variable_id'] for row in self.store.list()], [b['variable_id']])
        program = library.Store(self.path).resolve([root(b)])
        self.assertEqual(len(d.require_program(program)['bundle']['definitions']), 2)
        self.assertIn('0.08', program.to_json())
        self.assertNotIn('"value":"9"', program.to_json())
        exact = self.store.resolve([root(a)])
        self.assertEqual(exact.to_dict()['nodes'][0]['value'], '0.08')

    def test_delete_hides_entry_without_destroying_revisions_or_detached_program(self):
        record = self.store.create('Original', definition())
        program = self.store.resolve([root(record)])
        before = program.to_json()
        deleted = self.store.delete(record['variable_id'], 1)
        self.assertTrue(deleted['deleted'])
        self.assertEqual(deleted['version'], 2)
        self.assertEqual(self.store.list(), [])
        for action in (lambda: self.store.get(record['variable_id']),
                       lambda: self.store.delete(record['variable_id'], 2),
                       lambda: self.store.edit(record['variable_id'], 2, definition())):
            with self.assertRaises(library.Missing):
                action()
        self.path.unlink()
        self.assertEqual(d.require_program(program), json.loads(before))

    def test_missing_reference_invalid_units_and_hash_forgery_roll_back(self):
        record = self.store.create('Original', definition())
        before = self.rows()
        absent = dict(variable_id='var:' + '0' * 32, revision='sha256:' + '0' * 64)
        for authored in (definition(reference(absent)), definition(constant('2', 'USD'))):
            with self.assertRaises(d.FormulaError):
                self.store.edit(record['variable_id'], 1, authored)
            self.assertEqual(self.rows(), before)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE revisions SET definition=?', (d.canonical(definition(constant('3'))),))
        with self.assertRaises(d.FormulaError) as caught:
            self.store.resolve([root(record)])
        self.assertEqual(caught.exception.code, 'REVISION_MISMATCH')
        with self.assertRaises(d.FormulaError):
            self.store.edit(record['variable_id'], 1, definition())

    def test_cancel_before_commit_rolls_back_and_releases_connection(self):
        record = self.store.create('Original', definition())
        before = self.rows()
        def cancel():
            # At the last checkpoint the mutation is visible only to its writer.
            with closing(sqlite3.connect(self.path)) as observer:
                self.assertEqual(observer.execute('SELECT name FROM entries').fetchone()[0], 'Original')
            if self.store.path.exists():
                raise backtest_control.Cancelled()
        with self.assertRaises(backtest_control.Cancelled):
            self.store.rename(record['variable_id'], 1, 'Lost', checkpoint=cancel)
        self.assertEqual(self.rows(), before)
        with patch.object(library, '_now', side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):
                self.store.edit(record['variable_id'], 1, definition(constant('2')))
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.store.rename(record['variable_id'], 1, 'Recovered')['version'], 2)

    def test_failure_after_sql_mutation_before_commit_keeps_previous_state(self):
        record = self.store.create('Original', definition())
        calls = []
        def cancel():
            calls.append(1)
            if len(calls) == 3:
                raise backtest_control.Cancelled()
        with self.assertRaises(backtest_control.Cancelled):
            self.store.rename(record['variable_id'], 1, 'Unpublished', checkpoint=cancel)
        self.assertEqual(self.store.get(record['variable_id']), record)
        self.assertEqual(len(calls), 3)

    def test_process_exit_before_and_after_commit_preserves_restart_state(self):
        record = self.store.create('Original', definition())
        code = '''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from backtest.variables import library
store=library.Store(sys.argv[2]); identity=sys.argv[3]
if sys.argv[4]=='before':
    count=[0]
    def checkpoint():
        count[0]+=1
        if count[0]==3:os._exit(41)
    store.rename(identity,1,'Unpublished',checkpoint=checkpoint)
else:
    store.rename(identity,1,'Committed');os._exit(42)
'''
        for mode, expected_code, expected_name, expected_version in (
                ('before', 41, 'Original', 1), ('after', 42, 'Committed', 2)):
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code,
                str(Path(__file__).resolve().parents[1]), str(self.path), record['variable_id'], mode],
                capture_output=True, timeout=20)
            self.assertEqual(result.returncode, expected_code, result.stderr.decode(errors='replace'))
            reopened = library.Store(self.path).get(record['variable_id'])
            self.assertEqual((reopened['name'], reopened['version']), (expected_name, expected_version))
        self.path.rename(self.path.with_name('released.sqlite'))

    def test_unknown_version_foreign_schema_and_corrupt_file_are_preserved(self):
        record = self.store.create('Original', definition())
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA user_version=99')
        before = self.path.read_bytes()
        for action in (self.store.list, lambda: self.store.get(record['variable_id']),
                       lambda: self.store.create('New', definition())):
            with self.assertRaises(library.InvalidStore):
                action()
            self.assertEqual(self.path.read_bytes(), before)
        self.path.unlink()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE unrelated (value TEXT)')
            db.execute("INSERT INTO unrelated VALUES('keep')")
        before = self.path.read_bytes()
        with self.assertRaises(library.InvalidStore):
            self.store.create('New', definition())
        self.assertEqual(self.path.read_bytes(), before)
        self.path.unlink()
        self.path.write_bytes(b'private invalid SQLite fixture')
        before = self.path.read_bytes()
        with self.assertRaises(library.InvalidStore):
            self.store.list()
        self.assertEqual(self.path.read_bytes(), before)

    def test_busy_storage_has_bounded_safe_error_without_mutation(self):
        record = self.store.create('Original', definition())
        with closing(sqlite3.connect(self.path)) as blocker, patch.object(library, 'WAIT_SECONDS', .02):
            blocker.execute('BEGIN IMMEDIATE')
            with self.assertRaises(library.Unavailable) as caught:
                self.store.rename(record['variable_id'], 1, 'Blocked')
            self.assertNotIn(str(self.path), str(caught.exception))
        self.assertEqual(self.store.get(record['variable_id']), record)

    def test_damaged_revision_json_and_oversized_content_fail_closed(self):
        record = self.store.create('Original', definition())
        for content in ('{bad', ' ' * (d.CEILINGS['bytes'] + 1)):
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('UPDATE revisions SET definition=?', (content,))
            with self.assertRaises(library.InvalidStore):
                self.store.resolve([root(record)])
            self.assertEqual(self.store.get(record['variable_id'])['revision'], record['revision'])

    def test_identical_edit_rejects_null_current_revision_without_mutation(self):
        record = self.store.create('Original', definition())
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE revisions SET definition=?', ('null',))
        before = self.rows()
        with self.assertRaises(library.InvalidStore):
            self.store.edit(record['variable_id'], record['version'], definition())
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.store.get(record['variable_id']), record)
        with self.assertRaises(library.InvalidStore):
            self.store.resolve([root(record)])

    def test_revert_rejects_null_archived_revision_without_mutation(self):
        original = self.store.create('Original', definition())
        current = self.store.edit(original['variable_id'], 1, definition(constant('2')))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE revisions SET definition=? WHERE revision=?',
                       ('null', original['revision']))
        before = self.rows()
        with self.assertRaises(library.InvalidStore):
            self.store.edit(current['variable_id'], current['version'], definition())
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.store.get(current['variable_id']), current)
        self.assertEqual(self.store.resolve([root(current)]).to_dict()['nodes'][0]['value'], '2')

    def test_user_variables_have_no_saved_backtest_capacity_or_automatic_eviction(self):
        records = [self.store.create('Fictional ' + str(index), definition()) for index in range(101)]
        self.assertEqual(len(self.store.list()), 101)
        self.assertEqual(library.Store(self.path).get(records[0]['variable_id']), records[0])
        self.assertEqual(len(self.rows()[1]), 101)

    def test_mutation_inputs_are_bounded_and_do_not_touch_existing_data(self):
        record = self.store.create('Original', definition())
        before = self.rows()
        for action in (lambda: self.store.create('', definition()),
                       lambda: self.store.rename(record['variable_id'], 1, 'x' * 121),
                       lambda: self.store.favourite(record['variable_id'], 1, 1),
                       lambda: self.store.edit(record['variable_id'], True, definition()),
                       lambda: self.store.delete('draft:wrong', 1)):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.rows(), before)

    def test_local_resolution_does_not_publish_any_revision(self):
        record = self.store.create('Original', definition())
        before = self.rows()
        authored = definition(binary('add', reference(record), constant('2')))
        local = dict(variable_id='draft:local', revision=d.revision(authored), definition=authored)
        program = self.store.resolve([root(local)], submitted=[local])
        self.assertEqual(len(d.require_program(program)['bundle']['definitions']), 2)
        self.assertEqual(self.rows(), before)

    def test_source_publication_preserves_variable_library_and_other_durable_assets(self):
        from tools.ops import deploy
        record = self.store.create('Retained variable', definition())
        runtime = Path(self.folder.name)
        payload = runtime / '.deployment' / 'private-stage' / 'payload'
        payload.mkdir(parents=True)
        (payload / 'README.md').write_text('Synthetic source publication fixture')
        durable = runtime / 'data'
        durable.mkdir()
        self.path.rename(durable / 'variable-library.sqlite')
        for name in ('saved-backtests.sqlite', 'backtest-queue.sqlite'):
            (durable / name).write_bytes(b'fictional durable data')
        before = {path.name: path.read_bytes() for path in durable.iterdir()}
        manifest = dict(version=1, commit='a' * 40,
                        files={'README.md': deploy.digest(payload / 'README.md')},
                        source='/private/fictional-source', distro='private-fixture')
        deploy.publish(runtime, payload, manifest)
        for name, content in before.items():
            self.assertEqual((durable / name).read_bytes(), content)
            self.assertFalse(deploy.managed('data/' + name))
        self.assertEqual(library.Store(durable / 'variable-library.sqlite').get(record['variable_id']), record)
        with self.assertRaises(ValueError):
            deploy.validate_manifest(dict(manifest, files={'data/variable-library.sqlite': 'b' * 64}))


if __name__ == '__main__':
    unittest.main()

"""Atomic detached captures in private synthetic stores and prepared-input fixtures."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from contextlib import closing, contextmanager
from copy import deepcopy
import json
import sqlite3
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

from backtest.runtime import backtest_control
from backtest.variables import definitions as d, library
from test_variable_definitions import definition, constant, entry, root, reference, binary


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'variables.sqlite'
        self.store = library.Store(self.path)
        self.a = self.store.create('Original', definition(constant('8e-2')))

    def capture(self, **kwargs):
        return self.store.capture([root(self.a)], **kwargs)

    def assert_error(self, code, call, *args, **kwargs):
        with self.assertRaises(d.FormulaError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def changed(self, capture, change):
        value = capture.to_dict()
        change(value)
        return library.VariableCapture(d.canonical(value))

    def test_capture_contains_complete_program_and_snapshot_presentation(self):
        captured = self.capture()
        value = library.require_capture(captured)
        self.assertEqual(value['format'], 'variable-capture')
        self.assertEqual(value['version'], 1)
        self.assertEqual(value['presentation'], [dict(root(self.a), name='Original',
            provenance=dict(source='library', version=1, deleted=False))])
        self.assertEqual(d.require_program(captured.program), value['program'])
        self.assertEqual(json.loads(captured.to_json()), value)
        self.assertNotIn('favourite', captured.to_json())

    def test_value_is_immutable_and_decoded_mutation_has_no_effect(self):
        capture = self.capture()
        before = capture.to_json()
        value = capture.to_dict()
        value['presentation'][0]['name'] = 'Changed'
        with self.assertRaises(AttributeError):
            capture.document = '{}'
        self.assertEqual(capture.to_json(), before)

    def test_names_change_capture_without_changing_program_or_bundle_revision(self):
        original = self.capture()
        named = self.store.rename(self.a['variable_id'], 1, 'Renamed')
        changed = self.capture()
        self.assertNotEqual(original.to_json(), changed.to_json())
        self.assertEqual(original.program, changed.program)
        self.assertEqual(changed.to_dict()['presentation'][0]['provenance']['version'], named['version'])
        starred = self.store.favourite(self.a['variable_id'], named['version'], True)
        favourite = self.capture()
        self.assertEqual(favourite.program, changed.program)
        self.assertEqual(favourite.to_dict()['presentation'][0]['provenance']['version'], starred['version'])
        self.assertNotIn('favourite', favourite.to_json())

    def test_capture_survives_edits_deletion_restart_and_database_removal(self):
        capture = self.capture()
        before = capture.to_json()
        changed = self.store.edit(self.a['variable_id'], 1, definition(constant('99')))
        changed = self.store.rename(changed['variable_id'], changed['version'], 'New label')
        self.store.delete(changed['variable_id'], changed['version'])
        reopened = library.Store(self.path)
        self.assertEqual(reopened.list(), [])
        self.path.unlink()
        self.assertEqual(library.require_capture(capture), json.loads(before))
        self.assertEqual(capture.program.to_dict()['nodes'][0]['value'], '0.08')

    def test_deleted_dependencies_use_retained_capture_time_metadata(self):
        b = self.store.create('Consumer', definition(binary('add', reference(self.a), constant('2'))))
        named = self.store.rename(self.a['variable_id'], 1, 'Final retained name')
        deleted = self.store.delete(named['variable_id'], named['version'])
        capture = self.store.capture([root(b)])
        dependency = capture.to_dict()['presentation'][1]
        self.assertEqual(dependency, dict(root(self.a), name='Final retained name',
            provenance=dict(source='library', version=deleted['version'], deleted=True)))
        self.assertEqual(capture.program.to_dict()['nodes'][-1]['value'], '0.08')

    def test_repeated_roots_and_multiple_revisions_preserve_order(self):
        current = self.store.edit(self.a['variable_id'], 1, definition(constant('2')))
        roots = [root(current), root(self.a), root(current)]
        capture = self.store.capture(roots)
        value = library.require_capture(capture)
        self.assertEqual(value['program']['bundle']['roots'], roots)
        self.assertEqual([root(item) for item in value['presentation']], roots[:2])
        self.assertEqual([item['provenance']['version'] for item in value['presentation']], [2, 2])

    def test_submitted_entries_and_labels_are_detached_and_never_saved(self):
        authored = entry(definition(binary('add', reference(self.a), constant('2'))), 'draft:local')
        capture = self.store.capture([root(authored)], submitted=[authored],
            labels=[dict(root(authored), name=' Local label ')])
        value = capture.to_dict()
        self.assertEqual(value['presentation'][0], dict(root(authored), name='Local label',
            provenance=dict(source='submitted')))
        self.assertEqual(value['presentation'][1]['name'], 'Original')
        self.assertEqual(len(self.store.list()), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM revisions').fetchone()[0], 1)
        authored['definition']['expression']['right']['value'] = '999'
        self.assertEqual(library.require_capture(capture), value)

    def test_submission_fallback_and_archived_identity_overlap_follow_resolver(self):
        local = entry(identity='d' * 128)
        capture = self.store.capture([root(local)], submitted=[local])
        self.assertEqual(library.require_capture(capture)['presentation'][0]['name'], 'd' * 128)
        equivalent = dict(root(self.a), definition=definition(constant('.08')))
        overlap = self.store.capture([root(self.a)], submitted=[equivalent])
        row = overlap.to_dict()['presentation'][0]
        self.assertEqual(row['name'], self.a['variable_id'])
        self.assertEqual(row['provenance'], dict(source='submitted'))
        self.assertEqual(overlap.program, self.capture().program)

    def test_invalid_unused_submitted_definitions_and_labels_fail_completely(self):
        unused = entry(definition(constant('2', 'USD')), 'draft:unused')
        self.assert_error('UNIT_MISMATCH', self.store.capture, [root(self.a)], submitted=[unused])
        local = entry(identity='draft:local')
        for labels in ({}, [dict(root(self.a), name='Relabel archive')],
                       [dict(root(local), name='x' * 121)],
                       [dict(root(local), name='')],
                       [dict(root(local), name='A'), dict(root(local), name='B')]):
            self.assert_error('INVALID_SHAPE', self.store.capture, [root(local)], submitted=[local], labels=labels)

    def test_missing_store_for_local_capture_does_not_create_file(self):
        local = entry()
        path = self.path.with_name('absent.sqlite')
        with self.assertRaises(library.Missing):
            library.Store(path).capture([root(local)], submitted=[local])
        self.assertFalse(path.exists())

    def test_long_expanded_literals_restore_through_program_boundary(self):
        record = self.store.create('Long', definition(constant('1e100')))
        capture = self.store.capture([root(record)])
        restored = library.VariableCapture(capture.to_json())
        self.assertEqual(len(library.require_capture(restored)['program']['nodes'][0]['value']), 101)
        self.assertEqual(restored.program, capture.program)
        with self.assertRaises(d.FormulaError):
            d.validate(restored.program.to_dict()['bundle'])

    def test_capture_encoding_bound_is_exact_lowerable_and_counts_escaped_names(self):
        named = self.store.rename(self.a['variable_id'], 1, '\U0001f600' * 120)
        capture = self.capture()
        # The recorded bound is part of the complete encoded document.
        value = capture.to_dict()
        bound = 1
        for _ in range(10):
            value['limits']['bytes'] = bound
            needed = len(d.canonical(value))
            if needed == bound:
                break
            bound = needed
        exact = self.capture(limits={'capture_bytes': bound})
        self.assertEqual(len(exact.to_json()), bound)
        self.assertGreater(bound, len(json.dumps(exact.to_dict(), ensure_ascii=False)))
        self.assert_error('CAPTURE_LIMIT', self.capture, limits={'capture_bytes': bound - 1})
        for maximum in (True, 0, library.CAPTURE_BYTES + 1):
            self.assert_error('CAPTURE_LIMIT', self.capture, limits={'capture_bytes': maximum})
        self.assert_error('DEFINITION_LIMIT', self.capture, limits={'nodes': 1, 'bytes': 1})
        self.assertEqual(self.store.get(named['variable_id'])['version'], 2)

    def test_capture_graph_and_definition_limits_are_not_bypassed(self):
        b = self.store.create('Consumer', definition(reference(self.a)))
        self.assert_error('DEFINITION_LIMIT', self.store.capture, [root(b)], limits={'definitions': 1})
        self.assert_error('INVALID_SHAPE', self.capture, limits={'unknown': 1})
        self.assert_error('INVALID_SHAPE', self.capture, limits=[])

    def test_restore_rejects_wrong_shape_version_noncanonical_and_large_documents(self):
        capture = self.capture()
        for value in (None, {}, library.VariableCapture('bad'), library.VariableCapture('[]')):
            self.assert_error('INVALID_SHAPE', library.require_capture, value)
        self.assert_error('UNKNOWN_VERSION', library.require_capture,
            self.changed(capture, lambda value: value.update(version=2)))
        self.assert_error('INVALID_SHAPE', library.require_capture,
            library.VariableCapture(json.dumps(capture.to_dict())))
        self.assert_error('CAPTURE_LIMIT', library.require_capture,
            library.VariableCapture(' ' * (library.CAPTURE_BYTES + 1)))
        self.assert_error('CAPTURE_LIMIT', library.require_capture,
            self.changed(capture, lambda value: value['limits'].update(bytes=1)))

    def test_restore_rejects_missing_extra_reordered_and_forged_presentation(self):
        b = self.store.create('Other', definition(constant('2')))
        capture = self.store.capture([root(self.a), root(b)])
        changes = [lambda value: value.update(presentation=[]),
            lambda value: value['presentation'].reverse(),
            lambda value: value['presentation'].append(deepcopy(value['presentation'][0])),
            lambda value: value['presentation'][0].update(name=''),
            lambda value: value['presentation'][0].update(extra='no'),
            lambda value: value['presentation'][0]['provenance'].update(favourite=True),
            lambda value: value['presentation'][0]['provenance'].update(version=True),
            lambda value: value['presentation'][0]['provenance'].update(deleted=1),
            lambda value: value['presentation'][0]['provenance'].update(source='latest')]
        for change in changes:
            self.assert_error('INVALID_SHAPE', library.require_capture, self.changed(capture, change))

    def test_restore_checks_embedded_program_instead_of_trusting_projection(self):
        capture = self.capture()
        forged = self.changed(capture, lambda value: value['program']['nodes'][0].update(value='99'))
        self.assert_error('INVALID_SHAPE', library.require_capture, forged)
        with self.assertRaises(d.FormulaError):
            forged.program
        malformed = self.changed(capture, lambda value: value.update(program=None))
        self.assert_error('INVALID_SHAPE', library.require_capture, malformed)

    def test_capture_missing_and_corrupt_archive_or_metadata_fail_without_mutation(self):
        with closing(sqlite3.connect(self.path)) as db:
            before = db.execute('SELECT * FROM revisions').fetchall()
        for content in ('null', '{broken', d.canonical(definition(constant('99')))):
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('UPDATE revisions SET definition=?', (content,))
            with self.assertRaises((library.InvalidStore, d.FormulaError)):
                self.capture()
            self.assertEqual(self.store.get(self.a['variable_id']), self.a)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE revisions SET definition=?', (before[0][2],))
            db.execute('DELETE FROM entries')
        with self.assertRaises(library.InvalidStore):
            self.capture()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM revisions')
        self.assert_error('MISSING_REFERENCE', self.capture)

    def test_cancellation_at_resolution_collection_encoding_and_restore_closes_handles(self):
        captured = self.capture()
        count = [0]
        def counting():
            count[0] += 1
        self.capture(checkpoint=counting)
        total = count[0]
        for stop in (1, 3, total // 2, total - 2, total):
            calls = [0]
            def cancel():
                calls[0] += 1
                if calls[0] == stop:
                    raise backtest_control.Cancelled()
            with self.assertRaises(backtest_control.Cancelled):
                self.capture(checkpoint=cancel)
            with closing(sqlite3.connect(self.path, timeout=.01)) as db:
                db.execute('BEGIN EXCLUSIVE')
                db.rollback()
        def cancel_restore():
            raise backtest_control.Cancelled()
        with self.assertRaises(backtest_control.Cancelled):
            library.require_capture(captured, checkpoint=cancel_restore)
        self.assertEqual(self.capture(), captured)

    def test_concurrent_mutations_cannot_mix_definition_and_metadata_snapshots(self):
        for action in ('edit', 'rename', 'favourite', 'delete'):
            with self.subTest(action=action):
                original = self.store.create('Before ' + action, definition(constant('1')))
                reading, staged, release = Event(), Event(), Event()
                outcomes, failures = [], []
                class PausedWriter(library.Store):
                    @contextmanager
                    def _transaction(writer, *, write=False, checkpoint=backtest_control.checkpoint):
                        with super()._transaction(write=write, checkpoint=checkpoint) as db:
                            yield db
                            if write:
                                staged.set()
                                if not release.wait(10):
                                    raise RuntimeError('Private writer release timed out')
                writer = PausedWriter(self.path)
                def mutate():
                    try:
                        if not reading.wait(10):
                            raise RuntimeError('Private reader start timed out')
                        args = {'edit': definition(constant('2')), 'rename': 'After rename',
                                'favourite': True}
                        function = getattr(writer, action)
                        extra = [] if action == 'delete' else [args[action]]
                        outcomes.append(function(original['variable_id'], 1, *extra))
                    except BaseException as error:
                        failures.append(error)
                thread = Thread(target=mutate)
                thread.start()
                lookup = self.store._lookup
                def paused_lookup(db, *identity):
                    value = lookup(db, *identity)
                    reading.set()
                    if not staged.wait(10):
                        raise RuntimeError('Private writer staging timed out')
                    return value
                try:
                    with patch.object(self.store, '_lookup', side_effect=paused_lookup):
                        captured = self.store.capture([root(original)])
                finally:
                    release.set()
                    thread.join(10)
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, [])
                value = library.require_capture(captured)
                self.assertEqual(value['presentation'][0], dict(root(original), name='Before ' + action,
                    provenance=dict(source='library', version=1, deleted=False)))
                self.assertEqual(captured.program.to_dict()['nodes'][0]['value'], '1')
                fresh = self.store.capture([root(outcomes[0])])
                self.assertEqual(fresh.to_dict()['presentation'][0]['provenance']['version'], 2)
                self.assertEqual(fresh.program.to_dict()['nodes'][0]['value'], '2' if action == 'edit' else '1')

    def test_maximum_definition_count_and_escaped_names_fit_capture_ceiling(self):
        authored = [entry(definition(constant(str(index))), 'draft:' + str(index)) for index in range(32)]
        labels = [dict(root(value), name='\U0001f600' * 120) for value in authored]
        capture = self.store.capture([root(value) for value in authored], submitted=authored, labels=labels)
        self.assertEqual(len(library.require_capture(capture)['presentation']), 32)
        self.assertLess(len(capture.to_json()), library.CAPTURE_BYTES)

    def test_actual_daily_evaluation_and_selection_remain_detached(self):
        from datetime import date
        from backtest.application import scalar_execution, strategy_requests
        import test_strategy_requests as requests
        from test_scalar_execution import Fixture
        fixture = Fixture(4)
        self.addCleanup(fixture.db.close)
        ev = self.store.create('Captured EV', definition(dict(op='parameter', id='market.enterprise_value'), 'USD', 'usd'))
        capture = self.store.capture([root(ev)])
        intent = requests.intent(requests.formula(ev), rank_to=1)
        intent['pool'] = 'legacy'
        strategy = strategy_requests.capture_strategy(intent, self.store)
        roots = [dict(symbol='A0001', pool='legacy', mode='historical', date='2015-01-02')]
        def run():
            with fixture.view() as view:
                formula = scalar_execution.preview(strategy, roots, view)
                selected = scalar_execution.Executor(strategy, view, lambda record: None).select(
                    fixture.db, 1, date(2015, 1, 2), date(2015, 1, 5))
            return json.dumps(formula, sort_keys=True), json.dumps(selected, sort_keys=True)
        formula_text, selection_text = run()
        self.assertEqual(json.loads(formula_text)['evaluations'][0]['results'][0]['value'], 180e6)
        self.assertEqual(json.loads(selection_text)[0]['ranking_value'], 180e6)
        capture_text, strategy_text = capture.to_json(), strategy.to_json()
        changed = self.store.edit(ev['variable_id'], 1, definition(constant('3', 'USD'), 'USD', 'usd'))
        self.store.delete(changed['variable_id'], changed['version'])
        self.path.unlink()
        self.assertEqual(run(), (formula_text, selection_text))
        self.assertEqual(library.require_capture(capture), json.loads(capture_text))
        self.assertEqual(strategy_requests.require_strategy(strategy), json.loads(strategy_text))

if __name__ == '__main__':
    unittest.main()

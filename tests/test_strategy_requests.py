"""Private synthetic captured-strategy contracts; no financial or HTTP work."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextlib import closing
from copy import deepcopy
from datetime import date, timedelta
import json
import sqlite3
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

from backtest.application import strategy_requests as s
from backtest.runtime import backtest_control
from backtest.variables import definitions as d, library
from test_variable_definitions import definition, constant, entry, root, reference, binary


def builtin(identifier='metric:ev_ebitda:yield'):
    return dict(kind='builtin', id=identifier)


def formula(record):
    return dict(kind='formula', **root(record))


def intent(source=None, conditions=None, **settings):
    return dict(format='strategy-intent', version=1,
                selection=dict(ranking=dict(source=source or builtin(), direction='highest'),
                               conditions=conditions or [], **settings))


def condition(source, value='8', unit='percent', op='gt'):
    return dict(source=source, op=op, threshold=dict(value=value, unit=unit))


def rank_step(source=None, first=1, last=50, direction='highest'):
    return dict(kind='rank', source=source or builtin(), direction=direction, rank_from=first, rank_to=last)


def pipeline(*steps, pool='cached'):
    return dict(format='strategy-intent', version=2, universe=dict(pool=pool), steps=list(steps))


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'variables.sqlite'
        self.store = library.Store(self.path)

    def create(self, value='0.08', name='Original', **kwargs):
        return self.store.create(name, definition(constant(value), **kwargs))

    def error(self, code, call, *args, **kwargs):
        with self.assertRaises(d.FormulaError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def change(self, capture, callback):
        value = capture.to_dict()
        callback(value)
        return s.CapturedStrategy(d.canonical(value))

    def test_builtin_descriptors_preserve_independent_pairs_and_filter_scales(self):
        items = {item['id']: item for item in s.builtin_catalog()}
        self.assertEqual(len(items), 36)
        for name in ('ev_ebitda', 'ev_ebitda_3y'):
            for lane in ('yield', 'multiple'):
                self.assertEqual(items['metric:' + name + ':' + lane]['storage'],
                                 dict(kind='metric', metric=name, component=lane, scale=0))
        self.assertEqual(items['filter:fcf']['unit'], 'USD')
        self.assertEqual(items['filter:fcf']['storage']['scale'], 6)
        self.assertEqual(items['filter:operating_yield_spread_3y']['display'], 'percentage_points')
        self.assertEqual(items['filter:profit_margin']['storage']['scale'], -2)
        self.assertEqual(items['filter:peg']['storage']['scale'], 0)
        items['filter:pe']['label'] = 'Changed'
        self.assertNotEqual(s.builtin_catalog()[4]['label'], 'Changed')

    def test_builtin_only_capture_has_no_io_or_hidden_yield_condition(self):
        with patch.object(library.Store, '_transaction', side_effect=AssertionError('No storage')):
            capture = s.capture_strategy(intent(builtin('filter:pe')))
        value = s.require_strategy(capture)
        self.assertIsNone(value['variables'])
        self.assertEqual(value['selection']['conditions'], [])
        self.assertEqual(value['pool'], 'legacy')
        self.assertNotIn('min_yield', capture.to_json())
        self.assertEqual(value['selection']['ranking']['source']['id'], 'filter:pe')
        self.assertFalse(self.path.exists())

    def test_all_role_combinations_and_repeated_exact_formula_roots(self):
        a = self.create()
        for ranking, filters in [(formula(a), [builtin('filter:pe')]),
                                  (builtin(), [formula(a)]),
                                  (formula(a), [formula(a), formula(a)])]:
            with self.subTest(ranking=ranking):
                capture = s.capture_strategy(intent(ranking, [condition(item) for item in filters]), self.store)
                value = s.require_strategy(capture)
                sources = [ranking] + filters
                expected = [root(source) for source in sources if source['kind'] == 'formula']
                self.assertEqual(value['variables']['program']['bundle']['roots'], expected)
                self.assertEqual(len(value['variables']['presentation']), 1)

    def test_unsaved_capture_before_library_exists_and_unused_definition_validation(self):
        local = entry(definition(constant('0.08')), 'draft:local')
        unused = entry(definition(constant('3')), 'draft:unused')
        capture = s.capture_strategy(intent(formula(local)), submitted=[local, unused],
            labels=[dict(root(local), name=' Unsaved ')])
        value = s.require_strategy(capture)
        self.assertFalse(self.path.exists())
        self.assertEqual(len(value['variables']['program']['bundle']['definitions']), 2)
        self.assertEqual(value['variables']['presentation'][0]['name'], 'Unsaved')
        self.assertEqual(value['variables']['presentation'][1]['name'], 'draft:unused')
        corrupt = deepcopy(unused)
        corrupt['revision'] = local['revision']
        self.error('REVISION_MISMATCH', s.capture_strategy, intent(formula(local)), submitted=[local, corrupt])

    def test_local_dependencies_use_existing_resolver_and_missing_archive_fails(self):
        a = entry(definition(constant('2')), 'draft:a')
        b = entry(definition(binary('add', reference(a), constant('3'))), 'draft:b')
        capture = s.capture_strategy(intent(formula(b)), submitted=[a, b])
        self.assertEqual(len(capture.to_dict()['variables']['program']['nodes']), 4)
        self.error('MISSING_REFERENCE', s.capture_strategy, intent(formula(b)), submitted=[b])
        self.assertFalse(self.path.exists())

    def test_library_store_capture_still_requires_existing_store(self):
        a = entry(definition(constant('2')), 'draft:a')
        with self.assertRaises(library.Missing):
            self.store.capture([root(a)], submitted=[a])
        self.assertFalse(self.path.exists())
        captured = library.capture_submitted([root(a)], submitted=[a])
        self.assertEqual(captured.to_dict()['presentation'][0]['provenance'], {'source': 'submitted'})

    def test_exact_old_revision_survives_edit_delete_restart_and_file_removal(self):
        a = self.create()
        capture = s.capture_strategy(intent(formula(a), [condition(formula(a))]), self.store)
        before = capture.to_json()
        current = self.store.edit(a['variable_id'], a['version'], definition(constant('99')))
        current = self.store.rename(current['variable_id'], current['version'], 'Renamed')
        self.store.delete(current['variable_id'], current['version'])
        self.assertEqual(library.Store(self.path).list(), [])
        self.path.unlink()
        with patch.object(library.Store, '_transaction', side_effect=AssertionError('No lookup')):
            self.assertEqual(s.require_strategy(capture), json.loads(before))
        self.assertEqual(capture.to_json(), before)

    def test_atomic_capture_races_rename_edit_and_delete(self):
        for action in ('rename', 'edit', 'delete'):
            with self.subTest(action=action):
                a = self.create(name=action)
                snapshot, release, writer_started = Event(), Event(), Event()
                outcomes, errors = [], []
                lookup = self.store._lookup
                def paused(db, *identity):
                    result = lookup(db, *identity)
                    snapshot.set()
                    if not release.wait(5):
                        raise AssertionError('Capture release timed out')
                    return result
                def read():
                    try:
                        outcomes.append(s.capture_strategy(intent(formula(a)), self.store))
                    except BaseException as error:
                        errors.append(error)
                def write():
                    try:
                        writer_started.set()
                        if action == 'rename':
                            self.store.rename(a['variable_id'], 1, 'Later')
                        elif action == 'edit':
                            self.store.edit(a['variable_id'], 1, definition(constant('99')))
                        else:
                            self.store.delete(a['variable_id'], 1)
                    except BaseException as error:
                        errors.append(error)
                with patch.object(self.store, '_lookup', side_effect=paused):
                    reader = Thread(target=read)
                    reader.start()
                    self.assertTrue(snapshot.wait(5))
                    writer = Thread(target=write)
                    writer.start()
                    self.assertTrue(writer_started.wait(5))
                    release.set()
                    reader.join(5)
                    writer.join(5)
                    self.assertFalse(reader.is_alive())
                    self.assertFalse(writer.is_alive())
                self.assertEqual(errors, [])
                metadata = outcomes[0].to_dict()['variables']['presentation'][0]
                self.assertEqual(metadata['name'], action)
                self.assertEqual(metadata['provenance'], dict(source='library', version=1, deleted=False))
                self.assertEqual(outcomes[0].to_dict()['variables']['program']['nodes'][0]['value'], '0.08')

    def test_direction_rank_range_and_selection_order_are_explicit(self):
        for order in ('filter_first', 'rank_first'):
            for direction in ('highest', 'lowest'):
                request = intent(rank_from=2, rank_to=7, selection_order=order)
                request['selection']['ranking']['direction'] = direction
                value = s.capture_strategy(request).to_dict()['selection']
                self.assertEqual((value['rank_from'], value['rank_to'], value['selection_order']), (2, 7, order))
                self.assertEqual(value['ranking']['direction'], direction)
        request = intent()
        del request['selection']['ranking']['direction']
        self.error('INVALID_STRATEGY', s.capture_strategy, request)
        for values in ({'rank_from': True}, {'rank_from': 2, 'rank_to': 1}, {'selection_order': 'unknown'}):
            self.error('INVALID_STRATEGY', s.capture_strategy, intent(**values))

    def test_threshold_units_and_saved_comparison_scales(self):
        examples = [('filter:profit_margin', '8', 'percent', '0.08', 8.),
                    ('filter:operating_yield_spread_3y', '8', 'percentage_points', '0.08', 8.),
                    ('filter:pe', '-2.5', 'multiple', '-2.5', -2.5),
                    ('filter:fcf', '2.5', 'usd_million', '2500000', 2.5),
                    ('filter:fcf', '2500000', 'USD', '2500000', 2.5),
                    ('metric:ev_ebitda:yield', '8', 'percent', '0.08', .08)]
        for identifier, amount, unit, canonical, stored in examples:
            with self.subTest(identifier=identifier, unit=unit):
                row = condition(builtin(identifier), amount, unit)
                value = s.capture_strategy(intent(conditions=[row])).to_dict()['selection']['conditions'][0]
                self.assertEqual(value['threshold']['value'], canonical)
                self.assertEqual(value['submitted_threshold'], dict(value=amount, unit=unit))
                self.assertEqual(value['storage_comparison_value'], stored)
                self.assertEqual(value['comparison_value'], float(canonical))

    def test_signed_formula_threshold_and_long_expanded_literal_restore(self):
        local = entry(definition(constant('1e100')), 'draft:long')
        capture = s.capture_strategy(intent(formula(local), [condition(formula(local), '-3e99', 'number')]), submitted=[local])
        checked = s.require_strategy(capture)
        self.assertEqual(len(checked['variables']['program']['nodes'][0]['value']), 101)
        self.assertEqual(checked['selection']['conditions'][0]['comparison_value'], -3e99)
        self.assertTrue(s.calculation_equal(capture, s.CapturedStrategy(capture.to_json())))

    def test_malformed_units_nonfinite_and_inclusive_custom_conditions_fail(self):
        for amount, unit, code in [('8', 'USD', 'UNIT_MISMATCH'), ('NaN', 'percent', 'INVALID_LITERAL'),
                                    ('1e9999', 'percent', 'INVALID_LITERAL')]:
            self.error(code, s.capture_strategy, intent(conditions=[condition(builtin(), amount, unit)]))
        self.error('INVALID_STRATEGY', s.capture_strategy, intent(conditions=[condition(builtin(), op='ge')]))
        self.error('WORK_LIMIT', s.capture_strategy, intent(conditions=[condition(builtin())] * 51))

    def test_storage_threshold_overflow_underflow_and_supplied_evidence_fail(self):
        for source, value, unit in [(builtin('filter:fcf'), '1e-320', 'USD'),
                                    (builtin('filter:profit_margin'), '1e308', 'number')]:
            self.error('INVALID_LITERAL', s.capture_strategy,
                       intent(conditions=[condition(source, value, unit)]))
        row = condition(builtin())
        row['comparison_value'] = 99.
        self.error('INVALID_STRATEGY', s.capture_strategy, intent(conditions=[row]))
        row = condition(builtin())
        row['storage_comparison_value'] = 99.
        self.error('INVALID_STRATEGY', s.capture_strategy, intent(conditions=[row]))

    def test_size_metadata_bounds_are_explicit_and_never_add_yield_defaults(self):
        request = intent()
        request.update(pool='cached', bounds=dict(min_cap=None, max_cap=1e9, min_ev=0, sector='Energy', exchange='NYSE'))
        capture = s.capture_strategy(request)
        value = capture.to_dict()
        self.assertEqual(value['bounds'], dict(min_cap=None, max_cap=1e9, min_ev=0., sector='Energy', exchange='NYSE'))
        self.assertEqual(value['selection']['conditions'], [])
        original=capture.to_json()
        request['bounds'].update(min_yield=.08,max_multiple=12.5)
        checked=s.capture_strategy(request)
        self.assertEqual(s.from_wire(checked.to_dict()).to_json(),checked.to_json())
        self.assertEqual(checked.to_dict()['bounds']['min_yield'],.08)
        self.assertEqual(checked.to_dict()['bounds']['max_multiple'],12.5)
        self.assertEqual(s.require_strategy(capture),json.loads(original))
        for source in (builtin('filter:pe'),builtin('metric:ev_ebitda:multiple')):
            request['selection']['ranking']['source']=source
            self.error('INVALID_STRATEGY',s.capture_strategy,request)
        for bounds in ({'min_cap': True}, {'min_cap': -1}, {'min_cap': 10, 'max_cap': 9},
                       {'sector': 'x' * 257}, {'min_yield': -1}, {'max_multiple': True}):
            bad = intent()
            bad['bounds'] = bounds
            self.error('INVALID_STRATEGY', s.capture_strategy, bad)

    def test_immutable_copies_and_distinct_submission_calculation_equality(self):
        a = self.create()
        first = s.capture_strategy(intent(formula(a)), self.store)
        renamed = self.store.rename(a['variable_id'], 1, 'Later label')
        later = s.capture_strategy(intent(formula(a)), self.store)
        self.assertNotEqual(first.to_json(), later.to_json())
        self.assertTrue(s.calculation_equal(first, later))
        self.store.favourite(a['variable_id'], renamed['version'], True)
        starred = s.capture_strategy(intent(formula(a)), self.store)
        self.assertTrue(s.calculation_equal(later, starred))
        self.assertNotEqual(later.to_json(), starred.to_json())
        before = first.to_json()
        first.to_dict()['variables']['presentation'][0]['name'] = 'Mutated'
        self.assertEqual(first.to_json(), before)
        with self.assertRaises(AttributeError):
            first.document = '{}'

    def test_threshold_spelling_omissions_and_resource_limits_do_not_change_calculation(self):
        a = s.capture_strategy(intent(conditions=[condition(builtin(), '8', 'percent')]))
        b = s.capture_strategy(intent(conditions=[condition(builtin(), '0.080', 'number')], selection_order='filter_first'), limits={'bytes': 10000})
        self.assertTrue(s.calculation_equal(a, b))
        self.assertNotEqual(a.to_json(), b.to_json())
        for change in (lambda v: v['selection']['ranking'].update(direction='lowest'),
                       lambda v: v['selection'].update(selection_order='rank_first'),
                       lambda v: v.update(pool='cached')):
            request = intent(conditions=[condition(builtin(), '8', 'percent')])
            change(request)
            self.assertFalse(s.calculation_equal(a, s.capture_strategy(request)))

    def test_definition_and_display_revisions_change_calculation(self):
        a = self.create()
        first = s.capture_strategy(intent(formula(a)), self.store)
        changed = self.store.edit(a['variable_id'], 1, definition(constant('99')))
        second = s.capture_strategy(intent(formula(changed)), self.store)
        self.assertFalse(s.calculation_equal(first, second))
        displayed = self.store.edit(a['variable_id'], changed['version'], definition(constant('99'), display='percent'))
        self.assertFalse(s.calculation_equal(second, s.capture_strategy(intent(formula(displayed)), self.store)))

    def test_checked_restore_never_reads_current_catalog_or_library(self):
        a = self.create()
        capture = s.capture_strategy(intent(formula(a), [condition(builtin('filter:pe'))]), self.store)
        with (patch.object(s, 'builtin_catalog', side_effect=AssertionError('No live catalog')),
              patch.object(library.Store, '_transaction', side_effect=AssertionError('No library'))):
            self.assertEqual(s.require_strategy(capture), capture.to_dict())

    def test_preflight_rejects_changed_builtin_semantics_but_accepts_renamed_catalog(self):
        capture = s.capture_strategy(intent())
        options = dict(strategy=capture.to_dict())
        catalog = s.builtin_catalog()
        catalog[0]['label'] = 'New label'
        with patch.object(s, 'builtin_catalog', return_value=catalog):
            self.assertEqual(s.check_options(options), capture.to_dict())
        catalog[0]['storage']['scale'] = -2
        with patch.object(s, 'builtin_catalog', return_value=catalog):
            self.error('UNSUPPORTED_CAPABILITY', s.check_options, options)
        self.assertEqual(s.require_strategy(capture), capture.to_dict())

    def test_custom_discrimination_rejects_overlap_and_malformed_capture_before_input_work(self):
        captured = s.capture_strategy(intent()).to_dict()
        for key in ('metric', 'min_yield', 'filters', 'rank_from', 'pool', 'selection_order', 'variables'):
            self.error('INVALID_STRATEGY', s.check_options, dict(strategy=captured, **{key: None}))
        self.error('INVALID_STRATEGY', s.check_options, dict(engine='original', strategy=None))
        self.assertEqual(s.check_options(dict(engine='original', calendar={'unchanged': True}, strategy=captured)), captured)

    def test_legacy_options_and_requests_are_not_normalized_or_restricted(self):
        legacy = dict(metric='ev_ebitda', filters=[], sector='x' * 500, min_cap=100000000)
        before = deepcopy(legacy)
        with patch.object(s, 'builtin_catalog', side_effect=AssertionError('No new catalog')):
            self.assertIsNone(s.check_options(legacy))
            self.assertIsNone(s.check_request(dict(options=legacy, padding='x' * (s.REQUEST_BYTES + 1))))
        self.assertEqual(legacy, before)
        self.assertNotIn('selection_order', legacy)

    def test_canonical_request_bytes_include_names_and_wrapper_fields(self):
        capture = s.capture_strategy(intent()).to_dict()
        request = dict(id='a' * 32, name='Test', mode='custom', options=dict(strategy=capture), catalog={}, presentation={})
        retained = deepcopy(request)
        self.assertEqual(d.canonical(request), d.canonical(retained))
        retained['name'] = 'Different'
        self.assertNotEqual(d.canonical(request), d.canonical(retained))
        retained = deepcopy(request)
        retained['options']['strategy']['builtins'][0]['label'] = 'Later label'
        self.assertNotEqual(d.canonical(request), d.canonical(retained))

    def test_whole_request_exact_byte_limit_counts_escaping_and_display_context(self):
        capture = s.capture_strategy(intent()).to_dict()
        request = dict(id='b' * 32, mode='custom', options=dict(strategy=capture), catalog={}, presentation={}, padding='')
        size = len(d.canonical(request))
        request['padding'] = 'x' * (s.REQUEST_BYTES - size)
        self.assertEqual(len(d.canonical(request)), s.REQUEST_BYTES)
        self.assertEqual(s.check_request(request), capture)
        request['padding'] += 'x'
        self.error('WORK_LIMIT', s.check_request, request)
        request['padding'] = '😀' * 22000
        self.assertLess(len(json.dumps(request, ensure_ascii=False)), s.REQUEST_BYTES)
        self.error('WORK_LIMIT', s.check_request, request)

    def test_recorded_plan_has_separate_allowance_from_captured_settings(self):
        from backtest import calendar_requests
        from backtest.application import evidence_transfer
        capture=s.capture_strategy(intent()).to_dict()
        options=dict(strategy=capture,start='2000-01-01',end='2018-01-01',months=1,trials=100,seed=42)
        sessions=[date(2000,1,1)+timedelta(days=i) for i in range(6576)
                  if (date(2000,1,1)+timedelta(days=i)).weekday()<5]
        planned=calendar_requests.plan(sessions,options)
        request=dict(id='c'*32,mode='random',options=options,planned=planned)
        original=deepcopy(request)
        size=len(d.canonical(planned))
        self.assertGreater(size,s.REQUEST_BYTES)
        self.assertEqual(s.check_request(request),capture)
        self.assertEqual(request,original)
        with patch.object(evidence_transfer,'MAX_PLAN_BYTES',size-1):
            self.error('WORK_LIMIT',s.check_request,request)
        request['padding']='x'*s.REQUEST_BYTES
        self.error('WORK_LIMIT',s.check_request,request)

    def test_lowerable_strategy_byte_limit_and_escaped_names(self):
        a = self.create(name='😀' * 120)
        request = intent(formula(a))
        capture = s.capture_strategy(request, self.store)
        needed = len(capture.to_json())
        for _ in range(10):
            value = capture.to_dict()
            value['limits']['bytes'] = needed
            updated = len(d.canonical(value))
            if updated == needed:
                break
            needed = updated
        exact = s.capture_strategy(request, self.store, limits={'bytes': needed})
        self.assertEqual(len(exact.to_json()), needed)
        self.assertGreater(needed, len(json.dumps(exact.to_dict(), ensure_ascii=False)))
        self.error('WORK_LIMIT', s.capture_strategy, request, self.store, limits={'bytes': needed - 1})
        for bound in (True, 0, s.STRATEGY_BYTES + 1):
            self.error('WORK_LIMIT', s.capture_strategy, request, self.store, limits={'bytes': bound})

    def test_unknown_versions_fields_and_raw_malformed_json_fail(self):
        capture = s.capture_strategy(intent())
        for value in (None, {}, s.CapturedStrategy('bad'), s.CapturedStrategy('[]'),
                      s.CapturedStrategy(json.dumps(capture.to_dict()))):
            self.error('INVALID_STRATEGY', s.require_strategy, value)
        self.error('UNKNOWN_VERSION', s.require_strategy, self.change(capture, lambda v: v.update(version=3)))
        self.error('WORK_LIMIT', s.require_strategy, s.CapturedStrategy(' ' * (s.STRATEGY_BYTES + 1)))
        for change in (lambda v: v.update(version=True), lambda v: v.update(format='other')):
            bad = intent()
            change(bad)
            self.error('UNKNOWN_VERSION', s.capture_strategy, bad)
        bad = intent()
        bad['min_yield'] = 0
        self.error('INVALID_STRATEGY', s.capture_strategy, bad)

    def test_forged_roots_descriptors_and_threshold_evidence_fail(self):
        a = self.create()
        capture = s.capture_strategy(intent(formula(a), [condition(builtin('filter:pe'), '8', 'multiple')]), self.store)
        changes = [lambda v: v['variables']['program']['bundle']['roots'].reverse(),
                   lambda v: v['selection']['ranking']['source'].update(revision='sha256:' + '0' * 64),
                   lambda v: v['builtins'][0]['storage'].update(scale=6),
                   lambda v: v['builtins'].append(deepcopy(v['builtins'][0])),
                   lambda v: v['selection']['conditions'][0]['threshold'].update(value='99'),
                   lambda v: v['selection']['conditions'][0].update(comparison_value=99.),
                   lambda v: v['selection']['conditions'][0].update(storage_comparison_value=99.)]
        # Reversing a one-root list changes nothing; use an actual missing root.
        changes[0] = lambda v: v['variables']['program']['bundle'].update(roots=[])
        for change in changes:
            with self.assertRaises(d.FormulaError):
                s.require_strategy(self.change(capture, change))

    def test_unknown_sources_missing_revisions_and_labels_fail(self):
        self.error('UNSUPPORTED_CAPABILITY', s.capture_strategy, intent(builtin('filter:unknown')))
        self.error('INVALID_STRATEGY', s.capture_strategy, intent(dict(kind='formula', variable_id='latest', revision=None)))
        a = entry(definition(constant('2')), 'draft:a')
        self.error('INVALID_SHAPE', s.capture_strategy, intent(formula(a)), submitted=[a],
                   labels=[dict(root(a), name='')])
        self.error('INVALID_STRATEGY', s.capture_strategy, intent(), submitted=[a])

    def test_submitted_only_capture_uses_all_existing_limits_and_long_literal_restore(self):
        a = entry(definition(constant('1e100')), 'draft:a')
        captured = library.capture_submitted([root(a)], submitted=[a], labels=[dict(root(a), name='Local')])
        self.assertEqual(len(library.require_capture(captured)['program']['nodes'][0]['value']), 101)
        self.error('DEFINITION_LIMIT', library.capture_submitted, [root(a)], submitted=[a], limits={'bytes': 1})
        self.error('CAPTURE_LIMIT', library.capture_submitted, [root(a)], submitted=[a], limits={'capture_bytes': 1})
        self.error('INVALID_SHAPE', library.capture_submitted, [root(a)], submitted=[a], limits=[])
        self.assertFalse(self.path.exists())

    def test_cancellation_closes_all_connections_and_returns_no_partial_capture(self):
        a = self.create()
        request = intent(formula(a))
        calls = [0]
        def counting():
            calls[0] += 1
        s.capture_strategy(request, self.store, checkpoint=counting)
        total = calls[0]
        for stop in (1, total // 2, total - 1):
            calls[0] = 0
            def cancel():
                calls[0] += 1
                if calls[0] == stop:
                    raise backtest_control.Cancelled()
            with self.assertRaises(backtest_control.Cancelled):
                s.capture_strategy(request, self.store, checkpoint=cancel)
            with closing(sqlite3.connect(self.path, timeout=.1)) as db:
                db.execute('BEGIN EXCLUSIVE')
                db.rollback()
        self.path.unlink()


    def test_pipeline_capture_is_detached_and_retains_order_sources_and_scales(self):
        record = self.create()
        request = pipeline(rank_step(formula(record), 20, 40),
            dict(kind='filter', **condition(builtin('filter:profit_margin'), '8', op='ge')),
            dict(kind='filter', source=dict(kind='field', field='sector'), op='eq', threshold='Technology'),
            rank_step(formula(record), 1, 5, 'lowest'))
        capture = s.capture_strategy(request, self.store)
        value = capture.to_dict()
        self.assertEqual(value['steps'][1]['storage_comparison_value'], 8.)
        self.assertEqual(value['steps'][1]['comparison_value'], .08)
        self.assertEqual(value['variables']['program']['bundle']['roots'], [root(record)] * 2)
        self.assertEqual(value['universe'], dict(pool='cached'))
        self.assertNotIn('bounds', value)
        with patch.object(s, 'builtin_catalog', side_effect=AssertionError('No catalog')), \
             patch.object(library.Store, '_transaction', side_effect=AssertionError('No library')):
            self.assertEqual(s.require_strategy(capture), value)
            self.assertEqual(s.from_wire(value).to_json(), capture.to_json())
        from backtest.application import variable_authoring
        self.assertEqual(variable_authoring.prepare(dict(intent=variable_authoring.intent(value), original=value), self.store)['strategy'], value)
        self.assertEqual(s.log_fields(dict(strategy=value, market='us')),
                         dict(market='us', ranking_source_kind='formula', step_count=4))

    def test_pipeline_checks_steps_metadata_ranks_units_and_existing_limits(self):
        self.error('INVALID_STRATEGY', s.capture_strategy, pipeline())
        request = pipeline(rank_step())
        self.assertEqual(s.capture_strategy(pipeline(*[rank_step()] * 50)).to_dict()['version'], 2)
        self.error('WORK_LIMIT', s.capture_strategy, pipeline(*[rank_step()] * 51))
        self.error('INVALID_STRATEGY', s.capture_strategy,
                   pipeline(dict(kind='filter', **condition(builtin()))))
        for step in (rank_step(first=0), rank_step(direction='unknown'),
                     rank_step(dict(kind='field', field='sector')),
                     dict(kind='filter', **condition(builtin(), op='eq')),
                     dict(kind='filter', source=dict(kind='field', field='exchange'), op='ge', threshold='NYSE')):
            self.error('INVALID_STRATEGY', s.capture_strategy, pipeline(rank_step(), step))
        self.error('UNIT_MISMATCH', s.capture_strategy,
                   pipeline(rank_step(), dict(kind='filter', **condition(builtin('filter:fcf'), unit='percent'))))
        request['universe']['min_cap'] = 0
        self.error('INVALID_STRATEGY', s.capture_strategy, request)


if __name__ == '__main__':
    unittest.main()

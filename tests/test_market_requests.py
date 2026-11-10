"""Market intent survives admission and private queue records without changing old US bytes."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from datetime import date, timedelta
import io
import json
import tempfile
import unittest
import uuid
from unittest.mock import patch

from backtest import calendar_requests, result_evidence
from backtest.application import original_calculations, queue, result_exports, strategy_requests as s, variable_authoring
from backtest.inputs import daily, research
from backtest.variables import definitions as d, measures, parameters
from test_strategy_requests import formula, intent, pipeline, rank_step
from test_variable_definitions import constant, definition, entry
from test_market_inputs import prepared_markets


def capture(catalog=parameters.V4, pool='cached'):
    value = dict(definition(constant('1')), version=3, parameter_catalog=catalog,
                 temporal_policy=d.MARKET_TEMPORAL_POLICY if catalog == parameters.V4 else d.TEMPORAL_POLICY)
    item = entry(value)
    return s.capture_strategy(dict(intent(formula(item)), pool=pool), submitted=[item]).to_dict()


def request(options):
    return dict(id=uuid.uuid4().hex, name='Market test', mode='custom', options=options,
                catalog=dict(metrics={}, filters={}), presentation={})


class MarketRequests(unittest.TestCase):
    def test_market_admission_preserves_old_capture_and_requires_explicit_upgrade(self):
        original = capture(parameters.V3)
        frozen = d.canonical(original)
        self.assertEqual(s.check_options(dict(strategy=original)), original)
        for market in ('hk', 'jp'):
            with self.subTest(market=market):
                with self.assertRaises(d.FormulaError) as caught:
                    s.check_options(dict(strategy=original, market=market))
                self.assertEqual((caught.exception.code, caught.exception.path),
                                 ('UNSUPPORTED_CAPABILITY', '/strategy/variables'))
                current = capture()
                self.assertEqual(s.check_options(dict(strategy=current, market=market)), current)
        self.assertEqual(d.canonical(original), frozen)
        self.assertNotIn('market', s.canonical_options(dict(strategy=original)))

    def test_market_and_pool_are_checked_at_existing_admission_boundary(self):
        service = original_calculations.Original()
        for options, path in [(dict(market='xx'), '/market'), (dict(market=None), '/market'),
                              (dict(market='hk', pool='legacy'), '/pool'),
                              (dict(market='jp', strategy=capture(pool='legacy')), '/pool')]:
            with self.subTest(options=options):
                with self.assertRaises(d.FormulaError) as caught:
                    service.preflight(options)
                self.assertEqual(caught.exception.path, path)
        self.assertIsNone(s.check_options(dict(pool='legacy')))
        self.assertIsNone(s.check_options(dict(market='jp')))
        with self.assertRaises(d.FormulaError):
            queue.Store.specification(request(dict(start='2015-01-01', end='2015-12-31', market='xx')))

    def test_queue_hold_edit_and_reopen_preserve_market_and_old_omission(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'queue.sqlite'
            store = queue.Store(path)
            old = dict(start='2015-01-01', end='2015-12-31', months=3, rank_to=1)
            legacy = store.enqueue(request(old))
            self.assertEqual(legacy['options'], old)
            options = dict(start='2015-01-01', end='2015-12-31', months=3,
                           market='hk', strategy=capture())
            row = store.enqueue(request(options))
            held = store.change(row['id'], 'hold', dict(revision=row['revision']))
            changed = request(dict(options, market='jp'))
            store.change(row['id'], 'update', dict(revision=held['revision'], **changed))
            self.assertEqual(queue.Store(path).get(row['id'])['options'], changed['options'])
            self.assertEqual(queue.Store(path).get(legacy['id'])['options'], old)

    def test_random_plans_keep_market_and_old_hash_content(self):
        sessions = [date(2015, 1, 1) + timedelta(days=i) for i in range(365)
                    if (date(2015, 1, 1) + timedelta(days=i)).weekday() < 5]
        options = dict(start='2015-01-01', end='2015-12-31', months=3, trials=2, seed=42, rank_to=1)
        plan = calendar_requests.plan(sessions, options)
        frozen = json.dumps(plan, sort_keys=True)
        calendar_requests.validate_submitted(dict(options, market='us'), plan)
        self.assertEqual(json.dumps(plan, sort_keys=True), frozen)
        self.assertNotIn('market', plan['options'])
        foreign = calendar_requests.plan(sessions, dict(options, market='hk'))
        self.assertEqual(foreign['options']['market'], 'hk')
        with self.assertRaises(ValueError):
            calendar_requests.validate_submitted(dict(options, market='jp'), foreign)
        self.assertTrue(s.options_calculation_equal(options, dict(options, market='us')))
        self.assertFalse(s.options_calculation_equal(dict(options, market='hk'), dict(options, market='jp')))

    def test_current_authoring_has_market_policy_and_retains_published_named_measures(self):
        current = variable_authoring.catalog()
        self.assertEqual((current['current_parameter_catalog'], current['current_temporal_policy']),
                         (parameters.V4, d.MARKET_TEMPORAL_POLICY))
        self.assertEqual(current['version3_parameters'], parameters.catalog(parameters.V3))
        old = measures.catalog()
        new = measures.catalog(parameters.V4)
        self.assertEqual([item['id'] for item in old], [item['id'] for item in new])
        for before, after in zip(old, new):
            self.assertNotEqual(before['root']['revision'], after['root']['revision'])
            self.assertEqual(measures.exact(**before['root'])['definition']['parameter_catalog'], parameters.V3)
            bundle = measures.bundle([after['id']], parameters.V4)
            self.assertTrue(all(item['definition']['parameter_catalog'] == parameters.V4 for item in bundle['definitions']))

    def test_explicit_composed_measure_upgrade_can_save_and_run_foreign_without_rewriting_old_revision(self):
        before = next(item for item in measures.catalog() if item['id'] == 'gross_margin')
        old_definition = dict(definition(dict(op='ref', **before['root'])), version=3,
                              parameter_catalog=parameters.V3)
        with tempfile.TemporaryDirectory() as folder:
            from backtest.variables import library
            store = library.Store(Path(folder) / 'variables.sqlite')
            saved = store.create('Composed gross margin', old_definition)
            old_root = {key: saved[key] for key in ('variable_id', 'revision')}
            snapshot = store.authoring_snapshot(old_root)
            upgraded = variable_authoring.validate(dict(variable_id=saved['variable_id'],
                definition=old_definition, name=saved['name'], upgrade=True,
                submitted=[item for item in snapshot['authored'] if item['variable_id'] != saved['variable_id']],
                labels=[item for item in snapshot['capture']['presentation'] if item['variable_id'] != saved['variable_id']]), store)
            self.assertEqual(upgraded['root']['variable_id'], saved['variable_id'])
            self.assertNotEqual(upgraded['root']['revision'], saved['revision'])
            authored = next(item['definition'] for item in upgraded['authored'] if item['variable_id'] == saved['variable_id'])
            current = store.save(saved['variable_id'], saved['version'], saved['name'], authored)
            captured = s.capture_strategy(dict(intent(dict(kind='formula', variable_id=current['variable_id'],
                revision=current['revision'])), pool='cached'), store).to_dict()
            self.assertEqual(s.check_options(dict(strategy=captured, market='hk')), captured)
            self.assertTrue(all(item['definition']['parameter_catalog'] == parameters.V4
                                for item in captured['variables']['program']['bundle']['definitions']))
            self.assertEqual(store.authoring_snapshot(old_root)['authored'][0]['definition'], old_definition)

    def test_upgrade_keeps_explicit_user_dependency_revision(self):
        from backtest.variables import library
        with tempfile.TemporaryDirectory() as folder:
            store = library.Store(Path(folder) / 'variables.sqlite')
            dependency = store.create('Old dependency', definition())
            dependency_root = {key: dependency[key] for key in ('variable_id', 'revision')}
            value = definition(dict(op='ref', **dependency_root))
            upgraded = variable_authoring.validate(dict(definition=value, upgrade=True), store)
            authored = next(item['definition'] for item in upgraded['authored'] if item['variable_id'] == 'local:editor')
            self.assertEqual(authored['expression'], dict(op='ref', **dependency_root))
            with self.assertRaises(d.FormulaError) as caught:
                captured = s.capture_strategy(dict(intent(dict(kind='formula', **upgraded['root'])), pool='cached'),
                                              submitted=upgraded['authored']).to_dict()
                s.check_options(dict(strategy=captured, market='jp'))
            self.assertEqual(caught.exception.path, '/strategy/variables')

    def test_original_preview_coverage_and_usd_results_follow_recorded_market(self):
        captured = capture()
        # These fictional companies are smaller than the normal $100m floor.
        captured_intent = dict(intent(formula(captured['variables']['program']['bundle']['definitions'][0])),
                               pool='cached', bounds=dict(min_cap=0, min_ev=0))
        captured = s.capture_strategy(captured_intent,
            submitted=captured['variables']['program']['bundle']['definitions']).to_dict()
        with prepared_markets() as (_, raw, source, daily_path):
            connect = daily.connect
            with patch.object(research, 'DATABASE', source), patch.object(daily, 'connect',
                    side_effect=lambda: connect(daily_path, source)):
                service = original_calculations.Original()
                for market, symbol in [('hk', '0001.HK'), ('jp', '1000.T')]:
                    preview = service.preview(captured, [dict(symbol=symbol, pool='cached', mode='historical',
                                               date='2015-07-01')], market=market)
                    self.assertEqual(preview['evaluations'][0]['results'][0]['value'], 1.)
                jp, hk = service.coverage(market='jp'), service.coverage(market='hk')
                self.assertNotEqual(jp['generation'], hk['generation'])
                self.assertEqual([scope['pool'] for scope in jp['scopes']], ['cached'])
                self.assertNotEqual(jp['scopes'][0]['book'], hk['scopes'][0]['book'])
                scope = dict(jp['scopes'][0], generation=jp['generation'])
                inspected = service.coverage(captured, scope, market='jp')
                self.assertEqual(inspected['scope']['book'], scope['book'])
                options = dict(strategy=captured, market='jp', start='2015-07-01', end='2015-07-30', months=1)
                output = io.BytesIO()
                complete = service.calculate_into('custom', options, output, None, None)
                self.assertEqual(complete['manifest']['summary']['options']['market'], 'jp')
                self.assertAlmostEqual(complete['manifest']['summary']['growth'], 1.25)
                random_output, configurations = io.BytesIO(), []
                random_options = dict(options, trials=2, seed=42)
                sampled = service.calculate_into('random', random_options, random_output, None, configurations.append)
                self.assertEqual(sampled['manifest']['summary']['configuration']['options']['market'], 'jp')
                replay = service.calculate_into('random', random_options, io.BytesIO(), None, None, planned=configurations[0])
                self.assertEqual(replay['manifest']['summary']['configuration'], configurations[0])
                random_reader = result_evidence.open_reader(random_output, max_bytes=16*1024**2)
                self.assertEqual(random_reader.trial_summary(1)[0]['options']['market'], 'jp')
                ordinary = service.calculate('custom', dict(market='jp', start='2015-07-01', end='2015-07-30',
                                             months=1, min_cap=0, min_ev=0), None, None)
                self.assertEqual(ordinary['options']['market'], 'jp')
                self.assertAlmostEqual(ordinary['growth'], 1.25)
                self.assertAlmostEqual(ordinary['periods'][0]['spy'], .2)
            with (patch.object(s, 'builtin_catalog', side_effect=AssertionError('Stored reads use no catalog')),
                    patch.object(daily, 'connect', side_effect=AssertionError('Stored reads use no financial input'))):
                reader = result_evidence.open_reader(output, max_bytes=16*1024**2)
                self.assertEqual(reader.metadata['options']['market'], 'jp')
                self.assertEqual(reader.manifest, complete['manifest'])
                for kind in ('holdings', 'returns'):
                    rows = list(result_exports.rows(reader, kind, 1))
                    self.assertEqual(rows[0][:2], ['market', 'currency'])
                    self.assertEqual(rows[1][:2], ['jp', 'USD'])


    def test_pipeline_fixed_and_seeded_random_match_capture1_in_each_market(self):
        old = capture()
        source = old['selection']['ranking']['source']
        authored = old['variables']['program']['bundle']['definitions']
        old = s.capture_strategy(dict(intent(source, rank_from=1, rank_to=2), pool='cached',
                                      bounds=dict(min_cap=0, min_ev=0)), submitted=authored).to_dict()
        new = s.capture_strategy(pipeline(
            dict(kind='filter', source=dict(kind='field', field='market_cap'), op='ge', threshold=dict(value='0', unit='usd')),
            dict(kind='filter', source=dict(kind='field', field='enterprise_value'), op='ge', threshold=dict(value='0', unit='usd')),
            rank_step(source, 1, 2)), submitted=authored).to_dict()
        def holdings(reader):
            return [{key: (value.hex() if isinstance(value, float) else value) for key, value in row['value'].items()
                     if key != 'scalar_evidence'} for row in reader.verified_records() if row['type'] == 'holding']
        with prepared_markets() as (_, raw, research_path, daily_path):
            connect = daily.connect
            with patch.object(research, 'DATABASE', research_path), patch.object(daily, 'connect',
                    side_effect=lambda: connect(daily_path, research_path)):
                service = original_calculations.Original()
                for market in ('us', 'hk', 'jp'):
                    for mode in ('custom', 'random'):
                        results = []
                        for strategy in (old, new):
                            options = dict(strategy=strategy, market=market, start='2015-07-01', end='2015-07-30', months=1)
                            if mode == 'random':options.update(trials=2, seed=42)
                            stream = io.BytesIO()
                            service.calculate_into(mode, options, stream, None, None)
                            results.append(result_evidence.open_reader(stream, max_bytes=16*1024**2))
                        self.assertEqual(holdings(results[0]), holdings(results[1]), (market, mode))
                        for left, right in zip(results[0].verified_records(), results[1].verified_records()):
                            if left['type'] == right['type'] == 'period':
                                self.assertEqual(left, right)


if __name__ == '__main__':
    unittest.main()

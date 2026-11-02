"""Binary64, admission, evidence and resource checks on private provider fixtures."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

import json
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from backtest import observations
from backtest.variables import definitions as d, reference as r, evaluation as e
import test_observations as fixtures
import test_variable_definitions as language


def parameter(name='annual.revenue'):
    return dict(op='parameter', id=name)


def annual(stat='mean', count=3, name='annual.operating_margin'):
    return dict(op='annual', stat=stat, count=count, parameter=name)


def program(expression=None, unit='scalar', display='number'):
    return d.validate(language.bundle(language.entry(language.definition(expression, unit, display))))


def bits(value):
    return struct.pack('>d', value).hex()


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def roots(self, **changes):
        return [dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date, **changes)]

    def run_formula(self, expression=None, unit='scalar', *, view=None, roots=None, limits=None):
        display = 'usd' if unit == 'USD' else 'number'
        plan = r.plan(program(expression, unit, display), roots or self.roots(), limits)
        return r.evaluate(plan, view or self.fixture.view()).to_dict()

    def error(self, code, function, *args, **kwargs):
        with self.assertRaises(d.FormulaError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_constants_still_request_root_admission_without_financial_observations(self):
        plan = r.plan(program(language.constant('12')), self.roots()).to_dict()
        self.assertEqual(plan['provider']['requests'], [])
        self.assertEqual(len(plan['provider']['contexts']), 1)
        block = r.evaluate(r.EvaluationPlan(d.canonical(plan)), self.fixture.view()).to_dict()
        self.assertEqual(block['results'][0]['value'], 12.)
        self.assertEqual(block['observations']['results'], [])
        self.assertTrue(block['observations']['roots'][0]['admitted'])
        roots = [dict(self.roots()[0], mode='latest', date=self.fixture.latest_date)]
        block = self.run_formula(language.constant('12'), view=self.fixture.view(admitted=False), roots=roots)
        self.assertEqual(block['results'][0]['reason'], 'ROOT_NOT_ADMITTED')
        self.assertIsNone(block['results'][0]['value'])

    def test_tree_order_is_binary64_without_reassociation_or_folding(self):
        c, b = language.constant, language.binary
        first = b('add', b('add', c('1e16'), c('-1e16')), c('1'))
        second = b('add', c('1e16'), b('add', c('-1e16'), c('1')))
        self.assertEqual(self.run_formula(first)['results'][0]['value'], 1.)
        self.assertEqual(self.run_formula(second)['results'][0]['value'], 0.)
        self.assertEqual(len(self.run_formula(first)['operations']), 5)

    def test_signed_generic_division_and_zero_denominators(self):
        c, b = language.constant, language.binary
        for left, right, expected in (('-12', '-3', 4.), ('12', '-3', -4.), ('0', '-3', -0.)):
            value = self.run_formula(b('div', c(left, 'USD'), c(right, 'USD')))
            self.assertEqual(bits(value['results'][0]['value']), bits(expected))
            self.assertEqual(value['operations'][-1]['denominator_rule'], 'signed nonzero')
        for denominator in (c('0'), dict(op='neg', arg=c('0'))):
            value = self.run_formula(b('div', c('12'), denominator))['results'][0]
            self.assertEqual((value['value'], value['valid'], value['reason']), (None, False, 'ZERO_DENOMINATOR'))

    def test_overflow_is_unavailable_but_binary64_underflow_result_is_zero(self):
        c, b = language.constant, language.binary
        for expression in (b('mul', c('1e308'), c('2')), b('add', c('1e308'), c('1e308')),
                           b('div', c('1e308'), c('5e-324'))):
            value = self.run_formula(expression)['results'][0]
            self.assertEqual(value['reason'], 'NONFINITE_RESULT')
            self.assertIsNone(value['value'])
        value = self.run_formula(b('mul', c('5e-324'), c('0.1')))['results'][0]
        self.assertTrue(value['valid']); self.assertEqual(value['value'], 0.)

    def test_missing_propagates_through_zero_on_either_side(self):
        self.fixture.annual['2014-06-30']['revenue'] = fixtures.state(None, 'CONFLICTING_INPUT')
        for left, right in ((language.constant('0'), parameter()), (parameter(), language.constant('0'))):
            block = self.run_formula(language.binary('mul', left, right), 'USD')
            self.assertEqual(block['results'][0]['reason'], 'CONFLICTING_INPUT')
            operation = block['operations'][-1]
            self.assertEqual(len(operation['operands']), 2)
            self.assertIn(0., operation['inputs']); self.assertIn(None, operation['inputs'])

    def test_left_unavailable_is_primary_and_right_failure_evidence_survives(self):
        self.fixture.annual['2014-06-30']['revenue'] = fixtures.state(None, 'CONFLICTING_INPUT')
        self.fixture.annual['2014-06-30']['operatingIncome'] = fixtures.state(None, 'NON_USD_INPUT')
        block = self.run_formula(language.binary('add', parameter(), parameter('annual.operating_income')), 'USD')
        self.assertEqual(block['results'][0]['reason'], 'CONFLICTING_INPUT')
        self.assertEqual([item['reason'] for item in block['observations']['results']], ['CONFLICTING_INPUT', 'NON_USD_INPUT'])
        self.assertEqual([item['reason'] for item in block['operations'][:2]], ['CONFLICTING_INPUT', 'NON_USD_INPUT'])

    def test_provider_positive_denominator_rule_is_not_generic_division(self):
        self.fixture.annual['2014-06-30'] = fixtures.annual(-100., -20.)
        self.assertEqual(self.run_formula(parameter('annual.operating_margin'))['results'][0]['reason'], 'NONPOSITIVE_DENOMINATOR')
        expression = language.binary('div', parameter('annual.operating_income'), parameter())
        self.assertEqual(self.run_formula(expression)['results'][0]['value'], .2)

    def test_mean_of_margins_is_oldest_first_not_ratio_of_pooled_amounts(self):
        for year, revenue, income in ((2012, 100., 10.), (2013, 200., 40.), (2014, 300., 90.)):
            self.fixture.annual[f'{year}-06-30'] = fixtures.annual(revenue, income)
        b = language.binary
        expression = b('div', b('mul', parameter(), annual()), parameter('market.enterprise_value'))
        block = self.run_formula(expression)
        mean = ((.1 + .2) + .3) / 3
        self.assertEqual(block['results'][0]['value'], (300. * mean) / 180e6)
        self.assertNotEqual(mean, (10. + 40. + 90.) / (100. + 200. + 300.))
        self.assertEqual(next(item for item in block['operations'] if item['operation'] == 'annual')['inputs'], [.1, .2, .3])

    def test_mean_fold_order_and_extrema_preserve_oldest_signed_zero(self):
        for year, income in ((2012, 1e16), (2013, -1e16), (2014, 1.)):
            self.fixture.annual[f'{year}-06-30'] = fixtures.annual(1., income)
        self.assertEqual(self.run_formula(annual())['results'][0]['value'], 1. / 3)
        for year, income in ((2012, 2 ** 53), (2013, 1), (2014, -(2 ** 53))):
            self.fixture.annual[f'{year}-06-30'] = fixtures.annual(1., income)
        self.assertEqual(self.run_formula(annual(name='annual.operating_income'), 'USD')['results'][0]['value'], 0.)
        for year in (2012, 2013, 2014):
            self.fixture.annual[f'{year}-06-30'] = fixtures.annual(1., -0. if year == 2012 else 0.)
        for stat in ('min', 'max'):
            self.assertEqual(bits(self.run_formula(annual(stat))['results'][0]['value']), bits(-0.))
        one = self.run_formula(annual('mean', 1))['results'][0]['value']
        self.assertEqual(bits(one), bits(0.))
        self.fixture.annual['2014-06-30'] = fixtures.annual(1., -0.)
        self.assertEqual(bits(self.run_formula(annual('mean', 1))['results'][0]['value']), bits(-0.))

    def test_all_annual_members_required_and_nonfinite_mean_is_unavailable(self):
        for stat, expected in (('min', -.1), ('max', .2)):
            self.assertEqual(self.run_formula(annual(stat))['results'][0]['value'], expected)
        self.fixture.annual.pop('2013-06-30')
        for stat in ('mean', 'min', 'max'):
            block = self.run_formula(annual(stat))
            self.assertEqual(block['results'][0]['reason'], 'MISSING_FISCAL_YEAR')
            self.assertEqual(len(block['observations']['results'][0]['members']), 3)
        for year in (2012, 2013, 2014):
            self.fixture.annual[f'{year}-06-30'] = fixtures.annual(1., 1e308)
        self.assertEqual(self.run_formula(annual())['results'][0]['reason'], 'NONFINITE_RESULT')

    def test_references_share_tasks_observations_and_preserve_repeated_output_slots(self):
        base = language.entry(language.definition(parameter(), 'USD', 'usd'), 'saved:base')
        used = language.entry(language.definition(language.binary('add', language.reference(base), language.reference(base)), 'USD', 'usd'), 'draft:twice')
        p = d.validate(language.bundle(base, used, roots=[language.root(used), language.root(base), language.root(used)]))
        roots = self.roots() * 2
        plan = r.plan(p, roots)
        checked = plan.to_dict()
        self.assertEqual(len(checked['provider']['contexts']), 1)
        self.assertEqual(len(checked['provider']['requests']), 1)
        self.assertEqual(len(checked['tasks']), 4)
        self.assertEqual(len(checked['outputs']), 6)
        block = r.evaluate(plan, self.fixture.view()).to_dict()
        self.assertEqual([item['value'] for item in block['results']], [200., 100., 200.] * 2)
        self.assertEqual([item['request'] for item in block['results']], [0, 0, 0, 1, 1, 1])

    def test_equal_date_latest_root_and_derived_ev_contexts_are_distinct(self):
        ev = parameter('market.enterprise_value')
        expression = language.binary('sub', ev, dict(op='at', date=self.fixture.latest_date, arg=ev))
        roots = [dict(self.roots()[0], mode='latest', date=self.fixture.latest_date)]
        block = self.run_formula(expression, 'USD', roots=roots)
        self.assertEqual(block['results'][0]['value'], 10e6)
        self.assertEqual([item['members'][0]['value'] for item in block['observations']['results']], [190e6, 180e6])
        self.assertEqual(len(block['observations']['contexts']), 2)

    def test_dated_references_reselect_provider_report_and_clamp_nested_months(self):
        self.fixture.root_date = '2015-03-31'
        base = language.entry(language.definition(parameter(), 'USD', 'usd'), 'saved:revenue')
        expression = dict(op='lookback', months=1, arg=dict(op='lookback', months=1, arg=language.reference(base)))
        outer = language.entry(language.definition(expression, 'USD', 'usd'), 'draft:history')
        p = d.validate(language.bundle(base, outer))
        block = r.evaluate(r.plan(p, self.roots()), self.fixture.view()).to_dict()
        self.assertEqual([item['date'] for item in block['observations']['contexts']], ['2015-03-31', '2015-02-28', '2015-01-28'])
        self.assertEqual(block['results'][0]['value'], 100.)
        self.assertEqual({item['candidate_rank'] for item in block['observations']['results']}, {1})
        earlier = dict(op='at', date='2013-12-31', arg=parameter('annual.operating_income'))
        block = self.run_formula(earlier, 'USD')
        self.assertEqual(block['results'][0]['value'], 0.)
        self.assertEqual(block['observations']['results'][0]['anchor'], '2013-06-30')

    def test_leap_lookback_uses_provider_and_future_date_maps_to_formula_pointer(self):
        self.fixture.root_date = '2024-05-31'
        expression = dict(op='lookback', months=3, arg=language.constant())
        plan = r.plan(program(expression), self.roots()).to_dict()
        self.assertEqual(plan['provider']['contexts'][1]['months'], 3)
        block = r.evaluate(r.EvaluationPlan(d.canonical(plan)), self.fixture.view()).to_dict()
        self.assertEqual([item['date'] for item in block['observations']['contexts']], ['2024-05-31', '2024-02-29'])
        nested = dict(op='lookback', months=3, arg=dict(op='at', date='2024-03-01', arg=language.constant()))
        error = self.error('FUTURE_DATE', r.plan, program(nested), self.roots())
        self.assertEqual(error.path, '/definitions/0/definition/expression/arg/date')
        # A later second request cannot make an earlier request's future date valid.
        with self.assertRaises(d.FormulaError):
            r.plan(program(dict(op='at', date='2024-05-31', arg=language.constant())),
                   [dict(self.roots()[0], date='2024-05-30'), self.roots()[0]])

    def test_plan_is_immutable_and_every_derived_table_is_checked_before_inputs(self):
        roots = self.roots()
        plan = r.plan(program(), roots)
        roots[0]['symbol'] = 'B'
        self.assertEqual(plan.to_dict()['requests'][0]['symbol'], 'A')
        with self.assertRaises(AttributeError):
            plan.document = '{}'
        for field, value in (('format', 'other'), ('version', True), ('tasks', []), ('outputs', []),
                             ('provider', {}), ('reservations', {}), ('request_roots', [])):
            forged = plan.to_dict(); forged[field] = value
            inputs = Mock()
            self.error('INVALID_SHAPE', r.evaluate, r.EvaluationPlan(d.canonical(forged)), inputs)
            inputs.validate.assert_not_called()
        for forged in ({}, r.EvaluationPlan('{}'), r.EvaluationPlan('invalid')):
            self.error('INVALID_SHAPE', r.evaluate, forged, Mock())

    def test_nonfinite_captured_program_json_has_structured_errors_before_inputs(self):
        submitted = r.plan(program(), self.roots()).to_dict()
        submitted['program'] = 'forged-program-value'
        document = json.dumps(submitted)
        for token in ('NaN', 'Infinity', '-Infinity', '1e999'):
            for program_text in (token, '{"nested":' + token + '}'):
                with self.subTest(program=program_text):
                    forged = document.replace(json.dumps('forged-program-value'), program_text)
                    inputs = Mock()
                    error = self.error('INVALID_SHAPE', r.evaluate, r.EvaluationPlan(forged), inputs)
                    self.assertEqual(error.path, '/program')
                    self.assertEqual(error.to_dict()['errors'][0]['code'], 'INVALID_SHAPE')
                    self.assertEqual(inputs.mock_calls, [])

    def test_request_shapes_modes_types_and_lowerable_limit_shapes(self):
        for roots in ([], {}, [dict(self.roots()[0], extra=1)], [dict(self.roots()[0], symbol=[])],
                      [dict(self.roots()[0], mode='quarterly')], [dict(self.roots()[0], pool='all')]):
            self.error('INVALID_SHAPE', r.plan, program(), roots)
        self.error('INVALID_DATE', r.plan, program(), [dict(self.roots()[0], date='20150102')])
        for name, ceiling in r.CEILINGS.items():
            for value in (True, 0, ceiling + 1):
                self.error('INVALID_SHAPE', r.plan, program(), self.roots(), {name: value})
        self.error('INVALID_SHAPE', r.plan, program(), self.roots(), {'other': 1})

    def test_exact_task_output_and_provider_context_limits(self):
        p = program(language.binary('add', language.constant(), language.constant()))
        self.assertEqual(len(r.plan(p, self.roots(), dict(tasks=3)).to_dict()['tasks']), 3)
        self.error('WORK_LIMIT', r.plan, p, self.roots(), dict(tasks=2))
        self.assertEqual(len(r.plan(p, self.roots() * 2, dict(outputs=2)).to_dict()['outputs']), 2)
        self.error('WORK_LIMIT', r.plan, p, self.roots() * 2, dict(outputs=1))
        roots = [dict(self.roots()[0], symbol='A' + str(index)) for index in range(256)]
        self.assertEqual(len(r.plan(program(), roots).to_dict()['provider']['contexts']), 256)
        self.error('WORK_LIMIT', r.plan, program(), roots + [dict(roots[0], symbol='over')])
        repeated = self.roots() * r.CEILINGS['outputs']
        self.assertEqual(len(r.plan(program(), repeated).to_dict()['outputs']), 8192)
        self.error('WORK_LIMIT', r.plan, program(), repeated + self.roots())

    def test_exact_plan_byte_limit_and_one_byte_excess(self):
        p = program()
        low, high = 1, r.CEILINGS['plan_bytes']
        while low < high:
            middle = (low + high) // 2
            try:
                r.plan(p, self.roots(), dict(plan_bytes=middle))
            except d.FormulaError:
                low = middle + 1
            else:
                high = middle
        accepted = r.plan(p, self.roots(), dict(plan_bytes=low))
        self.assertEqual(len(accepted.document), low)
        self.error('WORK_LIMIT', r.plan, p, self.roots(), dict(plan_bytes=low - 1))

    def test_exact_output_and_retained_byte_boundaries_with_evidence(self):
        p, view = program(parameter(), 'USD', 'usd'), self.fixture.view()
        for name in ('output_bytes', 'retained_bytes'):
            low, high = 1, r.CEILINGS[name]
            while low < high:
                middle = (low + high) // 2
                try:
                    r.evaluate(r.plan(p, self.roots(), {name: middle}), view)
                except (d.FormulaError, observations.ObservationError, ValueError):
                    low = middle + 1
                else:
                    high = middle
            self.assertTrue(r.evaluate(r.plan(p, self.roots(), {name: low}), view).to_dict()['results'][0]['valid'])
            with self.assertRaises((d.FormulaError, observations.ObservationError, ValueError)):
                r.evaluate(r.plan(p, self.roots(), {name: low - 1}), view)

    def test_heavy_evidence_and_provider_budget_remain_complete_or_fail(self):
        self.fixture.annual['2012-06-30']['revenue']['rows'] = [dict(index=index, sha256='c' * 64) for index in range(500)]
        block = self.run_formula(parameter(), 'USD')
        self.assertTrue(block['results'][0]['valid'])
        # Unrequested old evidence is still owned and bounded by the provider.
        plan = r.plan(program(parameter(), 'USD', 'usd'), self.roots(), dict(retained_bytes=20000))
        with self.assertRaises((ValueError, observations.ObservationError, d.FormulaError)):
            r.evaluate(plan, self.fixture.view())

    def test_evidence_references_resolve_and_block_is_detached(self):
        block = r.evaluate(r.plan(program(language.binary('div', parameter(), parameter('market.enterprise_value'))), self.roots()), self.fixture.view())
        snapshot = block.to_json()
        value = block.to_dict()
        tasks = {item['id'] for item in value['operations']}
        nodes = {item['id'] for item in value['program']['nodes']}
        contexts = {item['id'] for item in value['observations']['contexts']}
        observation_ids = {item['id'] for item in value['observations']['results']}
        for operation in value['operations']:
            self.assertIn(operation['node'], nodes); self.assertIn(operation['context'], contexts)
            self.assertTrue(set(operation['operands']) <= tasks)
            if 'observation' in operation:
                self.assertIn(operation['observation'], observation_ids)
        for output in value['results']:
            self.assertIn(output['evidence']['operation'], tasks)
        self.fixture.doCleanups()
        self.assertEqual(block.to_json(), snapshot)
        self.assertEqual(block.to_dict(), json.loads(snapshot))
        value['results'].clear()
        self.assertEqual(len(block.to_dict()['results']), 1)

    def test_calculation_identity_binds_order_generation_projection_and_policy(self):
        p, view = program(), self.fixture.view()
        first = r.evaluate(r.plan(p, self.roots()), view).to_dict()
        self.assertEqual(first['calculation_identity'], r.evaluate(r.plan(p, self.roots()), view).to_dict()['calculation_identity'])
        changed = r.evaluate(r.plan(p, self.roots() * 2), view).to_dict()
        self.assertNotEqual(first['calculation_identity'], changed['calculation_identity'])
        view.identity = 'another-generation'
        changed = r.evaluate(r.plan(p, self.roots()), view).to_dict()
        self.assertNotEqual(first['calculation_identity'], changed['calculation_identity'])
        self.fixture.annual['2014-06-30'] = fixtures.annual(105., 20.)
        changed = r.evaluate(r.plan(p, self.roots()), self.fixture.view()).to_dict()
        self.assertEqual(first['identity']['generation'], changed['identity']['generation'])
        self.assertNotEqual(first['identity']['projection']['content'], changed['identity']['projection']['content'])
        self.assertNotEqual(first['calculation_identity'], changed['calculation_identity'])
        self.assertIn('policy', first['identity']['projection'])
        self.assertEqual(first['identity']['policy']['arithmetic']['division'], 'signed nonzero')

    def test_cancellation_before_observation_during_operations_and_final_encoding(self):
        plan, view = r.plan(program(), self.roots()), self.fixture.view()
        def cancel():
            raise RuntimeError('fixture cancellation')
        with patch.object(observations, 'observe', side_effect=AssertionError('Input access')):
            with self.assertRaisesRegex(RuntimeError, 'fixture cancellation'):
                r.evaluate(plan, view, cancel)
        original_encode = e._encode
        def cancel_final(value, maximum, checkpoint=lambda: None):
            if isinstance(value, dict) and value.get('format') == 'formula-evaluation' and value['operations']:
                return original_encode(value, maximum, cancel)
            return original_encode(value, maximum, checkpoint)
        with patch.object(e, '_encode', side_effect=cancel_final):
            with self.assertRaisesRegex(RuntimeError, 'fixture cancellation'):
                r.evaluate(plan, view)
        original_operation, in_operation = e._operation, False
        def operation(*args, **kwargs):
            nonlocal in_operation
            if isinstance(kwargs.get('value'), float):
                in_operation = True
            return original_operation(*args, **kwargs)
        def during_operation():
            if in_operation:
                cancel()
        with patch.object(e, '_operation', side_effect=operation):
            with self.assertRaisesRegex(RuntimeError, 'fixture cancellation'):
                r.evaluate(plan, view, during_operation)

    def test_closed_stale_and_post_observation_generation_changes_fail_operation(self):
        plan, view = r.plan(program(), self.roots()), self.fixture.view()
        original = observations.observe
        def changed(*args, **kwargs):
            block = original(*args, **kwargs)
            view.identity = 'changed-after-observation'
            return block
        with patch.object(observations, 'observe', side_effect=changed):
            self.error('STALE_INPUT_GENERATION', r.evaluate, plan, view)
        self.fixture.stale = True
        with self.assertRaisesRegex(ValueError, 'stale'):
            r.evaluate(plan, view)
        self.fixture.stale = False
        view.close()
        with self.assertRaisesRegex(ValueError, 'closed'):
            r.evaluate(plan, view)

    def test_staleness_introduced_during_final_encoding_is_rechecked(self):
        original_encode = e._encode
        def changed(value, maximum, checkpoint=lambda: None):
            text = original_encode(value, maximum, checkpoint)
            if isinstance(value, dict) and value.get('format') == 'formula-evaluation' and value['operations']:
                self.fixture.stale = True
            return text
        with patch.object(e, '_encode', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'stale'):
                self.run_formula()

    def test_loaded_definition_reference_and_provider_policies_are_bound(self):
        for owner, field in ((d, '_LOADED_POLICY'), (r, '_LOADED_REFERENCE'), (e, '_LOADED_EVALUATION'), (observations, '_LOADED_POLICY')):
            with self.subTest(field=field), patch.object(owner, field, 'changed'):
                with self.assertRaises((d.FormulaError, observations.ObservationError)):
                    self.run_formula()
        # The language owner detects edits even if it was imported before the
        # reference owner. A later consumer cannot bless stale loaded source.
        with tempfile.TemporaryDirectory() as folder:
            private = Path(folder) / 'definitions.py'
            private.write_bytes(Path(d.__file__).read_bytes())
            with patch.object(d, '__file__', str(private)):
                self.assertEqual(d.policy_fingerprint(), d._LOADED_POLICY)
                private.write_bytes(private.read_bytes() + b'\n# changed private language\n')
                self.error('STALE_INPUT_GENERATION', d.policy_fingerprint)
                self.error('STALE_INPUT_GENERATION', r.policy_fingerprint)
        with tempfile.TemporaryDirectory() as folder:
            private = Path(folder) / 'reference.py'
            private.write_bytes(Path(r.__file__).read_bytes())
            original_encode = e._encode
            def changed(value, maximum, checkpoint=lambda: None):
                text = original_encode(value, maximum, checkpoint)
                if isinstance(value, dict) and value.get('format') == 'formula-evaluation' and value['operations']:
                    private.write_bytes(private.read_bytes() + b'\n# private source changed\n')
                return text
            with patch.object(r, '__file__', str(private)), patch.object(e, '_encode', side_effect=changed):
                self.error('STALE_INPUT_GENERATION', self.run_formula)


if __name__ == '__main__':
    unittest.main()

"""Versioned annual growth uses complete, consecutive provider evidence."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import unittest
from unittest.mock import Mock, patch
from backtest.variables import definitions as d, reference, selection
from backtest.engines.numerical import formula_capabilities
from backtest.application import calculations, strategy_requests
import test_variable_definitions as lang
import test_observations as fixtures
import test_variable_selection as selection_tests
import test_strategy_requests as requests


def make(stat='growth', count=3, version=2, catalog='financial-parameters/1'):
    expr = dict(op='annual', stat=stat, count=count, parameter='annual.revenue')
    definition = lang.definition(expr, 'scalar', 'number')
    definition.update(version=version, parameter_catalog=catalog)
    return definition


def compile_def(definition):
    return d.validate(lang.bundle(lang.entry(definition)))


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def evaluate(self, stat, values):
        for year, value in zip((2012, 2013, 2014), values):
            self.fixture.annual[f'{year}-06-30'] = fixtures.annual(value, 1.)
        root = dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date)
        return reference.evaluate(reference.plan(compile_def(make(stat)), [root]), self.fixture.view()).to_dict()

    def test_growth_and_cagr_count_observations_and_retain_members(self):
        for stat, expected in [('growth', 3.), ('cagr', 1.)]:
            block = self.evaluate(stat, [100., 150., 400.])
            self.assertEqual(block['results'][0]['value'], expected)
            self.assertEqual(block['results'][0]['unit'], 'scalar')
            self.assertEqual(block['operations'][0]['inputs'], [100., 150., 400.])
            self.assertEqual(len(block['observations']['results'][0]['members']), 3)
        self.assertEqual(self.evaluate('growth', [100., 50., -50.])['results'][0]['value'], -1.5)
        self.assertEqual(self.evaluate('cagr', [400., -10., 100.])['results'][0]['value'], -.5)

    def test_actual_history_boundaries_and_temporal_contexts(self):
        self.fixture.annual = {f'{year}-06-30': fixtures.annual(float(2 ** (year - 2005)), 1.)
                               for year in range(2005, 2015)}
        root = dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date)
        for count in (2, 10):
            for stat, expected in (('growth', 2 ** (count - 1) - 1), ('cagr', 1.)):
                block = reference.evaluate(reference.plan(compile_def(make(stat, count)), [root]), self.fixture.view()).to_dict()
                self.assertEqual(block['results'][0]['value'], expected)
                self.assertEqual(len(block['operations'][0]['inputs']), count)
        for op in (dict(op='at', date='2014-01-02'), dict(op='lookback', months=12)):
            definition = make(count=2)
            definition['expression'] = dict(op, arg=definition['expression'])
            block = reference.evaluate(reference.plan(compile_def(definition), [root]), self.fixture.view()).to_dict()
            self.assertEqual(block['results'][0]['value'], 1.)
            self.assertEqual(block['observations']['results'][0]['anchor'], '2013-06-30')
            self.assertEqual(block['operations'][0]['inputs'], [128., 256.])

    def test_growth_resource_reservation_and_cancellation(self):
        program = compile_def(make(count=10))
        root = dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date)
        plan = reference.plan(program, [root])
        record = plan.to_dict()
        self.assertEqual(record['provider']['requests'][0]['count'], 10)
        self.assertGreater(record['reservations']['operations'], len(d.canonical(dict(inputs=[0.] * 10))))
        with self.assertRaises(d.FormulaError) as caught:
            reference.plan(program, [root], dict(output_bytes=100))
        self.assertEqual(caught.exception.code, 'WORK_LIMIT')
        view = Mock()
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            reference.evaluate(plan, view, lambda: (_ for _ in ()).throw(RuntimeError('cancelled')))
        self.assertEqual(view.mock_calls, [])

    def test_endpoint_rules_missing_precedence_and_nonfinite(self):
        for stat, values, reason in [('growth', [0., 1., 2.], 'NONPOSITIVE_DENOMINATOR'),
                                     ('cagr', [-1., 1., -2.], 'NONPOSITIVE_DENOMINATOR'),
                                     ('cagr', [1., 1., 0.], 'NONPOSITIVE_ENDPOINT'),
                                     ('growth', [1e-308, 1., 1e308], 'NONFINITE_RESULT')]:
            self.assertEqual(self.evaluate(stat, values)['results'][0]['reason'], reason)
        self.fixture.annual.pop('2013-06-30')
        self.fixture.annual['2012-06-30'] = fixtures.annual(0., 1.)
        root = dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date)
        block = reference.evaluate(reference.plan(compile_def(make()), [root]), self.fixture.view()).to_dict()
        self.assertEqual(block['results'][0]['reason'], 'MISSING_FISCAL_YEAR')
        self.assertEqual(len(block['observations']['results'][0]['members']), 3)

    def test_version_count_dimensions_and_catalog_are_independent(self):
        for definition in (make(version=1), make(count=1), make(count=11), make(version=4)):
            with self.assertRaises(d.FormulaError): compile_def(definition)
        for catalog in ('financial-parameters/1', 'financial-parameters/2'):
            for count in (2, 10):
                program = compile_def(make(count=count, catalog=catalog))
                self.assertEqual(d.require_program(program), program.to_dict())
                self.assertEqual(program.to_dict()['version'], 1)
        wrong = make(); wrong['output'] = dict(unit='USD', display='usd')
        with self.assertRaises(d.FormulaError): compile_def(wrong)

    def test_mixed_reference_and_unused_v2_rejected_by_both_gates(self):
        old = lang.entry(lang.definition(lang.constant('2')), 'old')
        v2 = lang.definition(lang.reference(old)); v2['version'] = 2
        new = lang.entry(v2, 'new')
        for roots in ([lang.root(old)], [lang.root(new)]):
            program = d.validate(lang.bundle(old, new, roots=roots))
            self.assertEqual(reference.require_program(program), program.to_dict())
            for gate in (selection.require_program, formula_capabilities.require_program):
                with self.assertRaises(d.FormulaError) as caught: gate(program)
                self.assertEqual(caught.exception.code, 'UNSUPPORTED_CAPABILITY')
            root = dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date)
            plan = selection.plan(program, [root], selection_tests.specification(program))
            inputs = Mock()
            with self.assertRaises(d.FormulaError) as caught:
                selection.evaluate(plan, inputs)
            self.assertEqual(caught.exception.code, 'UNSUPPORTED_CAPABILITY')
            self.assertEqual(inputs.mock_calls, [])
        root = dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date)
        block = reference.evaluate(reference.plan(program, [root]), self.fixture.view()).to_dict()
        self.assertEqual(block['results'][0]['value'], 2.)

    def test_application_rejects_v2_before_preparation(self):
        definition = lang.definition(lang.constant('2')); definition['version'] = 2
        entry = lang.entry(definition, 'version2')
        capture = strategy_requests.capture_strategy(requests.intent(requests.formula(entry)), submitted=[entry]).to_dict()
        preparation = Mock()
        owner = calculations.Selectable(preparation)
        self.addCleanup(owner.retire); self.addCleanup(owner.close)
        for engine in ('original', 'experimental'):
            with self.assertRaises(d.FormulaError) as caught:
                owner.calculate('latest', dict(strategy=capture, engine=engine), None, None)
            self.assertEqual(caught.exception.code, 'UNSUPPORTED_CAPABILITY')
        self.assertEqual(preparation.mock_calls, [])

if __name__ == '__main__': unittest.main()

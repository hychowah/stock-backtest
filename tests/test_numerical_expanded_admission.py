"""Frozen numerical admission and formula parity, moved from live Original tests.

These cases moved out of live test files when the experimental engine was
frozen (AGENTS.md, Tests). The live files keep the Original gate. No tier runs
this file; run it directly with tmp/numerical-venv when unfreezing.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from functools import wraps
import hashlib
import io
import unittest
from unittest.mock import Mock, patch

from backtest import observations
from backtest.application import calculations, strategy_requests
from backtest.application import strategy_requests as s
from backtest.application.calculations import Selectable
from backtest.engines.numerical import formula_capabilities
from backtest.inputs import observation_inputs as source
from backtest.variables import definitions as d, library, measures, parameters, reference, selection
import test_annual_growth as growth
import test_observations as fixtures
import test_parameter_admission as admission
import test_strategy_requests as requests
import test_variable_definitions as lang
import test_variable_selection as selection_tests
from test_variable_definitions import bundle, root

EXPANDED_QUALIFIED = 3 in formula_capabilities.capabilities()['definition_versions']
ROOTS = admission.ROOTS
capture = admission.capture
expanded_cases = admission.expanded_cases


def restrict_catalog_two(test):
    """Model a recognized catalog which neither backend has qualified."""
    @wraps(test)
    def run(*args, **kwargs):
        original = frozenset(item for item in selection.QUALIFIED_NAMESPACES
                             if item[1] != parameters.V2)
        numerical = frozenset(item for item in formula_capabilities.QUALIFIED_NAMESPACES
                              if item[1] != parameters.V2)
        with patch.object(selection, 'QUALIFIED_NAMESPACES', original), \
             patch.object(formula_capabilities, 'QUALIFIED_NAMESPACES', numerical):
            return test(*args, **kwargs)
    return run


class ExpandedAdmissionTests(unittest.TestCase):
    def error(self, callback):
        with self.assertRaises(d.FormulaError) as caught:callback()
        self.assertEqual(caught.exception.code,'UNSUPPORTED_CAPABILITY')

    def test_every_v2_case_restores_and_obeys_both_backend_gates(self):
        for entries in expanded_cases():
            with self.subTest(parameter=entries[0]['definition']['expression']):
                captured=capture(entries)
                self.assertEqual(s.require_strategy(captured),captured.to_dict())
                variable=library.VariableCapture(d.canonical(captured.to_dict()['variables']))
                self.assertEqual(library.require_capture(variable),variable.to_dict())
                program=variable.program
                self.assertEqual(d.require_program(program),program.to_dict())
                reference.require_program(program)
                for gate in (selection.require_program,formula_capabilities.require_program):
                    if EXPANDED_QUALIFIED:self.assertEqual(gate(program),program.to_dict())
                    else:self.error(lambda:gate(program))
                for engine in ('original','experimental'):
                    if EXPANDED_QUALIFIED:self.assertEqual(s.check_options(dict(strategy=captured.to_dict(),engine=engine)),captured.to_dict())
                    else:self.error(lambda:s.check_options(dict(strategy=captured.to_dict(),engine=engine)))

    @restrict_catalog_two
    def test_application_modes_reject_before_readiness_financial_or_compiler(self):
        preparation=Mock();owner=Selectable(preparation)
        self.addCleanup(owner.retire);self.addCleanup(owner.close)
        with patch.object(owner,'ready_for',side_effect=AssertionError('No readiness')), \
             patch.object(owner.original,'_financial',side_effect=AssertionError('No financial input')), \
             patch.object(preparation,'_runtime',side_effect=AssertionError('No compiler/runtime')):
            for entries in expanded_cases():
                captured=capture(entries).to_dict()
                for engine in ('original','experimental'):
                    options=dict(strategy=captured,engine=engine)
                    for mode in ('latest','january','custom','random'):
                        self.error(lambda:owner.calculate_into(mode,options,io.BytesIO(),None,None))
                        self.error(lambda:owner.calculate(mode,options,None,None))
                    self.error(lambda:s.check_request(dict(kind='random',options=options)))
                self.error(lambda:owner.preview(captured,ROOTS))
                self.error(lambda:owner.original.preview(captured,ROOTS))
                self.error(lambda:owner.original.calculate_into('latest',dict(strategy=captured),io.BytesIO(),None,None))
        preparation.status.assert_not_called();preparation._runtime.assert_not_called()

    @restrict_catalog_two
    def test_numerical_prepare_rejects_before_tape_kernel_or_input_construction(self):
        from backtest.engines.numerical import formulas
        for entries in (list(expanded_cases())[0],list(expanded_cases())[1],list(expanded_cases())[-1]):
            program=d.validate(bundle(*entries,roots=[root(entries[0])]))
            plan=reference.plan(program,ROOTS)
            inputs=Mock();inputs.validate.side_effect=AssertionError('No inputs.validate')
            with formulas.Evaluator() as evaluator, \
                 patch.object(formulas,'_Tape',side_effect=AssertionError('No compiled tape')), \
                 patch.object(evaluator,'_warm',side_effect=AssertionError('No compiler kernel')):
                self.error(lambda:evaluator.evaluate(plan,inputs))
                self.assertEqual(evaluator.stats['kernel_compilations'],0)
            inputs.validate.assert_not_called()

    def test_new_semantic_source_in_transitive_numerical_and_current_policy_identity(self):
        from backtest.engines.numerical.random import source_identity
        key='backtest/variables/parameters.py'
        self.assertEqual(source_identity()[key],hashlib.sha256(Path(parameters.__file__).read_bytes()).hexdigest())
        first=d.policy_fingerprint();provider=observations.policy_fingerprint()
        with patch.object(parameters,'policy_fingerprint',return_value='b'*64):
            self.assertNotEqual(d.policy_fingerprint(),first)
            self.assertNotEqual(observations.policy_fingerprint(),provider)
        with patch.object(parameters,'_LOADED','changed'):
            for call,error in ((d.policy_fingerprint,d.FormulaError),(observations.policy_fingerprint,observations.ObservationError)):
                with self.assertRaises(error) as caught:call()
                self.assertEqual(caught.exception.code,'STALE_INPUT_GENERATION')
        self.assertIsInstance(d.policy_fingerprint(),str)
        self.assertIsInstance(observations.policy_fingerprint(),str)


class GrowthAdmissionTests(unittest.TestCase):
    setUp = growth.GrowthTests.setUp

    def test_mixed_reference_and_unused_v2_follow_both_gates(self):
        old = lang.entry(lang.definition(lang.constant('2')), 'old')
        v2 = lang.definition(lang.reference(old)); v2['version'] = 2
        new = lang.entry(v2, 'new')
        for roots in ([lang.root(old)], [lang.root(new)]):
            program = d.validate(lang.bundle(old, new, roots=roots))
            self.assertEqual(reference.require_program(program), program.to_dict())
            for gate in (selection.require_program, formula_capabilities.require_program):
                if EXPANDED_QUALIFIED:self.assertEqual(gate(program), program.to_dict())
                else:
                    with self.assertRaises(d.FormulaError) as caught: gate(program)
                    self.assertEqual(caught.exception.code, 'UNSUPPORTED_CAPABILITY')
            root = dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date)
            plan = selection.plan(program, [root], selection_tests.specification(program))
            inputs = Mock()
            if not EXPANDED_QUALIFIED:
                with self.assertRaises(d.FormulaError) as caught:
                    selection.evaluate(plan, inputs)
                self.assertEqual(caught.exception.code, 'UNSUPPORTED_CAPABILITY')
                self.assertEqual(inputs.mock_calls, [])
        root = dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date)
        block = reference.evaluate(reference.plan(program, [root]), self.fixture.view()).to_dict()
        self.assertEqual(block['results'][0]['value'], 2.)

    def test_application_v2_admission_follows_qualified_policy(self):
        definition = lang.definition(lang.constant('2')); definition['version'] = 2
        entry = lang.entry(definition, 'version2')
        capture = strategy_requests.capture_strategy(requests.intent(requests.formula(entry)), submitted=[entry]).to_dict()
        preparation = Mock()
        owner = calculations.Selectable(preparation)
        self.addCleanup(owner.retire); self.addCleanup(owner.close)
        for engine in ('original', 'experimental'):
            if EXPANDED_QUALIFIED:
                self.assertEqual(strategy_requests.check_options(dict(strategy=capture, engine=engine)), capture)
            else:
                with self.assertRaises(d.FormulaError) as caught:
                    owner.calculate('latest', dict(strategy=capture, engine=engine), None, None)
                self.assertEqual(caught.exception.code, 'UNSUPPORTED_CAPABILITY')
        self.assertEqual(preparation.mock_calls, [])


class MeasureParityTests(unittest.TestCase):
    def test_each_measure_executes_in_larger_expression(self):
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        income = dict(revenue=100., costOfRevenue=40., operatingIncome=20., ebit=17., eps=2., epsDiluted=1.5, netIncome=90., weightedAverageShsOut=10., weightedAverageShsOutDil=15.)
        fixture.annual['2014-06-30'] = {k: fixtures.state(v) for k, v in income.items()}
        view = fixture.view()
        db = fixture.db
        for endpoint, values in (
            ('balance-sheet-statement', dict(totalDebt=70., cashAndCashEquivalents=10., totalCurrentAssets=80., totalCurrentLiabilities=30., totalStockholdersEquity=90., goodwill=8., intangibleAssets=7., totalAssets=200.)),
            ('cash-flow-statement', dict(freeCashFlow=14., operatingCashFlow=20., capitalExpenditure=-9.))):
            db.execute('INSERT INTO observation_annual VALUES(?,?,?,?)', ('A', endpoint, '2014-06-30',
                source.encoded({k: fixtures.state(v) for k, v in values.items()})))
        evidence = dict(snapshot=dict(market_cap=200., enterprise_value=250.),
            metrics=dict(ev_ebitda=[4., .25000000000000006], ev_ebitda_3y=[5., .2]),
            filters=dict(profit_margin=12., pe=8., pb=2., fcf_yield=7., price_fcf=9., peg=1.5,
                roe=10., current_ratio=2., interest_coverage=3., debt_equity=.7,
                return_1y=15., return_3y=25., operating_yield_spread_3y=4.))
        db.execute('INSERT INTO observation_measure_contexts VALUES(?,?,?,?,?)',
            ('historical', 'legacy', fixture.root_date, 'A', source.encoded(evidence)))
        db.execute('DELETE FROM observation_metadata')
        metadata = source.finish(db, fixture.latest_date, scopes=[dict(mode='historical', pool='legacy',
            context_date=fixture.root_date, book=2015)])
        view._expected = metadata
        expected = dict(gross_profit=60., gross_margin=.6, operating_margin=.2, net_margin=.12,
            ebit=17., ebitda=54e6, free_cash_flow=14., operating_cash_flow_plus_capex=11.,
            total_debt=70., net_debt=60., working_capital=50., tangible_book_equity=75.,
            market_cap=200., enterprise_value=180e6, basic_eps=2., diluted_eps=1.5,
            price_sales=2., debt_assets=.35, pe=8., pb=2., fcf_yield=.07, price_fcf=9.,
            peg=1.5, roe=.1, current_ratio=2., interest_coverage=3., debt_equity=.7,
            return_1y=.15, return_3y=.25, ev_ebitda=4., ev_ebitda_3y=5.,
            ebitda_yield=.25000000000000006, operating_yield_spread_3y=.04)
        root = dict(symbol='A', pool='legacy', mode='historical', date=fixture.root_date)
        for descriptor in measures.catalog():
            key = descriptor['id']
            with self.subTest(measure=key):
                bundle = measures.bundle([key])
                expression = dict(op='add', left=dict(op='ref', **bundle['roots'][0]),
                    right=dict(op='constant', value='0', unit=descriptor['unit']))
                definition = lang.definition(expression, descriptor['unit'], descriptor['display'])
                definition.update(version=3, parameter_catalog=parameters.V3)
                outer = lang.entry(definition, 'outer')
                bundle['definitions'].append(outer)
                bundle['roots'] = [lang.root(outer)]
                plan = reference.plan(d.validate(bundle), [root])
                block = reference.evaluate(plan, view).to_dict()
                from backtest.engines.numerical import formula_capabilities
                if 3 in formula_capabilities.capabilities()['definition_versions']:
                    from backtest.engines.numerical import formulas
                    from scalar_qualification import compare_blocks
                    with formulas.Evaluator() as evaluator:
                        numerical = evaluator.evaluate(plan, view).to_dict()
                    compare_blocks([block], [numerical])
                result = block['results'][0]
                self.assertTrue(result['valid'], result)
                self.assertEqual(result['value'], expected[key])

    def test_capture_restore_and_unused_gates_before_financial_access(self):
        import tempfile
        from unittest.mock import Mock, patch
        from backtest.variables import library, selection
        from backtest.engines.numerical import formula_capabilities
        bundle = measures.bundle(['gross_margin'])
        with tempfile.TemporaryDirectory() as folder:
            store = library.Store(Path(folder) / 'private.sqlite')
            store.create('Private fixture', lang.definition(lang.constant('1')))
            capture = store.capture(bundle['roots'], submitted=bundle['definitions'])
            with patch.object(measures, 'bundle', side_effect=AssertionError('registry access')), patch.object(measures, 'catalog', side_effect=AssertionError('registry access')):
                self.assertEqual(library.require_capture(library.VariableCapture(capture.to_json())), capture.to_dict())
        old = lang.entry(lang.definition(lang.constant('2')), 'old')
        new_definition = lang.definition(lang.constant('3'))
        new_definition.update(version=3, parameter_catalog=parameters.V3)
        new = lang.entry(new_definition, 'new')
        for roots in ([lang.root(old)], [lang.root(new)]):
            program = d.validate(lang.bundle(old, new, roots=roots))
            for gate in (selection.require_program, formula_capabilities.require_program):
                if 3 in formula_capabilities.capabilities()['definition_versions']:
                    self.assertEqual(gate(program), program.to_dict())
                else:
                    with self.assertRaises(d.FormulaError) as error:
                        gate(program)
                    self.assertEqual(error.exception.code, 'UNSUPPORTED_CAPABILITY')
        from backtest.application import calculations, strategy_requests
        import test_strategy_requests as requests
        capture = strategy_requests.capture_strategy(requests.intent(requests.formula(new)), submitted=[new]).to_dict()
        preparation = Mock()
        owner = calculations.Selectable(preparation)
        self.addCleanup(owner.retire)
        self.addCleanup(owner.close)
        for engine in ('original','experimental'):
            if 3 in formula_capabilities.capabilities()['definition_versions']:
                self.assertEqual(strategy_requests.check_options(dict(strategy=capture,engine=engine)), capture)
            else:
                with self.assertRaises(d.FormulaError) as error:
                    owner.calculate('latest', dict(strategy=capture, engine=engine), None, None)
                self.assertEqual(error.exception.code, 'UNSUPPORTED_CAPABILITY')
        self.assertEqual(preparation.mock_calls, [])


if __name__ == '__main__':
    unittest.main()

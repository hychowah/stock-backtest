"""Private candidate application exercise; skipped until admission is qualified."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import unittest
import os
import subprocess
import json
from datetime import date
from unittest.mock import patch

from backtest.application import strategy_requests
from backtest.application import scalar_execution
from backtest.engines.numerical import formula_capabilities, formulas
from backtest.variables import definitions, parameters, reference
from backtest.inputs import observation_inputs
from scalar_qualification import Scenario, compare_artifacts, compare_blocks
from guarded_numerical_entries import install
import test_strategy_requests as intent
import test_variable_definitions as language
import test_observations as fixtures
from test_scalar_execution import Fixture


def expanded_capture(pool, order):
    growth = dict(op='annual', parameter='annual.revenue', stat='growth', count=3)
    expression = dict(op='positive_div', left=growth, right=language.constant('2'))
    definition = language.definition(expression, 'scalar', 'percent')
    definition.update(version=3, parameter_catalog=parameters.V3)
    entry = language.entry(definition, 'phase11:expanded')
    strategy = intent.intent(intent.formula(entry), rank_to=10)
    strategy['pool'] = pool
    strategy['selection']['selection_order'] = order
    return strategy_requests.capture_strategy(strategy, submitted=[entry])


@unittest.skipUnless(3 in formula_capabilities.capabilities()['definition_versions'],
                     'Expanded application admission remains closed')
class CandidateApplicationTests(unittest.TestCase):
    def setUp(self):
        if sys.platform == 'win32':
            before, original_null = subprocess.Popen, os.devnull
            install(Path(__file__).resolve().parents[1])
            self.addCleanup(setattr, subprocess, 'Popen', before)
            self.addCleanup(setattr, os, 'devnull', original_null)

    def test_modes_pools_and_selection_orders(self):
        for pool in ('cached', 'legacy'):
            for order in ('filter_first', 'rank_first'):
                with self.subTest(pool=pool, order=order), Scenario(
                        companies=12, first=2015, last=2016,
                        capture=expanded_capture(pool, order)) as scenario:
                    for mode in ('latest', 'january', 'custom', 'random'):
                        with self.subTest(mode=mode):
                            options = scenario.options(mode, **({'trials': 2} if mode == 'random' else {}))
                            original, _, _ = scenario.run_backend('original', mode, options)
                            numerical, receipt, _ = scenario.run_backend('experimental', mode, options)
                            compared = compare_artifacts(original, numerical)
                            self.assertGreater(compared['holdings'], 0)
                            self.assertGreater(compared['operations'], 0)
                            self.assertEqual(receipt['closure']['state'], 'closed')

    def test_application_uses_explicit_owner_on_equal_dates(self):
        definition = language.definition(dict(op='parameter', id='owner.ev_ebitda'))
        definition.update(version=3, parameter_catalog=parameters.V3)
        entry = language.entry(definition, 'phase11:owner')
        strategy = intent.intent(intent.formula(entry), rank_to=10)
        strategy['pool'] = 'cached'
        capture = strategy_requests.capture_strategy(strategy, submitted=[entry])
        finish = observation_inputs.finish
        def adversarial_finish(db, *args, **kwargs):
            # Change only the private fixture's stored owner evidence before
            # its content identity is sealed. The dated financial owner keeps
            # its original independent inputs and calculation.
            rows = db.execute('SELECT mode,pool,context_date,symbol,evidence_json '
                              'FROM observation_measure_contexts').fetchall()
            for mode, pool, day, symbol, document in rows:
                evidence = json.loads(document)
                if 'metrics' in evidence:
                    if symbol == 'Q0000':
                        db.execute('DELETE FROM observation_measure_contexts WHERE mode=? AND pool=? AND context_date=? AND symbol=?',
                                   (mode,pool,day,symbol))
                        continue
                    if symbol == 'Q0001':
                        evidence['metrics'].pop('ev_ebitda', None)
                    else:
                        evidence['metrics']['ev_ebitda'] = [7.0, .37]
                    db.execute('UPDATE observation_measure_contexts SET evidence_json=? '
                               'WHERE mode=? AND pool=? AND context_date=? AND symbol=?',
                               (observation_inputs.encoded(evidence),mode,pool,day,symbol))
            return finish(db, *args, **kwargs)
        with patch.object(observation_inputs, 'finish', side_effect=adversarial_finish):
            with Scenario(companies=4, first=2015, last=2016, capture=capture) as scenario:
                for mode in ('latest', 'january', 'custom', 'random'):
                    with self.subTest(mode=mode):
                        options = scenario.options(mode, **({'trials': 2} if mode == 'random' else {}))
                        original, _, _ = scenario.run_backend('original', mode, options)
                        numerical, receipt, _ = scenario.run_backend('experimental', mode, options)
                        compared = compare_artifacts(original, numerical)
                        self.assertGreater(compared['holdings'], 0)
                        values = [row['value']['ranking_value'] for row in numerical.records()
                                  if row['type'] in ('holding', 'screen')]
                        self.assertTrue(values)
                        if mode in ('latest', 'january'):
                            self.assertTrue(all(value == 7.0 for value in values))
                        else:
                            self.assertTrue(all(value != 7.0 for value in values))
                        unavailable = set()
                        for record in numerical.records():
                            if record['type'] != 'evaluation':
                                continue
                            observed = record['value']['block']['observations']
                            roots = {item['root']: item for item in observed['roots']}
                            for item in observed['results']:
                                if not item['valid']:
                                    unavailable.add(item['reason'])
                                    continue
                                root = roots[item['root']]
                                member = item['members'][0]
                                owner = member['evidence']['owner']
                                if mode in ('latest', 'january'):
                                    self.assertEqual(owner['metrics']['ev_ebitda'], [7.0, .37])
                                    self.assertEqual(member['value'], 7.0)
                                else:
                                    self.assertEqual(owner['policy'], 'dated-owner')
                                    number = int(root['symbol'][1:])
                                    entry_day = date.fromisoformat(root['date'])
                                    fiscal = date.fromisoformat(member['fiscal_date'])
                                    origin = date(2015, 1, 1)
                                    fiscal_price = 20. + (fiscal-origin).days*.0005 + number*.0001
                                    entry_price = 20. + (entry_day-origin).days*.0005 + number*.0001
                                    cap, enterprise = 120e6+number*1e5, 180e6+number*1e5
                                    expected = (cap*(entry_price/fiscal_price)+(enterprise-cap)) / ((1/(5+number/10000))*enterprise)
                                    self.assertEqual(member['value'], expected)
                        if mode in ('latest', 'january'):
                            self.assertIn('PREPARED_MEASURE_CONTEXT_UNAVAILABLE', unavailable)
                            self.assertIn('LEGACY_MEASURE_UNAVAILABLE', unavailable)
                        if mode == 'random':
                            self.assertGreater(numerical.manifest['summary']['execution']['workers'], 0)
                        self.assertEqual(receipt['closure']['state'], 'closed')

    def test_expanded_missing_and_invalid_arithmetic_reasons(self):
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = dict(symbol='A', pool='legacy', mode='historical', date=fixture.root_date)
        cases = [('growth', [0., 2., 3.], 'NONPOSITIVE_DENOMINATOR'),
                 ('cagr', [1., 2., 0.], 'NONPOSITIVE_ENDPOINT'),
                 ('growth', [1., None, 3.], 'MISSING_INPUT'),
                 ('cagr', [1., None, 3.], 'MISSING_INPUT')]
        with formulas.Evaluator() as evaluator:
            for statistic, values, reason in cases:
                with self.subTest(statistic=statistic, values=values):
                    for year, value in zip((2012,2013,2014), values):
                        fixture.annual[f'{year}-06-30']['revenue'] = fixtures.state(value, None if value is not None else 'MISSING_INPUT')
                    definition = language.definition(dict(op='annual', parameter='annual.revenue', stat=statistic, count=3))
                    definition.update(version=3, parameter_catalog=parameters.V3)
                    program = definitions.validate(language.bundle(language.entry(definition)))
                    plan = reference.plan(program, [root]); view = fixture.view()
                    expected = reference.evaluate(plan, view).to_dict()
                    actual = evaluator.evaluate(plan, view).to_dict()
                    compare_blocks([expected], [actual])
                    self.assertEqual(actual['results'][0]['reason'], reason)
            fixture.annual['2014-06-30']['revenue'] = fixtures.state(None, 'MISSING_INPUT')
            expression = dict(op='positive_div', left=dict(op='parameter', id='annual.revenue'),
                              right=language.constant('0', 'USD'))
            definition = language.definition(expression)
            definition.update(version=3, parameter_catalog=parameters.V3)
            program = definitions.validate(language.bundle(language.entry(definition)))
            plan = reference.plan(program, [root]); view = fixture.view()
            expected = reference.evaluate(plan, view).to_dict()
            actual = evaluator.evaluate(plan, view).to_dict()
            compare_blocks([expected], [actual])
            self.assertEqual(actual['results'][0]['reason'], 'MISSING_INPUT')

    def test_owner_work_rejects_before_observation_when_aggregate_bound_is_low(self):
        definition = language.definition(dict(op='parameter', id='owner.ev_ebitda'))
        definition.update(version=3, parameter_catalog=parameters.V3)
        entry = language.entry(definition, 'phase11:owner-bound')
        strategy = intent.intent(intent.formula(entry))
        strategy['pool'] = 'cached'
        capture = strategy_requests.capture_strategy(strategy, submitted=[entry])
        fixture = Fixture(1); self.addCleanup(fixture.db.close)
        records = []
        with fixture.view() as view:
            view._bounds['max_financial'] = 100000
            with patch.object(scalar_execution, 'MAX_INSPECTED_ROWS', 100000), \
                 patch.object(scalar_execution.reference, 'evaluate', side_effect=AssertionError('Unexpected observation')):
                with self.assertRaises(definitions.FormulaError) as error:
                    scalar_execution.Executor(capture, view, records.append).select(
                        fixture.db, 1, date(2015,1,2), date(2015,1,5))
        self.assertEqual(error.exception.code, 'WORK_LIMIT')
        self.assertEqual(records, [])


if __name__ == '__main__':
    unittest.main()

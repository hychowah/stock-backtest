"""Actual private preparation/provider chains for reference formulas."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from datetime import date
import json
import unittest

from backtest.financial import books
from backtest.inputs import daily
from backtest.variables import definitions as d, reference as r
from prepared_inputs_fixture import PreparedInputs
import test_observations as provider_fixtures
import test_variable_definitions as language
import test_variable_evaluation as expressions


class IntegrationTests(unittest.TestCase):
    def test_complete_population_ranks_and_denials_also_apply_to_constants(self):
        fixture = provider_fixtures.PopulationAdmissionTests('test_complete_population_buffer_order_and_uncached_names')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.add_population()
        _, ranks = books.candidates(daily.histories(fixture.db), date(2015, 1, 2))
        roots = [dict(symbol=symbol, pool=pool, mode='historical', date='2015-01-02')
                 for symbol, pool in (('Z249', 'legacy'), ('Z250', 'legacy'), ('Z005', 'legacy'), ('Z250', 'cached'))]
        plan = r.plan(expressions.program(language.constant('13')), roots)
        inputs = fixture.view()
        block = r.evaluate(plan, inputs)
        values = block.to_dict()
        self.assertEqual([row['valid'] for row in values['results']], [True, False, False, True])
        self.assertEqual(values['observations']['roots'][0]['candidate_rank'], ranks['Z249'])
        self.assertEqual(values['observations']['roots'][0]['candidate_rank'], 250)
        self.assertEqual([row['reason'] for row in values['observations']['roots']],
                         [None, 'OUTSIDE_LEGACY_BUFFER', 'MISSING_CACHED_PRICES', None])
        self.assertEqual(values['observations']['results'], [])
        alone = r.evaluate(r.plan(expressions.program(), [roots[1]]), inputs).to_dict()
        self.assertEqual(alone['results'][0]['reason'], 'ROOT_NOT_ADMITTED')
        ev = r.evaluate(r.plan(expressions.program(expressions.parameter('market.enterprise_value'), 'USD', 'usd'), [roots[-1]]), inputs).to_dict()
        self.assertEqual(ev['results'][0]['value'], 180e6)
        self.assertEqual(block.to_dict(), json.loads(block.to_json()))

    def test_real_research_daily_provider_evaluator_chain_detaches(self):
        ratio = language.entry(language.definition(language.binary('div', expressions.parameter(),
            expressions.parameter('market.enterprise_value'))), 'draft:ratio')
        margin = language.entry(language.definition(expressions.annual()), 'draft:margin')
        constant = language.entry(language.definition(language.constant('12')), 'draft:constant')
        program = d.validate(language.bundle(ratio, margin, constant,
            roots=[language.root(row) for row in (ratio, margin, constant)]))
        roots = [dict(symbol='TEST', pool='legacy', mode=mode, date=day)
                 for mode, day in (('historical', '2015-01-02'), ('latest', '2015-10-20'))]
        with PreparedInputs() as prepared, prepared.view() as inputs:
            block = r.evaluate(r.plan(program, roots), inputs)
            values = block.to_dict()
            self.assertEqual(values['identity']['generation'], inputs.identity)
            self.assertEqual([row['valid'] for row in values['results']], [True, False, True] * 2)
            self.assertEqual(values['results'][4]['reason'], 'MISSING_INPUT')
            self.assertEqual(values['results'][3]['value'], 100e6 / 270e6)
            self.assertEqual([row['value'] for row in values['results'][2::3]], [12., 12.])
            for observed in values['observations']['results']:
                self.assertEqual(observed['candidate_rank'], 1)
                self.assertIsNotNone(observed['anchor_report'])
            self.assertIn('income-statement', block.to_json())
        detached = block.to_json()
        self.assertEqual(block.to_dict(), json.loads(detached))
        self.assertNotIn('return', detached)
        self.assertEqual(values['observations']['roots'][1]['admission_evidence']['valuation_price'], ['2015-10-20', 22])


if __name__ == '__main__':
    unittest.main()

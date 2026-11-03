"""Independent compiled arithmetic probes under the declared admission policy."""
from contextlib import nullcontext
import math
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

import numpy as np
from numba import njit

from backtest.engines.numerical import formulas
from backtest.engines.numerical import formula_capabilities
from backtest.variables import definitions, parameters, reference
import test_observations as fixtures
import test_variable_definitions as language
from scalar_qualification import compare_blocks


class CompiledOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kernel = staticmethod(njit(fastmath=False, error_model='numpy', boundscheck=True)(formulas._execute))

    def run_tape(self, tape, members, count):
        tape = np.array(tape, dtype=np.int32)
        values, reasons = np.zeros(count), np.zeros(count, dtype=np.int32)
        self.kernel(tape, np.zeros(count), np.ones(count, dtype=np.bool_),
                    np.zeros(count, dtype=np.int32), np.array(members, dtype=np.float64),
                    values, reasons, 0, len(tape))
        return values, reasons

    def test_growth_and_cagr_endpoint_rules(self):
        for code, first, last, expected, reason in (
            (formulas._GROWTH, 2., -1., -1.5, 0),
            (formulas._CAGR, 2., 8., 1., 0),
            (formulas._GROWTH, 0., 1., 0., formulas._NONPOSITIVE),
            (formulas._CAGR, 1., 0., 0., formulas._ENDPOINT)):
            with self.subTest(code=code, first=first, last=last):
                values, reasons = self.run_tape([[1, 0, -1, -1, 0, 0],
                    [code, 0, -1, 3, 2, 1]], [first, 3., last], 1)
                self.assertEqual(reasons[0], reason)
                if not reason:
                    self.assertEqual(values[0], expected)

    def test_positive_division_rejects_negative_and_zero(self):
        for denominator in (-2., -0., 0., 2.):
            values, reasons = self.run_tape([[1, 0, -1, -1, 0, 1],
                [1, 1, -1, -1, 1, 1], [formulas._POSITIVE_DIV, 2, 0, 1, -1, 1]],
                [4., denominator], 3)
            self.assertEqual(reasons[2], formulas._NONPOSITIVE if denominator <= 0 else 0)
            if denominator > 0:
                self.assertEqual(values[2], 2.)

    def test_closed_gate_private_arithmetic_compares_complete_operations(self):
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = dict(symbol='A', pool='legacy', mode='historical', date=fixture.root_date)
        expressions = [
            dict(op='positive_div', left=language.constant('4'), right=language.constant('-2')),
            dict(op='annual', parameter='annual.revenue', stat='growth', count=3),
            dict(op='annual', parameter='annual.revenue', stat='cagr', count=3),
        ]
        for expression in expressions:
            definition = language.definition(expression)
            definition.update(version=3, parameter_catalog=parameters.V3)
            program = definitions.validate(language.bundle(language.entry(definition)))
            plan = reference.plan(program, [root])
            view = fixture.view()
            expected = reference.evaluate(plan, view).to_dict()
            # This is a private arithmetic probe, not application admission or
            # qualification. The public capability policy remains unchanged.
            with patch.object(formula_capabilities, 'require_program', reference.require_program):
                with formulas.Evaluator() as evaluator:
                    actual = evaluator.evaluate(plan, view).to_dict()
            self.assertEqual(actual['operations'], expected['operations'])
            self.assertEqual(actual['results'], expected['results'])
            self.assertEqual(actual['observations'], expected['observations'])

    def test_growth_and_cagr_extreme_complete_evidence(self):
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = dict(symbol='A', pool='legacy', mode='historical', date=fixture.root_date)
        # Each case uses the same admitted report anchor and an independently
        # constructed oldest-first income spine. The comparator checks every
        # observation, operation and result, including signed zero.
        cases = [
            ('growth', 2, 1e-300, 1e-100, True, None, 1e200),
            ('cagr', 2, 1e-300, 1e-100, True, None, 1e200),
            ('growth', 10, 1e-308, 1e308, False, 'NONFINITE_RESULT', None),
            ('cagr', 10, 1e-308, 1e308, False, 'NONFINITE_RESULT', None),
            ('growth', 2, 1e308, 5e-324, True, None, -1.0),
            ('cagr', 10, 1e308, 5e-324, True, None, -1.0),
            ('growth', 10, -0.0, 1.0, False, 'NONPOSITIVE_DENOMINATOR', None),
            ('cagr', 2, -0.0, 1.0, False, 'NONPOSITIVE_DENOMINATOR', None),
            ('growth', 2, 1.0, -0.0, True, None, -1.0),
            ('cagr', 10, 1.0, -0.0, False, 'NONPOSITIVE_ENDPOINT', None),
            ('growth', 10, 1.0, 1.0, True, None, 0.0),
            ('cagr', 2, 1.0, 1.0, True, None, 0.0),
        ]
        for statistic, count, first, last, valid, reason, value in cases:
            with self.subTest(statistic=statistic, count=count, first=first, last=last):
                values = [1.0] * count
                values[0], values[-1] = first, last
                fixture.annual = {f'{year}-06-30': fixtures.annual(member, 1.0)
                                  for year, member in zip(range(2015-count, 2015), values)}
                definition = language.definition(dict(op='annual', parameter='annual.revenue',
                                                      stat=statistic, count=count))
                definition.update(version=2, parameter_catalog=parameters.V1)
                program = definitions.validate(language.bundle(language.entry(definition)))
                plan = reference.plan(program, [root]); view = fixture.view()
                expected = reference.evaluate(plan, view).to_dict()
                # A qualified policy uses its real gate. A closed policy can
                # still check compiled arithmetic in isolation through reference admission.
                admission = (nullcontext() if 2 in formula_capabilities.capabilities()['definition_versions']
                             else patch.object(formula_capabilities, 'require_program', reference.require_program))
                with admission, formulas.Evaluator() as evaluator:
                    actual = evaluator.evaluate(plan, view).to_dict()
                compare_blocks([expected], [actual])
                result = actual['results'][0]
                self.assertEqual((result['valid'], result['reason']), (valid, reason))
                self.assertEqual(result['value'], value)
                if value == 0.0:
                    self.assertEqual(math.copysign(1.0, result['value']), 1.0)
                self.assertEqual(len(actual['observations']['results'][0]['members']), count)


if __name__ == '__main__':
    unittest.main()

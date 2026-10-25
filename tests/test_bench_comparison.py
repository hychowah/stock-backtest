"""Prospective paired-protocol checks; no engines or market-data assets."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from bench_comparison import ComparisonError, ComparisonLedger, ComparisonProtocol, COSTS, STEPS


def protocol(**changes):
    values = dict(configuration=dict(requested=1, samples=[['2025-06-02']]),
        binding=dict(generation='fixture'), environment=dict(python='fixture'),
        costs=dict.fromkeys(COSTS, 10.), whole_seconds=100.,
        max_control_drift=2., max_bracket_seconds=90.)
    values.update(changes)
    return ComparisonProtocol.freeze(**values)


class ProtocolTests(unittest.TestCase):
    def test_costs_include_all_work_and_reject_the_old_four_control_floor(self):
        costs = dict.fromkeys(COSTS, 1.)
        costs.update(request=4 * 598.52 + 2 * 120.20, setup=2 * 148.33)
        with self.assertRaisesRegex(ComparisonError, 'infeasible_costs'):
            protocol(costs=costs, whole_seconds=2700.)
        costs.update(request=2 * 598.52 + 2 * 180.)
        self.assertTrue(protocol(costs=costs, whole_seconds=2700.).identity)

    def test_freeze_owns_copies_of_nested_settings_and_dates(self):
        config = dict(requested=1, samples=[['2025-06-02']])
        item = protocol(configuration=config)
        identity = item.identity
        config['samples'][0][0] = '2025-06-03'
        item.value['configuration']['samples'].clear()
        self.assertEqual(item.identity, identity)
        self.assertEqual(item.value['configuration']['samples'], [['2025-06-02']])

    def test_invalid_costs_order_dates_and_nonfinite_values_reject(self):
        for changes in (dict(costs={}), dict(whole_seconds=float('inf')),
                        dict(order=STEPS[::-1]), dict(max_control_drift=.5),
                        dict(configuration=dict(requested=2, samples=[['2025-06-02']]))):
            with self.subTest(changes=changes), self.assertRaises(ComparisonError):
                protocol(**changes)

    def test_one_complete_contemporary_bracket_requires_closure(self):
        ledger = ComparisonLedger(protocol())
        for step in STEPS:
            ledger.begin(step)
            ledger.finish(step, dict(financial_agreement=True, closed=True, request_seconds=1.))
        with self.assertRaisesRegex(ComparisonError, 'incomplete'):
            ledger.result()
        result = ledger.result(closed=True)
        self.assertEqual(result['status'], 'fixture_pair_complete')
        self.assertEqual(result['speed_gate'], 'unqualified')
        with self.assertRaises(ComparisonError):
            ledger.begin(STEPS[0])

    def test_stop_failure_and_cost_overrun_cannot_be_resumed(self):
        for kind in ('stop', 'disagreement', 'cost'):
            ledger = ComparisonLedger(protocol())
            ledger.begin(STEPS[0])
            if kind == 'stop':
                ledger.stop('cancelled')
            else:
                with self.assertRaises(ComparisonError):
                    if kind == 'cost':
                        ledger.charge('setup', 11.)
                    else:
                        ledger.finish(STEPS[0], dict(financial_agreement=False, closed=True))
            for action in (lambda: ledger.begin(STEPS[1]), lambda: ledger.result(closed=True)):
                with self.assertRaises(ComparisonError):
                    action()

    def test_old_bracket_or_control_drift_cannot_become_a_valid_pair(self):
        for problem in ('time', 'drift'):
            now = [0.]
            ledger = ComparisonLedger(protocol(), clock=lambda: now[0])
            for number, step in enumerate(STEPS):
                ledger.begin(step)
                if problem == 'time' and number == 3:
                    now[0] = 95.
                seconds = 3. if problem == 'drift' and number == 3 else 1.
                ledger.finish(step, dict(financial_agreement=True, closed=True, request_seconds=seconds))
            with self.assertRaisesRegex(ComparisonError, 'noncontemporary|control_drift'):
                ledger.result(closed=True)


if __name__ == '__main__':
    unittest.main()

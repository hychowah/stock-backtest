"""Prospective paired-protocol checks; no engines or market-data assets."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from pathlib import Path
import sys
import unittest

from tools.experiments.bench_comparison import ComparisonError, ComparisonLedger, ComparisonProtocol, COSTS, STEPS, STEP_COSTS, validate_prospective


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
                    now[0] = 89.
                seconds = 3. if problem == 'drift' and number == 3 else 1.
                ledger.finish(step, dict(financial_agreement=True, closed=True, request_seconds=seconds))
            if problem == 'time': now[0] = 95.
            with self.assertRaisesRegex(ComparisonError, 'noncontemporary|control_drift'):
                ledger.result(closed=True)

    def test_bracket_expiry_stops_before_another_request(self):
        now = [0.]
        ledger = ComparisonLedger(protocol(), clock=lambda: now[0])
        ledger.begin(STEPS[0])
        ledger.finish(STEPS[0], dict(financial_agreement=True, closed=True, request_seconds=1.))
        now[0] = 95.
        with self.assertRaisesRegex(ComparisonError, 'noncontemporary'): ledger.begin(STEPS[1])
        self.assertEqual(ledger.stopped, 'noncontemporary')

    def test_step_limits_survive_freeze_and_reject_overrun_with_aggregate_headroom(self):
        import copy
        allocations = {step: dict.fromkeys(STEP_COSTS, 2.5) for step in STEPS}
        frozen = protocol(step_costs=allocations)
        changed = copy.deepcopy(allocations)
        changed[STEPS[0]]['request'] -= .5
        changed[STEPS[1]]['request'] += .5
        self.assertNotEqual(frozen.identity, protocol(step_costs=changed).identity)
        self.assertEqual(frozen.value['costs'], protocol(step_costs=changed).value['costs'])
        ledger = ComparisonLedger(frozen)
        ledger.begin(STEPS[0])
        self.assertEqual(ledger.remaining('request'), 2.5)
        with self.assertRaisesRegex(ComparisonError, 'limit'): ledger.charge('request', 2.6)
        self.assertLess(ledger.costs['request'], frozen.value['costs']['request'])
        with self.assertRaises(ComparisonError): ledger.begin(STEPS[1])

    def test_prospective_declaration_costs_order_gates_and_stdin_only_route(self):
        import copy
        import json
        import subprocess
        path = Path(__file__).resolve().parents[1] / 'docs/plans/compiled-backtest/phases/CB-02/execution/prospective-comparison.json'
        value = json.loads(path.read_bytes())
        result = validate_prospective(value)
        self.assertEqual(result['arithmetic'], 'feasible')
        self.assertEqual(result['execution_admission'], 'unavailable')
        self.assertEqual(len(result['unresolved']), 6)
        for kind in ('missing', 'cost', 'order', 'stop'):
            changed = copy.deepcopy(value)
            if kind == 'missing': changed['step_costs']['numba_compiled'].pop('setup')
            elif kind == 'cost': changed['step_costs']['numba_compiled']['request'] = 1e9
            elif kind == 'order': changed['order'] = changed['order'][::-1]
            else: changed['stop_rules'].remove('busy')
            with self.subTest(kind=kind), self.assertRaises(ComparisonError): validate_prospective(changed)
        changed = copy.deepcopy(value)
        changed['order'][1:3] = changed['order'][1:3][::-1]
        self.assertEqual(validate_prospective(changed)['execution_admission'], 'unavailable')
        changed = copy.deepcopy(value)
        changed['step_costs']['control_before']['request'] -= 1.
        changed['step_costs']['numba_source']['request'] += 1.
        self.assertNotEqual(result['protocol_sha256'], validate_prospective(changed)['protocol_sha256'])
        # Even unsupported caller qualification assertions grant no admission.
        changed['qualification'] = dict.fromkeys(value['qualification'], 'qualified')
        self.assertEqual(validate_prospective(changed)['qualification_claims'], 'unverified')
        tool = Path(__file__).resolve().parents[1] / 'tools/bench_comparison.py'
        run = subprocess.run([sys.executable, str(tool)], input=json.dumps(value),
                             text=True, capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['execution_admission'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
